"""쇼츠 '글자 중심' 모양(typo): 카드 → 화면 내용, 읽을 시간만큼 장면 늘리기, 미디어별 배치(가로 창·세로 가득·글자만),
글자가 장면 시작에만 움직이고 멈춤, 영상이 실제로 재생됨, 영상을 못 읽으면 대신 만듦."""
import asyncio
import os
import subprocess

import pytest
from PIL import Image, ImageChops

from cards import ffmpeg_tools, shorts_typo
from cards.design_templates import get
from cards.schema import CardSlide, MediaAsset
from cards.shorts_renderer import ShortsOptions, ShortsRendererService
from cards import shorts_ed
from test_shorts import _fake_tts
from test_shorts_ed import _sb, seeded  # noqa: F401 — seeded는 자동 적용 픽스처

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_tools.available(), reason="FFmpeg 없음")


def _clip(path, size="640x360", seconds=4):
    subprocess.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=24:duration={seconds}",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def _frame(mp4, t):
    raw = subprocess.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", mp4, "-frames:v", "1", "-f", "image2pipe",
                          "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    import io
    return Image.open(io.BytesIO(raw)).convert("RGB")


def _changed(a, b, box):
    return sum(ImageChops.difference(a.crop(box), b.crop(box)).convert("L").point(lambda v: 255 if v > 24 else 0).histogram()[255:])


def _slide(t, **kw):
    base = dict(slide_number=1, slide_type=t, lead_headline="쉬어도 *피곤한* 이유", body_content="", takeaway="")
    base.update(kw)
    return CardSlide(**base)


# --- 카드 → 화면 내용 ---------------------------------------------------------------------------
def test_content_from_cards():
    c = shorts_typo.content_of(_slide("checklist", body_content="- 잠이 자주 깨요: 자고 일어나도 개운하지 않아요\n- 작은 일에도 짜증이 나요",
                                      takeaway="오래 이어지면 이야기를 나눠 보세요"), "마음 체크")
    assert c.kind == "list" and c.marker == "check" and c.kicker == "마음 체크"
    assert c.items[0] == ("잠이 자주 깨요", "자고 일어나도 개운하지 않아요") and c.items[1] == ("작은 일에도 짜증이 나요", "")
    assert shorts_typo.content_of(_slide("steps", body_content="1. 숨 고르기\n2. 적어 보기")).marker == "number"
    body = shorts_typo.content_of(_slide("body", body_content="쉬어도 피곤한 이유\n몸은 쉬어도 생각은 일해요.\n걱정을 적어 보세요.", takeaway="생각에도 쉼이 필요해요"))
    assert body.kind == "prose" and body.sub == "생각에도 쉼이 필요해요" and body.lines == ["몸은 쉬어도 생각은 일해요.", "걱정을 적어 보세요."]   # 제목과 같은 줄은 뺌
    cover = shorts_typo.content_of(_slide("cover", body_content="지친 마음도 돌봄이 필요해요.\n오늘은 신호를 살펴봐요."))
    assert cover.sub == "지친 마음도 돌봄이 필요해요." and cover.lines == ["오늘은 신호를 살펴봐요."]   # 표지는 첫 줄이 소개
    stat = shorts_typo.content_of(_slide("big_number", stat_value="97.14점", stat_label="만족도"))
    assert stat.kind == "stat" and stat.stat == ("97.14점", "만족도")
    cta = shorts_typo.content_of(_slide("call_to_action", body_content="055-000-0000으로 문의\n편하게 연락 주세요"), "", "055-000-0000", "창원시")
    assert cta.kind == "cta" and cta.phone == "055-000-0000" and cta.lines == ["편하게 연락 주세요"]      # 번호 줄은 큰 번호 칸으로


def test_helpers():
    assert shorts_typo.split_item("일정 - 매주 화요일") == ("일정", "매주 화요일")
    assert shorts_typo.split_item("그냥 한 줄") == ("그냥 한 줄", "")
    assert shorts_typo.count_up("97.14점", 0.5) == "48.57점" and shorts_typo.count_up("1,200명", 1.0) == "1,200명"
    short = shorts_typo.content_of(_slide("body", lead_headline="짧게"))
    long_ = shorts_typo.content_of(_slide("body", body_content="\n".join(["아주 긴 본문 문장이 이어집니다 정말로 길어요"] * 5), takeaway="요약 한 줄"))
    assert shorts_typo.read_seconds(short) == shorts_typo.READ_MIN < shorts_typo.read_seconds(long_) <= shorts_typo.READ_MAX
    assert ShortsOptions().video_layout == "typo"


@pytest.mark.parametrize("arr,size", [("window", (1920, 1080)), ("fill", (1080, 1920)), ("none", (0, 0))])
def test_layout_fits_above_progress_bar_and_keeps_min_window(arr, size):
    many = _slide("checklist", body_content="\n".join(f"- 항목 {i}: 설명이 조금 긴 문장입니다 {i}" for i in range(6)), takeaway="요약 한 줄입니다")
    c = shorts_typo.content_of(many, "마음 체크")
    sc = shorts_typo.TypoScene(c, shorts_ed.full_palette(get("editorial")), arr, size, "온자람 마음노트", "01 / 05", 60, False, True, (0, .2))
    assert sc.panel_y + sc.panel_h <= shorts_typo.CONTENT_BOTTOM + 2
    assert sc.title_y > shorts_typo.SAFE_TOP + 40
    if arr == "window":
        assert sc.win[3] >= shorts_typo.MIN_WIN and sc.win[1] > sc.title_y
    if arr == "fill":
        assert sc.kick_y >= shorts_typo.H * shorts_typo.FILL_TOP_FRAC          # 위쪽은 영상이 보이게 비움


# --- 실제 합성 ---------------------------------------------------------------------------------
def _render(sb, tmp_path, **opts):
    r = ShortsRendererService(export_dir=str(tmp_path / "out"))
    mp4 = asyncio.run(r.render_shorts_video(sb, options=ShortsOptions(frame_style="tri", tts_call=_fake_tts, **opts)))
    return r, mp4


@needs_ffmpeg
@pytest.mark.parametrize("design", ["editorial", "report"])
def test_typo_shorts_with_landscape_and_portrait_video(tmp_path, design):
    sb = _sb(tmp_path)
    sb.design_id = design
    land = _clip(tmp_path / "land.mp4", "640x360", 3)          # 짧은 영상 → 반복 재생
    port = _clip(tmp_path / "port.mp4", "360x640", 3)
    sb.assets += [MediaAsset(id="V1", kind="video", source="user", path=land, duration=3.0),
                  MediaAsset(id="V2", kind="video", source="user", path=port, duration=3.0)]
    sb.shorts_scenes[0].asset_id = "V2"         # 표지 = 세로 영상(화면 가득)
    sb.shorts_scenes[1].asset_id = "V1"         # 다음 = 가로 영상(창)
    for s in sb.card_slides:                     # 나머지는 미디어 없음(글자만)
        if s.slide_number > 2:
            s.asset_id = None
    sb.assets = [a for a in sb.assets if a.kind == "video"]
    r, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="slide")
    assert not [w for w in r.last_warnings if "읽지 못해" in w], r.last_warnings
    total = sum(1 for _ in sb.shorts_scenes)
    assert total >= 3 and os.path.getsize(mp4) > 10_000
    # 장면 1(세로 영상, 화면 가득): 위쪽 영상 부분이 시간에 따라 바뀐다(재생)
    a, b = _frame(mp4, 1.9), _frame(mp4, 2.6)
    assert _changed(a, b, (100, 300, 980, 560)) > 2000
    # 마지막 장면(가로 영상 창 + 상담 안내 패널): 창 안은 재생되고, 움직임이 끝난 패널 글자는 그대로다
    dur = float(subprocess.run([ffmpeg_tools.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
                               capture_output=True, text=True).stdout.strip())
    a, b = _frame(mp4, dur - 2.2), _frame(mp4, dur - 1.0)
    sc = shorts_typo.TypoScene(r._typo_content(sb, sb.card_slides[-1]), shorts_ed.full_palette(get(design)), "window", (640, 360),
                               "", "05 / 05", 90, True, True, (0, 1))
    x, y, w, h = sc.win
    assert _changed(a, b, (x + 20, y + 20, x + w - 20, y + h - 20)) > 2000
    assert _changed(a, b, (80, sc.panel_y + 10, 1000, min(sc.panel_y + sc.panel_h - 10, 1700))) < 300
    # 장면 시작 직후(글자가 나타나는 중)와 멈춘 뒤는 다르다
    early, settled = _frame(mp4, 0.1), _frame(mp4, 2.0)
    assert _changed(early, settled, (64, 1100, 1016, 1700)) > 5000


@needs_ffmpeg
def test_text_only_scene_and_scene_padding(tmp_path):
    sb = _sb(tmp_path)
    for s in sb.card_slides:
        s.asset_id = None
    sb.assets = []
    for sc in sb.shorts_scenes:
        sc.asset_id = None
    # 내레이션은 아주 짧게, 카드 글자는 많게 → 읽을 시간을 위해 장면이 늘어난다
    for sc in sb.shorts_scenes:
        sc.narration_script = "짧게."
    r, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="slide")
    dur = float(subprocess.run([ffmpeg_tools.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
                               capture_output=True, text=True).stdout.strip())
    n = len(sb.shorts_scenes)
    assert n * 1.0 + 0.5 < dur <= n * (1.0 + 0.3 + shorts_typo.PAD_MAX) + 0.5   # 늘리되 장면당 최대 PAD_MAX초(말이 오래 끊기지 않게)
    assert any("읽을 시간" in n for n in r.last_notes)


@needs_ffmpeg
def test_broken_video_falls_back_without_failing(tmp_path):
    sb = _sb(tmp_path)
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    sb.assets.append(MediaAsset(id="VB", kind="video", source="user", path=str(bad)))
    sb.shorts_scenes[0].asset_id = "VB"
    r, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="none")
    assert os.path.getsize(mp4) > 10_000
    assert any("읽지 못해" in w for w in r.last_warnings)


@needs_ffmpeg
def test_photo_window_scene_moves_with_zoom(tmp_path):
    sb = _sb(tmp_path)                    # 표지·본문에 가로 사진(1200x900)
    r, mp4 = _render(sb, tmp_path, photo_motion="zoom_in", text_motion="none")
    a, b = _frame(mp4, 0.5), _frame(mp4, 2.8)
    sc = shorts_typo.TypoScene(r._typo_content(sb, sb.card_slides[0]), shorts_ed.full_palette(get("editorial")), "window", (1200, 900),
                               "", "01 / 05", 90, False, False, (0, .2))
    x, y, w, h = sc.win
    assert _changed(a, b, (x + 10, y + 10, x + w - 10, y + h - 10)) > 500          # 창 안 사진이 천천히 커진다
    assert not r.last_warnings or all("읽지 못해" not in w for w in r.last_warnings)


@needs_ffmpeg
@pytest.mark.parametrize("layout", ["typo", "band"])
def test_video_ends_on_the_finished_last_screen_and_holds_it(tmp_path, layout):
    """마지막 장면 첫머리가 끝에 다시 붙어 그 화면(제목이 막 떠오르는 화면)으로 끝나던 버그. 끝은 완성된 끝 화면을 END_HOLD초 보여 준다."""
    from cards.shorts_renderer import END_HOLD
    sb = _sb(tmp_path)
    r, mp4 = _render(sb, tmp_path, photo_motion="none", text_motion="slide", video_layout=layout)
    dur = float(subprocess.run([ffmpeg_tools.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
                               capture_output=True, text=True).stdout.strip())
    raw = subprocess.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-sseof", "-0.05", "-i", mp4, "-frames:v", "1", "-f", "image2pipe",
                          "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    import io
    final = Image.open(io.BytesIO(raw)).convert("RGB")
    held = _frame(mp4, dur - END_HOLD + 0.3)
    box = (0, 0, 1080, shorts_typo.BAR_Y - 10)              # 진행 막대는 끝까지 움직이므로 뺀다
    assert _changed(held, final, box) < 500, "끝 화면이 마지막까지 그대로여야 합니다"
