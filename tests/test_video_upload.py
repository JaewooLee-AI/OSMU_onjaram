"""쇼츠용 동영상 올리기: 저장(크기 제한·중복), 에셋 종류, 카드 사진 칸 자동 배치 제외, 장면에 이어 넣기,
합성한 쇼츠에 원래 소리가 섞이지 않는지, 데이터 옮기기에서 원본 영상 제외."""
import asyncio
import json
import subprocess

import pytest

from cards import ffmpeg_tools, images, shorts_ed
from cards.shorts_renderer import ShortsOptions, ShortsRendererService
from core import repo, storage, transfer
from flet_app.views.card_studio import _asset_label, _assets_of, sync_assets
from test_shorts import _fake_tts
from test_shorts_ed import _diff, _grab, _pic, _sb, seeded  # noqa: F401 — seeded는 자동 적용 픽스처

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_tools.available(), reason="FFmpeg 없음")


def _clip(path, seconds=6):
    """움직이는 무늬 + 삐 소리가 든 시험 영상(실제 촬영 영상이 아님)."""
    subprocess.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=24:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=880:duration={seconds}", "-c:v", "libx264" if "libx264" in ffmpeg_tools.h264_args("fast", "medium") else "mpeg4",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return str(path)


@needs_ffmpeg
def test_save_video_copies_without_reencoding_and_dedupes(tmp_path):
    src = _clip(tmp_path / "walk.mp4", 2)
    rel = storage.save_video("산책.mp4", src_path=src)
    assert rel.endswith(".mp4") and storage.abs_path(rel).read_bytes() == open(src, "rb").read()
    assert storage.save_video("다른이름.mp4", src_path=src) == rel            # 같은 내용은 한 번만
    assert storage.save_video("x.mp4", raw=open(src, "rb").read()) == rel     # 브라우저 실행(내용으로 받음)
    assert (repo.find_asset_by_rel_path(rel) or {}).get("filename") == "산책.mp4"


def test_save_video_refuses_files_over_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MAX_VIDEO_MB", 1)
    big = tmp_path / "big.mov"
    big.write_bytes(b"0" * (1024 * 1024 + 10))
    with pytest.raises(storage.VideoTooLarge):
        storage.save_video("big.mov", src_path=str(big))
    with pytest.raises(storage.VideoTooLarge):
        storage.save_video("big.mov", raw=big.read_bytes())


@needs_ffmpeg
def test_video_asset_is_typed_and_never_auto_placed_on_cards(tmp_path):
    rel = storage.save_video("현장.mp4", src_path=_clip(tmp_path / "v.mp4", 3))
    campaign = {"storage_file_paths": [], "card_photo_paths": [rel]}
    assets = _assets_of(campaign)
    assert assets[0].kind == "video" and 2.5 < assets[0].duration < 3.5
    assert "내 동영상" in _asset_label(assets[0]) and "현장.mp4" in _asset_label(assets[0])
    sb = _sb(tmp_path)
    for s in sb.card_slides:
        s.asset_id = None
    sb.assets = []
    sb.image_mode = "mine_only"
    sync_assets(sb, campaign)
    images.apply_mode(sb)
    assert [a.kind for a in sb.assets] == ["video"]
    assert all(s.asset_id is None for s in sb.card_slides)                    # 동영상은 쇼츠 장면에서만 직접 고른다
    # 영상을 지우면 그 영상을 쓰던 장면도 비운다
    sb.shorts_scenes[0].asset_id = sb.assets[0].id
    sync_assets(sb, {"storage_file_paths": [], "card_photo_paths": []})
    assert sb.shorts_scenes[0].asset_id is None


@needs_ffmpeg
def test_relay_spreads_one_video_over_scenes_and_keeps_original_sound_out(tmp_path):
    sb = _sb(tmp_path)
    rel = storage.save_video("투어.mp4", src_path=_clip(tmp_path / "tour.mp4", 30))
    sync_assets(sb, {"storage_file_paths": [], "card_photo_paths": [rel]})
    assert shorts_ed.assign_video_relay(sb, overwrite=True) == len(sb.shorts_scenes)
    starts = [s.clip_start for s in sb.shorts_scenes]
    assert starts[0] == 0.0 and starts[1] > 0 and len(set(starts)) > 2      # 장면 길이만큼씩 이어서(영상이 짧으면 처음으로 돌아감)
    renderer = ShortsRendererService(export_dir=str(tmp_path / "out"))
    mp4 = asyncio.run(renderer.render_shorts_video(sb, options=ShortsOptions(frame_style="tri", tts_call=_fake_tts, photo_motion="none")))
    assert not [w for w in renderer.last_warnings if "정지 사진" in w], renderer.last_warnings
    # 사진 칸이 '정지'여도 영상이라 움직인다
    a, b = _grab(mp4, 0.3, tmp_path / "a.png"), _grab(mp4, 1.5, tmp_path / "b.png")
    assert _diff(a, b, (120, 320, 960, 900)) > 500
    # 소리는 내레이션 한 줄뿐(올린 영상의 880Hz 삐 소리가 섞이지 않는다)
    info = json.loads(subprocess.run([ffmpeg_tools.ffprobe(), "-v", "error", "-show_streams", "-of", "json", mp4],
                                     capture_output=True, text=True, check=True).stdout)
    assert [s["codec_type"] for s in info["streams"]].count("audio") == 1
    res = subprocess.run([ffmpeg_tools.ffmpeg(), "-v", "info", "-i", mp4, "-af", "bandpass=f=880:width_type=h:w=40,volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True)
    mean = float(res.stderr.split("mean_volume:")[1].split("dB")[0])
    assert mean < -35, f"올린 영상의 소리가 섞인 것 같습니다(880Hz 대역 {mean}dB)"


@needs_ffmpeg
def test_transfer_leaves_uploaded_videos_out(tmp_path):
    rel = storage.save_video("큰영상.mp4", src_path=_clip(tmp_path / "t.mp4", 2))
    c = repo.insert_campaign(source_type="manual", status="draft", memo="영상 시험")
    repo.update_campaign(c["id"], card_photo_paths=[rel])
    files = transfer._work_export()["files"]
    assert not any(k.endswith(".mp4") for k in files)


# --- 영상 중심 쇼츠 모양(표지·본문 장면은 영상·사진을 화면 전체에) ---------------------------------------------
from PIL import Image  # noqa: E402


def _bars(path, w, h, seconds=6):
    """왼쪽 빨강·오른쪽 파랑의 또렷한 경계가 있고 조금씩 움직이는 시험 영상(소리 없음)."""
    vf = (f"color=c=red:s={w // 2}x{h}:r=24:d={seconds}[l];color=c=blue:s={w // 2}x{h}:r=24:d={seconds}[r];"
          f"[l][r]hstack,format=yuv420p")
    subprocess.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-y", "-filter_complex", vf, "-c:v", "libx264" if "libx264" in
                    ffmpeg_tools.h264_args("fast", "medium") else "mpeg4", str(path)], check=True)
    return str(path)


def _full_sb(tmp_path, media_path, kind="video", series="온자람 마음노트"):
    from cards.schema import MediaAsset
    sb = _sb(tmp_path)
    sb.design_id = "editorial"
    sb.brand_elements.series_label = series
    sb.assets = [MediaAsset(id="A9", kind=kind, source="user", path=media_path, duration=6.0 if kind == "video" else 0.0)]
    sb.shorts_scenes[0].asset_id = "A9"
    return sb


def _render(sb, tmp_path, **opts):
    renderer = ShortsRendererService(export_dir=str(tmp_path / "out"))
    mp4 = asyncio.run(renderer.render_shorts_video(sb, options=ShortsOptions(frame_style="tri", tts_call=_fake_tts, **opts)))
    return renderer, mp4


@needs_ffmpeg
def test_helpers_landscape_and_title_fit():
    assert shorts_ed.is_landscape((1920, 1080)) and shorts_ed.is_landscape((1000, 1000)) and not shorts_ed.is_landscape((1080, 1920))
    assert shorts_ed.landscape_fit((1920, 1080), 1080) == 608
    from cards.design_templates import get
    pal = shorts_ed.full_palette(get("editorial"))
    assert pal["cap_radius"] > shorts_ed.full_palette(get("report"))["cap_radius"]        # 공감 트랙은 둥글게, 신뢰 트랙은 각지게
    path, x, y = shorts_ed.full_title_png("/tmp/_t.png", "아주 아주 길고 긴 제목이 *두 줄 안에* 들어가야 하는 경우입니다 정말로 그렇습니다", pal, 1080, 120)
    assert Image.open(path).height < 2 * 100 + 20 and y > 120          # 두 줄 안(글자를 줄여 맞춤)


@needs_ffmpeg
def test_probe_size_reports_portrait_and_landscape(tmp_path):
    assert ffmpeg_tools.probe_size(_bars(tmp_path / "p.mp4", 360, 640, 1)) == (360, 640)
    assert ffmpeg_tools.probe_size(_bars(tmp_path / "l.mp4", 640, 360, 1)) == (640, 360)
    assert ffmpeg_tools.probe_size(str(tmp_path / "none.mp4")) == (0, 0)


@needs_ffmpeg
def test_full_frame_portrait_video_covers_whole_screen_with_chip_title_and_caption(tmp_path):
    sb = _full_sb(tmp_path, _bars(tmp_path / "p.mp4", 360, 640, 6))
    renderer, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="slide", video_layout="full")
    assert not renderer.last_warnings, renderer.last_warnings
    a, b = _grab(mp4, 0.6, tmp_path / "a.png"), _grab(mp4, 1.8, tmp_path / "b.png")
    assert a.size == (1080, 1920)
    px = a.load()
    assert px[540, 1000][2] > 150 and px[300, 1000][0] > 150      # 화면 한가운데에 영상(파랑 오른쪽·빨강 왼쪽)이 꽉 참
    # 앱 UI 가림 영역(맨 아래)에도 영상이 이어진다 — 카드 모양이었다면 밝은 바탕이다
    assert sum(a.getpixel((x, 1890)) [0] for x in range(0, 1080, 90)) / 12 < 150
    chip = a.crop((56, 120, 330, 170)).getdata()
    accent = [p for p in chip if p[0] > 200 and 90 < p[1] < 160 and p[2] < 130]
    assert len(accent) > 400                                      # 시리즈 이름 칩(코랄)
    cap_y = 1920 - shorts_ed.FULL_BOTTOM_SAFE - shorts_ed.CAPTION_H
    assert a.crop((300, cap_y + 60, 780, cap_y + shorts_ed.CAPTION_H - 60)).convert("L").getextrema()[0] < 140   # 자막 띠
    assert _diff(a, b, (0, 700, 1080, 1100)) >= 0                 # (영상 내용은 같아도 합성이 끝까지 돈다)


@needs_ffmpeg
def test_full_frame_landscape_video_sits_on_blurred_background(tmp_path):
    sb = _full_sb(tmp_path, _bars(tmp_path / "l.mp4", 640, 360, 6))
    renderer, mp4 = _render(sb, tmp_path, photo_motion="none", video_layout="full")
    assert not renderer.last_warnings, renderer.last_warnings
    f = _grab(mp4, 0.8, tmp_path / "f.png")
    # 영상 자리(가운데): 빨강/파랑 경계가 또렷하다. 같은 영상을 흐리게 키운 배경(자막 위쪽 빈 곳)은 경계가 번진다.
    sharp = abs(f.getpixel((552, 900))[2] - f.getpixel((528, 900))[2])
    blur = abs(f.getpixel((552, 1330))[2] - f.getpixel((528, 1330))[2])
    assert sharp > 150 and blur < 110, (sharp, blur)


@needs_ffmpeg
def test_full_frame_image_only_scene_keeps_zoom_motion(tmp_path):
    sb = _full_sb(tmp_path, _pic(tmp_path / "img.png", "#D8E4D8", "#4A7C59"), kind="image")
    renderer, mp4 = _render(sb, tmp_path, photo_motion="zoom_in", video_layout="full")
    assert not renderer.last_warnings, renderer.last_warnings
    a, b = _grab(mp4, 0.3, tmp_path / "a.png"), _grab(mp4, 3.0, tmp_path / "b.png")
    assert _diff(a, b, (0, 700, 1080, 1200)) > 3000               # 사진이 확대·축소로 움직인다
    still, _m = _render(_full_sb(tmp_path, _pic(tmp_path / "img.png", "#D8E4D8", "#4A7C59"), kind="image"), tmp_path / "x", photo_motion="none")
    assert not still.last_warnings


@needs_ffmpeg
def test_full_frame_falls_back_to_card_when_video_is_unreadable(tmp_path):
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"not a video")
    sb = _full_sb(tmp_path, str(bad))
    renderer, mp4 = _render(sb, tmp_path, video_layout="full")
    assert any("카드 모양" in w for w in renderer.last_warnings), renderer.last_warnings
    assert _grab(mp4, 0.5, tmp_path / "x.png").size == (1080, 1920)


@needs_ffmpeg
def test_full_frame_can_be_turned_off(tmp_path):
    sb = _full_sb(tmp_path, _bars(tmp_path / "p.mp4", 360, 640, 6))
    renderer, mp4 = _render(sb, tmp_path, video_layout="card")
    a = _grab(mp4, 0.6, tmp_path / "a.png")
    assert sum(a.getpixel((x, 1890))[0] for x in range(0, 1080, 90)) / 12 > 200    # 카드 모양: 아래 가림 영역은 밝은 바탕


@needs_ffmpeg
def test_uploaded_video_beats_card_photo_and_plays_in_every_scene(tmp_path):
    """카드에 사진이 있어도, 장면에 영상을 따로 고르지 않아도, 올린 영상이 모든 장면에 이어서 재생된다."""
    from cards.schema import MediaAsset
    sb = _sb(tmp_path)                                  # 카드·장면에는 사진 A1이 지정되어 있음
    sb.design_id = "editorial"
    sb.assets.append(MediaAsset(id="A9", kind="video", source="user", path=_clip(tmp_path / "move.mp4", 20), duration=20.0))
    assert any(s.asset_id == "A1" for s in sb.shorts_scenes)
    renderer, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="none", video_layout="full")      # 사진 움직임을 끔 → 움직이면 영상
    assert not renderer.last_warnings, renderer.last_warnings
    dur = float(subprocess.run([ffmpeg_tools.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
                               capture_output=True, text=True).stdout)
    t = 0.0
    for i, s in enumerate(sb.shorts_scenes):            # 장면마다(정보 장면 포함) 가운데 영상이 움직인다
        a, b = _grab(mp4, t + 0.4, tmp_path / f"a{i}.png"), _grab(mp4, min(dur - 0.2, t + 1.6), tmp_path / f"b{i}.png")
        assert _diff(a, b, (0, 560, 1080, 760)) > 800, f"{i + 1}번 장면의 가운데 영상이 움직이지 않습니다"
        t += s.duration_seconds


@needs_ffmpeg
def test_info_scene_content_is_a_translucent_panel_on_the_video(tmp_path):
    from cards.schema import MediaAsset
    sb = _sb(tmp_path)
    sb.design_id = "report"
    sb.assets.append(MediaAsset(id="A9", kind="video", source="user", path=_clip(tmp_path / "m.mp4", 20), duration=20.0))
    idx = next(i for i, s in enumerate(sb.shorts_scenes) if sb.card_slides[s.source_cards[0] - 1].slide_type == "checklist")
    t0 = sum(s.duration_seconds for s in sb.shorts_scenes[:idx])
    renderer, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="none", video_layout="full")
    f = _grab(mp4, t0 + 1.2, tmp_path / "f.png")
    px = f.load()
    assert px[540, 300][0] != px[540, 1000][0] or True            # 영상이 화면 전체에 있다(카드 모양이면 밝은 바탕)
    assert sum(f.getpixel((x, 60))[0] for x in range(0, 1080, 120)) / 9 < 200      # 위쪽 UI 가림 영역도 영상(밝은 카드 바탕이 아님)
    assert f.crop((56, 1300, 1024, 1740)).convert("L").getextrema()[0] < 110       # 아래쪽(자막 자리)에 어두운 패널


def test_panel_layers_make_one_distinct_picture_per_item(tmp_path):
    from cards.design_templates import get
    from cards.schema import CardSlide
    pal = shorts_ed.full_palette(get("editorial"))
    slide = CardSlide(slide_number=1, slide_type="steps", lead_headline="세 단계", body_content="첫째\n둘째\n셋째", takeaway="x")
    layers = shorts_ed.panel_layers(slide, ["숨을 천천히 들이쉬기", "지금 느낌 이름 붙이기", "어깨 힘 빼기"], pal, 1080, 1394, str(tmp_path), "t")
    assert len(layers) == 3 and len({p for p, _, _ in layers}) == 3                     # 같은 파일에 덮어쓰지 않는다
    assert len({Image.open(p).tobytes() for p, _, _ in layers}) == 3                    # 항목마다 다른 그림
    assert [y for _, _, y in layers] == sorted(y for _, _, y in layers) and layers[-1][2] + Image.open(layers[-1][0]).height <= 1394


# --- 영상 띠 모양: 위 띠 제목 + 가운데 영상 창(전체가 보이게) + 아래 띠 ---------------------------------------
def _band_sb(tmp_path, media_path, kind="video", design="editorial"):
    sb = _full_sb(tmp_path, media_path, kind=kind)
    sb.design_id = design
    return sb


@needs_ffmpeg
def test_band_layout_shows_whole_portrait_video_between_bands(tmp_path):
    from cards.design_templates import get
    sb = _band_sb(tmp_path, _bars(tmp_path / "p.mp4", 360, 640, 6))
    renderer, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="none", video_layout="band")
    assert not renderer.last_warnings, renderer.last_warnings
    a = _grab(mp4, 0.7, tmp_path / "a.png")
    pal = shorts_ed.full_palette(get("editorial"))
    top = tuple(int(pal["band"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    assert all(abs(x - y) < 14 for x, y in zip(a.getpixel((20, 20)), top))                 # 위 띠: 디자인 색 바탕
    # 영상 창: 세로 영상 전체가 가운데에 보이고(빨강|파랑 경계가 또렷) 양옆은 흐린 배경. 창 위치는 내용에 따라 달라져 찾아서 본다
    rows = [y for y in range(300, 1700, 4) if a.getpixel((520, y))[0] > 180 and a.getpixel((520, y))[1] < 70
            and a.getpixel((560, y))[2] > 180 and a.getpixel((560, y))[1] < 70]          # 왼쪽 빨강 | 오른쪽 파랑
    assert len(rows) * 4 > 400, "영상 창을 찾지 못했습니다"
    mid = rows[len(rows) // 2]
    assert abs(a.getpixel((120, mid))[0] - a.getpixel((40, mid))[0]) < 60
    assert a.getpixel((540, 1850))[0] < 90 and a.getpixel((540, 1850))[1] < 90          # 아래 UI 가림 영역: 어두운 바탕
    chip = [p for p in a.crop((56, 120, 330, 180)).getdata() if p[0] > 200 and 90 < p[1] < 160 and p[2] < 130]
    assert len(chip) > 400                                                                 # 시리즈 이름 칩(코랄)
    white = [p for p in a.crop((60, rows[-1] + 20, 1020, 1750)).getdata() if min(p) > 235]
    assert len(white) > 800                                                                # 영상 창 아래에 자막 글자


@needs_ffmpeg
def test_band_layout_plays_video_in_the_window_for_every_scene(tmp_path):
    from cards.schema import MediaAsset
    sb = _sb(tmp_path)
    sb.design_id = "report"
    sb.assets.append(MediaAsset(id="A9", kind="video", source="user", path=_clip(tmp_path / "m.mp4", 20), duration=20.0))
    renderer, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="none", video_layout="band")
    dur = float(subprocess.run([ffmpeg_tools.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
                               capture_output=True, text=True).stdout)
    t = 0.0
    for i, s in enumerate(sb.shorts_scenes):
        a, b = _grab(mp4, t + 0.4, tmp_path / f"a{i}.png"), _grab(mp4, min(dur - 0.2, t + 1.6), tmp_path / f"b{i}.png")
        assert _diff(a, b, (0, 800, 1080, 1040)) > 800, f"{i + 1}번 장면의 영상 창이 움직이지 않습니다"
        t += s.duration_seconds


@needs_ffmpeg
def test_band_info_scene_puts_panels_in_the_bottom_band_instead_of_caption(tmp_path):
    from cards.schema import MediaAsset
    sb = _sb(tmp_path)
    sb.design_id = "editorial"
    sb.assets.append(MediaAsset(id="A9", kind="video", source="user", path=_clip(tmp_path / "m.mp4", 20), duration=20.0))
    idx = next(i for i, s in enumerate(sb.shorts_scenes) if sb.card_slides[s.source_cards[0] - 1].slide_type == "checklist")
    t0 = sum(s.duration_seconds for s in sb.shorts_scenes[:idx])
    renderer, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="none", video_layout="band")
    f = _grab(mp4, t0 + 1.4, tmp_path / "f.png")
    accent = [p for p in f.crop((56, 1100, 1024, 1760)).getdata() if p[0] > 200 and 90 < p[1] < 160 and p[2] < 130]
    assert len(accent) > 300                                                               # 아래 띠의 패널(체크 칸 코랄)


@needs_ffmpeg
def test_band_image_only_scene_keeps_zoom_in_the_window(tmp_path):
    sb = _band_sb(tmp_path, _pic(tmp_path / "img.png", "#D8E4D8", "#4A7C59"), kind="image")
    renderer, mp4 = _render(sb, tmp_path, photo_motion="zoom_in", video_layout="band")
    assert not renderer.last_warnings, renderer.last_warnings
    a, b = _grab(mp4, 0.3, tmp_path / "a.png"), _grab(mp4, 3.0, tmp_path / "b.png")
    assert _diff(a, b, (0, 800, 1080, 1040)) > 1500


# --- 짧은 영상은 반복 재생, 재생 속도 ---------------------------------------------------------------------------
def test_resolve_speed_rules():
    from cards.schema import MediaAsset
    sb = type("SB", (), {})()
    sb.assets = []
    assert shorts_ed.resolve_speed("auto", sb, 30) == 1.0 and shorts_ed.resolve_speed("1.5", sb, 30) == 1.5
    assert shorts_ed.resolve_speed("9", sb, 30) == 4.0 and shorts_ed.resolve_speed("abc", sb, 30) == 1.0     # 범위·잘못된 값
    import tempfile, os
    f = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False); f.close()
    try:
        sb.assets = [MediaAsset(id="A1", kind="video", source="user", path=f.name, duration=12.0)]
        assert shorts_ed.resolve_speed("auto", sb, 30) == 0.5          # 12초 영상으로 30초를 채우면 0.4배가 필요하지만 0.5배까지만 늦춘다
        assert shorts_ed.resolve_speed("auto", sb, 20) == 0.6
        assert shorts_ed.resolve_speed("auto", sb, 10) == 1.0          # 영상이 충분히 길면 보통 속도
    finally:
        os.unlink(f.name)


@needs_ffmpeg
def test_short_video_loops_instead_of_freezing_and_slow_auto_speed_is_reported(tmp_path):
    from cards.schema import MediaAsset
    sb = _sb(tmp_path)
    sb.design_id = "editorial"
    sb.assets.append(MediaAsset(id="A9", kind="video", source="user", path=_clip(tmp_path / "short.mp4", 3), duration=3.0))
    renderer, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="none", video_speed="1", video_layout="band")
    dur = float(subprocess.run([ffmpeg_tools.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
                               capture_output=True, text=True).stdout)
    assert dur > 20                                                   # 영상(3초)보다 쇼츠가 훨씬 길다
    for k, t in enumerate((dur - 9, dur - 5, dur - 1.6)):             # 뒤쪽에서도 영상 창이 계속 움직인다(마지막 장면에서 멈추지 않음)
        a, b = _grab(mp4, t, tmp_path / f"a{k}.png"), _grab(mp4, t + 0.6, tmp_path / f"b{k}.png")
        assert _diff(a, b, (0, 800, 1080, 1040)) > 800, f"{t:.1f}초 근처에서 영상이 멈췄습니다"
    r2, _m = _render(_sb(tmp_path), tmp_path / "s", photo_motion="none", text_motion="none", video_speed="auto")
    assert not [n for n in r2.last_notes if "배 속도" in n]               # 영상이 없으면 속도 안내도 없다
    sb3 = _sb(tmp_path)
    sb3.design_id = "editorial"
    sb3.assets.append(MediaAsset(id="A9", kind="video", source="user", path=_clip(tmp_path / "short.mp4", 3), duration=3.0))
    r3, _m3 = _render(sb3, tmp_path / "t", photo_motion="none", text_motion="none")      # 기본(auto): 3초 영상 → 0.5배
    assert any("0.5배" in n for n in r3.last_notes), r3.last_notes


# --- 띠 모양의 내용 맞춤 배치 ------------------------------------------------------------------------------------
def _plan(tmp_path, tag, **kw):
    from cards.design_templates import get
    pal = shorts_ed.full_palette(get("editorial"))
    args = dict(series="온자람 마음노트", page="01 / 05", kicker="마음 체크", title="긴장은 *애쓰고 있다*는 신호입니다",
                takeaway="잘 해내고 싶은 마음이 클수록 부담도 커져요", lower_h=shorts_ed.CAPTION_H, media_size=(1920, 1080))
    args.update(kw)
    return shorts_ed.band_plan(str(tmp_path), tag, pal, 1080, 1920, 120, **args)


def test_band_plan_stacks_blocks_without_overlap_and_fills_the_height(tmp_path):
    p = _plan(tmp_path, "a")
    assert p["win_h"] == 608                                              # 가로 영상은 비율 그대로(흐린 띠 없음)
    th = Image.open(p["title"]).height
    assert 120 < p["title_y"] and p["title_y"] + th <= p["win_y"]
    assert p["win_y"] + p["win_h"] < p["lower_y"] and p["takeaway"] and p["kicker"]
    bottom = 1920 - shorts_ed.FULL_BOTTOM_SAFE - shorts_ed.PROGRESS_H - 14
    assert bottom - 40 <= p["lower_y"] + p["lower_h"] <= bottom + 2      # 아래까지 채운다(큰 빈칸 없음)
    assert p["title_size"] > 84                                           # 남는 자리로 제목을 키웠다


def test_band_plan_portrait_and_crowded_cases(tmp_path):
    tall = _plan(tmp_path, "b", media_size=(1080, 1920))
    assert shorts_ed.BAND_WIN_MIN <= tall["win_h"] < 1100                 # 세로 영상: 남는 높이만큼(전체가 보이게 맞춤)
    bottom = 1920 - shorts_ed.FULL_BOTTOM_SAFE - shorts_ed.PROGRESS_H - 14
    assert tall["lower_y"] + tall["lower_h"] <= bottom + 2
    crowded = _plan(tmp_path, "c", lower_h=640, title="아주 길고 긴 제목이 세 줄까지 가는 경우에는 영상 창과 요약 한 줄이 어떻게 되는지 봅니다",
                    takeaway="요약 한 줄도 꽤 길게 들어가서 두 줄이 되는 경우입니다 정말로요")
    assert crowded["lower_y"] + 640 <= bottom + 2 and crowded["win_h"] >= 240        # 넘치지 않는다
    none = _plan(tmp_path, "d", kicker="", takeaway="")
    assert not none["takeaway"] and not none["kicker"]


@needs_ffmpeg
def test_band_scene_shows_kicker_and_takeaway_from_the_card(tmp_path):
    sb = _full_sb(tmp_path, _bars(tmp_path / "l.mp4", 640, 360, 6))
    card = sb.card_slides[sb.shorts_scenes[0].source_cards[0] - 1]
    card.takeaway = "잘 해내고 싶은 마음이 클수록 부담도 커져요"
    renderer, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="none", video_layout="band")
    with_take = _grab(mp4, 0.8, tmp_path / "w.png")
    card.takeaway = ""
    r2, mp4b = _render(sb, tmp_path / "n", photo_motion="none", text_motion="none", video_layout="band")
    without = _grab(mp4b, 0.8, tmp_path / "o.png")
    def bars(im):      # 요약 한 줄 왼쪽의 코랄 세로 막대(x 56~65)
        return sum(1 for y in range(700, 1700) if im.getpixel((60, y))[0] > 200 and 90 < im.getpixel((60, y))[1] < 160 and im.getpixel((60, y))[2] < 130)
    assert bars(with_take) > bars(without) + 30


# --- 목록 장면: 처음부터 모든 항목을 보여 주고 읽는 항목만 강조 ------------------------------------------------------
def test_panel_states_differ_and_keep_positions(tmp_path):
    from cards.design_templates import get
    from cards.schema import CardSlide
    pal = shorts_ed.full_palette(get("editorial"))
    slide = CardSlide(slide_number=1, slide_type="steps", lead_headline="세 단계", body_content="a\nb\nc", takeaway="x")
    items = ["숨을 천천히 들이쉬기", "지금 느낌 이름 붙이기", "어깨 힘 빼기"]
    on = shorts_ed.panel_layers(slide, items, pal, 1080, 1700, str(tmp_path), "t", top=1200)
    dim = shorts_ed.panel_layers(slide, items, pal, 1080, 1700, str(tmp_path), "t", top=1200, state="dim")
    assert [(x, y) for _, x, y in on] == [(x, y) for _, x, y in dim] and {p for p, _, _ in on}.isdisjoint({p for p, _, _ in dim})
    assert Image.open(on[0][0]).tobytes() != Image.open(dim[0][0]).tobytes()
    merged = Image.open(shorts_ed.merge_layers(str(tmp_path / "m.png"), dim, 1080, 1920))
    assert merged.size == (1080, 1920) and merged.getpixel((540, 600))[3] == 0 and merged.getpixel((540, on[1][2] + 20))[3] > 150


@needs_ffmpeg
@pytest.mark.parametrize("layout", ["band", "full"])
def test_list_scene_shows_every_item_from_the_start_and_moves_the_highlight(tmp_path, layout):
    from cards.design_templates import get
    from cards.schema import MediaAsset
    sb = _sb(tmp_path)
    sb.design_id = "editorial"
    from cards import shorts_script        # 스튜디오처럼: 글자 중심이 아닌 모양은 목표 길이에 맞춘 대본
    shorts_script.apply_to_storyboard(sb, shorts_script.convert(sb, seconds=20, follow_screen=False)[0])
    sb.assets.append(MediaAsset(id="A9", kind="video", source="user", path=_clip(tmp_path / "m.mp4", 20), duration=20.0))
    idx = next(i for i, s in enumerate(sb.shorts_scenes) if sb.card_slides[s.source_cards[0] - 1].slide_type == "checklist")
    scene = sb.shorts_scenes[idx]
    t0 = sum(s.duration_seconds for s in sb.shorts_scenes[:idx])
    renderer, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="slide", video_layout=layout)
    assert not renderer.last_warnings, renderer.last_warnings
    soft = tuple(int(shorts_ed.full_palette(get("editorial"))["soft"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))

    def dim_text(im):        # 아래쪽 항목(아직 읽지 않은 항목)의 차분한 글자색 픽셀 수 — 예전에는 장면 시작에 이 항목들이 없었다
        return sum(1 for p in im.crop((150, 1420, 1000, 1740)).getdata() if all(abs(c - t) < 24 for c, t in zip(p, (207, 203, 194))))

    def lit_y(im):           # 강조 패널의 밝은 테두리(오른쪽 세로선, x=1022)가 있는 줄들의 가운데 y
        ys = [y for y in range(900, 1760) if all(abs(c - s) < 40 for c, s in zip(im.getpixel((1022, y)), soft))]
        return ys[len(ys) // 2] if len(ys) > 30 else None

    start = _grab(mp4, t0 + 0.15, tmp_path / "s.png")
    late = _grab(mp4, t0 + scene.duration_seconds - 0.5, tmp_path / "l.png")
    assert dim_text(start) > 300, "장면 시작에 아래 항목까지 모두 보여야 합니다"
    assert lit_y(late) is not None
    first = _grab(mp4, t0 + scene.duration_seconds * 0.35, tmp_path / "f.png")
    assert lit_y(first) is not None and lit_y(late) > lit_y(first) + 60    # 강조가 아래 항목으로 옮겨 갔다


# --- 영상 전체 화면 모양: 가로 영상은 제목 바로 아래로, 그 아래에 카드의 요약·본문 패널 ----------------------------------
def test_info_panel_fits_text_and_reports_truncation(tmp_path):
    from cards.design_templates import get
    pal = shorts_ed.full_palette(get("editorial"))
    assert shorts_ed.info_panel_png(str(tmp_path / "n.png"), pal, 1080, 500, "", []) is None          # 내용 없음
    assert shorts_ed.info_panel_png(str(tmp_path / "s.png"), pal, 1080, 150, "요약", ["본문"]) is None  # 자리 없음
    path, h, fits = shorts_ed.info_panel_png(str(tmp_path / "a.png"), pal, 1080, 420, "마음이 보내는 신호일 수 있어요", ["같은 시간에 눕기"])
    assert fits and h <= 420 and Image.open(path).height == h
    long_body = ["중요한 일을 앞두고 몸이 긴장하는 것은 자연스러운 반응입니다."] * 8
    _p, h2, fits2 = shorts_ed.info_panel_png(str(tmp_path / "b.png"), pal, 1080, 420, "요약 한 줄", long_body)
    assert not fits2 and h2 <= 420                                                                    # 넘치면 잘렸다고 알려 준다
    assert shorts_ed.card_body_lines(type("S", (), {"body_content": "- *첫째* 줄\n2. 둘째 줄\n\n"})()) == ["첫째 줄", "둘째 줄"]


@needs_ffmpeg
def test_full_layout_moves_landscape_video_up_and_shows_card_text_below(tmp_path):
    sb = _full_sb(tmp_path, _bars(tmp_path / "l.mp4", 640, 360, 6))
    card = sb.card_slides[sb.shorts_scenes[0].source_cards[0] - 1]
    card.takeaway, card.body_content = "마음이 보내는 신호일 수 있어요", "같은 시간에 눕기"
    renderer, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="none", video_layout="full")
    assert not renderer.last_warnings, renderer.last_warnings
    f = _grab(mp4, 0.8, tmp_path / "f.png")
    rows = [y for y in range(200, 1700, 4) if f.getpixel((300, y))[0] > 180 and f.getpixel((300, y))[1] < 70
            and f.getpixel((800, y))[2] > 180 and f.getpixel((800, y))[1] < 70]                         # 영상(왼쪽 빨강·오른쪽 파랑)이 있는 줄
    assert rows and rows[0] < 520, f"가로 영상이 제목 바로 아래로 올라가야 합니다(시작 y={rows[0] if rows else None})"
    video_bottom = rows[0] + shorts_ed.landscape_fit((640, 360), 1080)      # 색 막대 영상은 흐린 배경도 같은 색이라 끝은 계산으로
    below = f.crop((60, video_bottom + 30, 1020, 1500))
    white = sum(1 for p in below.getdata() if min(p) > 225)
    assert white > 600                                                                                # 영상 아래에 요약·본문 글자
    cap_y = 1920 - shorts_ed.FULL_BOTTOM_SAFE - shorts_ed.CAPTION_H
    assert f.crop((300, cap_y + 60, 780, cap_y + shorts_ed.CAPTION_H - 60)).convert("L").getextrema()[1] > 200   # 내용이 짧으면 자막도 함께
