"""에디토리얼 쇼츠 전용 화면: 칸 위치 기록, 자막 나누기·시각, 목록 순차 등장, 사진 칸만 움직임, 미디어 바꿔 끼우기(두 장·영상)."""
import asyncio
import subprocess

import pytest
from PIL import Image, ImageChops, ImageDraw

from cards import ffmpeg_tools, shorts_ed, shorts_script
from cards.card_renderer import CardNewsRendererService
from cards.director import plan_cards
from cards.schema import MediaAsset
from cards.shorts_renderer import ShortsOptions, ShortsRendererService
from core import repo
from core.brand_seed import seed_if_empty
from test_shorts import TEXT, _fake_tts

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_tools.available(), reason="FFmpeg 없음")


@pytest.fixture(autouse=True)
def seeded():
    seed_if_empty()
    repo.set_slot("tts", repo.upsert_model("google", "tts-ed", "T", ["tts"], per_second=0.01))


def _pic(path, c1, c2):
    img = Image.new("RGB", (1200, 900), c1)
    d = ImageDraw.Draw(img)
    for i in range(0, 1200, 80):
        d.ellipse([i, 200 + (i % 240), i + 160, 360 + (i % 240)], fill=c2)
    img.save(path)
    return str(path)


def _sb(tmp_path):
    sb, _ = plan_cards(TEXT, "empathy", use_llm=False, count=5)
    sb.assets = [MediaAsset(id="A1", kind="image", source="ai", path=_pic(tmp_path / "p1.png", "#D8E4D8", "#4A7C59"))]
    for s in sb.card_slides:
        if s.slide_type in ("cover", "body"):
            s.asset_id = "A1"
    scenes, _ = shorts_script.convert(sb, seconds=20)
    shorts_script.apply_to_storyboard(sb, scenes)
    return sb


def _grab(mp4, t, out):
    subprocess.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-y", "-ss", str(t), "-i", mp4, "-frames:v", "1", str(out)], check=True)
    return Image.open(out).convert("RGB")


def _diff(a, b, box):
    return sum(ImageChops.difference(a.crop(box), b.crop(box)).convert("L").point(lambda v: 255 if v > 24 else 0).histogram()[255:])


def test_layout_records_photo_and_row_boxes(tmp_path):
    sb = _sb(tmp_path)
    r = CardNewsRendererService(export_dir=str(tmp_path / "c"))
    asyncio.run(r.render_slide(sb, 0))
    assert r.ed_regions["photo"]["box"][3] > r.ed_regions["photo"]["box"][1] and r.ed_regions["rows"] == []
    check = next(i for i, s in enumerate(sb.card_slides) if s.slide_type == "checklist")
    asyncio.run(r.render_slide(sb, check))
    rows = r.ed_regions["rows"]
    assert len(rows) >= 2 and all(b[1] > a[3] for a, b in zip(rows, rows[1:]))   # 위에서 아래로 겹치지 않게


def test_caption_chunks_and_times():
    text = "요즘 이유 없이 지치고 잠도 오지 않아요. 마음이 보내는 신호일 수 있어요. " + "아주 긴 문장 " * 30
    chunks = shorts_ed.caption_chunks(text, 1080 - 2 * 72 - 64)
    assert chunks[0] == "요즘 이유 없이 지치고 잠도 오지 않아요." and len(chunks) > 3
    times = shorts_ed.caption_times(chunks, 0.5, 10.0, 12.0)
    assert times[0][0] == 0.5 and times[-1][1] == 12.0
    assert all(a[1] == pytest.approx(b[0]) for a, b in zip(times, times[1:]))   # 빈틈 없이 이어짐
    assert shorts_ed.row_times(3, 1.0, 6.0) == sorted(shorts_ed.row_times(3, 1.0, 6.0))
    assert shorts_ed.row_times(3, 1.0, 6.0, already_shown=True) == [0.0, 0.0, 0.0]


def test_media_for_prefers_override_then_scene_then_card(tmp_path):
    sb = _sb(tmp_path)
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"x")
    sb.assets.append(MediaAsset(id="V1", kind="video", source="user", path=str(vid)))
    scene, slide = sb.shorts_scenes[0], sb.card_slides[0]
    assert shorts_ed.media_for(sb, scene, slide).kind == "image"
    scene.asset_id, scene.clip_start = "V1", 2.0
    m = shorts_ed.media_for(sb, scene, slide)
    assert (m.kind, m.clip_start, m.moves_by_itself) == ("video", 2.0, True)
    pair = shorts_ed.SceneMedia("image_pair", [sb.assets[0].path, sb.assets[0].path])
    assert shorts_ed.media_for(sb, scene, slide, {0: pair}, 0) is pair
    assert not shorts_ed.SceneMedia("image_pair", [sb.assets[0].path]).usable()   # 두 장이 아니면 쓰지 않음


@needs_ffmpeg
@pytest.mark.parametrize("design", ["editorial", "report"])
def test_editorial_shorts_caption_rows_and_photo_slot_motion(tmp_path, design):
    sb = _sb(tmp_path)
    sb.design_id = design
    p2 = _pic(tmp_path / "p2.png", "#F3E2DA", "#E07A5F")
    renderer = ShortsRendererService(export_dir=str(tmp_path / "out"))
    mp4 = asyncio.run(renderer.render_shorts_video(sb, options=ShortsOptions(
        frame_style="tri", tts_call=_fake_tts, photo_motion="zoom_in", text_motion="slide",
        media_overrides={1: shorts_ed.SceneMedia("image_pair", [sb.assets[0].path, p2])})))
    assert not renderer.last_warnings, renderer.last_warnings
    # 첫 장면(표지): 사진 칸은 움직이고 머리줄·제목은 그대로
    probe = CardNewsRendererService(export_dir=str(tmp_path / "probe"))
    probe.HEIGHT, probe.safe_top = 1920, renderer.ED_SAFE_TOP
    probe.safe_bottom, probe.FOLLOW_ASPECT, probe.ED_SHORTS = renderer.ED_SAFE_BOTTOM + shorts_ed.CAPTION_H, False, True
    asyncio.run(probe.render_slide(sb, 0))
    x0, y0, x1, y1 = probe.ed_regions["photo"]["box"]
    a, b = _grab(mp4, 0.2, tmp_path / "a.png"), _grab(mp4, 1.6, tmp_path / "b.png")
    assert a.size == (1080, 1920)
    assert _diff(a, b, (x0 + 10, y0 + 10, x1 - 10, y1 - 10)) > 500
    assert _diff(a, b, (0, 0, 1080, y0 - 10)) == 0
    # 큰 자막 띠: 아래 가림 영역 바로 위에 색 칸이 있다
    cap_y = 1920 - renderer.ED_SAFE_BOTTOM - shorts_ed.CAPTION_H
    band = a.crop((200, cap_y + 60, 880, cap_y + shorts_ed.CAPTION_H - 60)).convert("L")
    assert band.getextrema()[0] < 120          # 진한 자막 칸
    assert a.crop((0, 1920 - 200, 1080, 1920)).convert("L").getextrema()[0] > 200   # 아래 UI 가림 영역은 비어 있음


def test_ed_segment_falls_back_to_still_photo_when_media_fails(tmp_path):
    if not ffmpeg_tools.available():
        pytest.skip("FFmpeg 없음")
    sb = _sb(tmp_path)
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"not a video")
    renderer = ShortsRendererService(export_dir=str(tmp_path / "out"))
    mp4 = asyncio.run(renderer.render_shorts_video(sb, options=ShortsOptions(
        frame_style="tri", tts_call=_fake_tts, media_overrides={0: shorts_ed.SceneMedia("video", [str(bad)])})))
    assert any("정지 사진" in w for w in renderer.last_warnings)
    assert _grab(mp4, 0.5, tmp_path / "x.png").size == (1080, 1920)


def test_script_never_cuts_a_sentence_and_reads_all_list_items():
    from cards.schema import CardSlide, EditableStoryboard
    body = ("중요한 과제를 마주하면 우리 뇌는\n스스로를 보호하기 위해 에너지를 모아요.\n"
            "문제가 있어서 나타나는 반응이 아니니\n애쓰는 나를 먼저 따뜻하게 안아주세요.")
    assert shorts_script._prose_sentences(body) == [
        "중요한 과제를 마주하면 우리 뇌는 스스로를 보호하기 위해 에너지를 모아요.",
        "문제가 있어서 나타나는 반응이 아니니 애쓰는 나를 먼저 따뜻하게 안아주세요."]
    cards = [CardSlide(slide_number=1, slide_type="cover", lead_headline="요즘 마음이 바쁜가요?", body_content="한 해의 마무리를 앞두고\n조급해지는 날들을 위한\n이야기", takeaway=""),
             CardSlide(slide_number=2, slide_type="body", lead_headline="뇌가 방어 상태를 켠 거예요", body_content=body, takeaway=""),
             CardSlide(slide_number=3, slide_type="checklist", lead_headline="이런 모습이 있나요?",
                       body_content="턱에 힘이 들어간다\n작은 일에도 예민하다\n쉽게 잠들지 못한다\n쉬는 시간도 불편하다", takeaway="")]
    sb = EditableStoryboard(title="t", target_audience="a", tone_and_manner="b", visual_style="c", is_anonymized=False,
                            sns_caption="", card_slides=cards)
    for sec in (20, 30, 45, 60):
        scenes, report = shorts_script.convert(sb, seconds=sec)
        for s in scenes:   # 모든 장면이 문장 끝으로 끝난다(줄 중간 '우리 뇌는.' 같은 끊김 없음)
            assert s.narration_script.endswith((".", "?", "!")) and "뇌는." not in s.narration_script and "앞두고." not in s.narration_script
        check = scenes[2].narration_script
        assert all(x in check for x in ("턱에 힘이", "작은 일에도", "쉽게 잠들지", "쉬는 시간도")) and "첫째" not in check
    scenes, report = shorts_script.convert(sb, seconds=10)     # 목록만으로도 목표를 넘으면 자르지 않고 알려 준다
    assert any("목표 길이" in w for w in report["warnings"])


def test_rows_appear_when_their_item_is_spoken():
    narration = "이런 모습이 있나요? 턱에 힘이 들어간다. 작은 일에도 예민하다. 쉽게 잠들지 못한다."
    items = ["턱에 힘이 들어간다", "작은 일에도 예민하다", "쉽게 잠들지 못한다"]
    t = shorts_ed.row_times_from_text(narration, items, 1.0, 10.0)
    assert t == sorted(t) and t[0] > 1.5 and t[-1] < 11.0
    assert abs(t[1] - (1.0 + 10.0 * narration.find("작은 일에") / len(narration) - 0.15)) < 1e-6
    assert shorts_ed.row_times_from_text("다른 말", items, 1.0, 10.0) == shorts_ed.row_times(3, 1.0, 10.0)
