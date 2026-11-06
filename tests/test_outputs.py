"""한 번에 만들기(블로그·카드뉴스·쇼츠 선택) 시험 — LLM·영상 호출 없이."""
import os

import pytest

from core import repo
from core.brand_seed import seed_if_empty
from flet_app import outputs
from flet_app.views import card_studio

MEMO = "마음이 지칠 땐 쉬어가도 괜찮아요. 오늘은 10분만 눈을 감고 쉬어 보세요. 작은 쉼이 마음을 가볍게 해 줍니다. 당신 잘못이 아니에요."


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    seed_if_empty()
    monkeypatch.setattr(card_studio, "EXPORTS_DIR", str(tmp_path))
    return repo.insert_campaign(source_type="manual", status="awaiting_media", memo=MEMO)["id"]


def test_default_outputs_roundtrip():
    assert outputs.default_outputs() == ["blog", "cards", "shorts"]
    outputs.save_default_outputs(["cards", "blog"])
    assert outputs.default_outputs() == ["blog", "cards"]


def test_nothing_chosen_is_an_error(campaign):
    with pytest.raises(ValueError):
        outputs.run_outputs(campaign, [])


def test_cards_only_renders_cards_without_shorts_or_blog(campaign, monkeypatch):
    monkeypatch.setattr(outputs, "run_pipeline", lambda *a, **k: pytest.fail("블로그를 만들면 안 됩니다"))
    result = outputs.run_outputs(campaign, ["cards"], use_ai=False)
    c = repo.get_campaign(campaign)
    sb = card_studio.load_storyboard(c)
    assert len(sb.card_slides) > 1 and not sb.shorts_scenes
    assert c["card_export_dir"] and os.path.exists(os.path.join(c["card_export_dir"], "slide_01.png"))
    assert any("카드뉴스" in m for m in result["made"])


def test_one_card_option_makes_exactly_one_card(campaign):
    outputs.run_outputs(campaign, ["cards"], one_card=True, use_ai=False)
    c = repo.get_campaign(campaign)
    sb = card_studio.load_storyboard(c)
    assert len(sb.card_slides) == 1 and sb.card_slides[0].slide_type == "single"
    assert os.path.exists(os.path.join(c["card_export_dir"], "slide_01.png"))


def test_cards_then_shorts_makes_script_but_no_video(campaign):
    outputs.run_outputs(campaign, ["cards", "shorts"], use_ai=False)
    c = repo.get_campaign(campaign)
    sb = card_studio.load_storyboard(c)
    assert sb.shorts_scenes and not c.get("shorts_video_path")


def test_shorts_only_plans_cards_without_rendering_them(campaign):
    result = outputs.run_outputs(campaign, ["shorts"], use_ai=False)
    c = repo.get_campaign(campaign)
    sb = card_studio.load_storyboard(c)
    assert sb.shorts_scenes and sb.card_slides
    assert not c.get("card_export_dir")
    assert any("기획만" in n for n in result["notes"])


def test_blog_runs_pipeline_and_cards_use_its_text(campaign, monkeypatch):
    def fake_pipeline(campaign_id, progress=None):
        repo.update_campaign(campaign_id, content="첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다.", title="제목")
    monkeypatch.setattr(outputs, "run_pipeline", fake_pipeline)
    outputs.run_outputs(campaign, ["blog", "cards"], use_ai=False)
    sb = card_studio.load_storyboard(repo.get_campaign(campaign))
    assert "첫 문장" in sb.card_slides[0].lead_headline


def test_cards_changed_after_render_are_flagged_stale_until_redrawn(campaign):
    outputs.run_outputs(campaign, ["cards"], use_ai=False)
    c = repo.get_campaign(campaign)
    sb = card_studio.load_storyboard(c)
    assert card_studio.stale_cards(sb) == []
    sb.card_slides[1].lead_headline = "고친 제목"
    assert card_studio.stale_cards(sb) == [1]
    card_studio.save_storyboard(campaign, sb)
    card_studio.render_one(campaign, sb, 1)
    assert card_studio.stale_cards(card_studio.load_storyboard(repo.get_campaign(campaign))) == []


def test_plan_honors_requested_card_count(campaign):
    sb, _ = outputs.plan_for_campaign(campaign, type_id="howto", use_ai=False, count=4)
    assert len(sb.card_slides) == 4
    sb, _ = outputs.plan_for_campaign(campaign, type_id="howto", use_ai=False, count=6)
    assert len(sb.card_slides) == 6


def test_edit_card_by_prompt_changes_only_asked_fields_and_flags_new_numbers(campaign, monkeypatch):
    from cards import edit as card_edit
    monkeypatch.setattr(card_edit, "get_configured_vendor", lambda slot=None: "google")
    sb, _ = outputs.plan_for_campaign(campaign, type_id="empathy", use_ai=False)
    card = sb.card_slides[1]
    old_body = card.body_content
    reply = '{"lead_headline": "더 짧은 제목 *쉼*", "takeaway": "하루 77번 쉬어요", "image_prompt": "Soft morning light on a wooden desk with a green plant"}'
    out = card_edit.edit_card(sb, 1, "제목을 짧게, 이미지는 아침 햇살로", generate=lambda **k: reply)
    assert set(out["changed"]) == {"lead_headline", "takeaway", "image_prompt"} and out["image_changed"]
    assert card.lead_headline == "더 짧은 제목 *쉼*" and card.body_content == old_body       # 말하지 않은 칸은 그대로
    assert card.image_prompt.startswith("Soft morning light")
    assert any("77" in w for w in out["warnings"])                                         # 카드에 없던 숫자는 경고
    with pytest.raises(ValueError):
        card_edit.edit_card(sb, 1, "  ", generate=lambda **k: reply)
    # 글만 바꾸는 요청에는 그림 장면을 건드리지 않는다
    out = card_edit.edit_card(sb, 1, "말투를 부드럽게", generate=lambda **k: '{"takeaway": "천천히 쉬어가요"}')
    assert out["changed"] == ["takeaway"] and not out["image_changed"]


@pytest.mark.parametrize("pack_id", ["empathy", "howto", "checklist", "big_number", "qna", "info_summary", "event_notice", "expert"])
def test_any_card_count_one_to_eight_works_for_every_type(pack_id):
    from cards import card_types
    pack = card_types.get(pack_id)
    for n in range(1, 9):
        seq = card_types.free_sequence(pack, n)
        assert len(seq) == n and all(s["archetype"] in card_types.VALID_ARCHETYPES for s in seq), (pack_id, n)
        if n >= 3:
            assert seq[0]["archetype"] == "cover" and seq[-1]["archetype"] == "call_to_action"


def test_plan_makes_exactly_the_chosen_count_even_below_the_types_minimum(campaign):
    for n in (1, 2, 3, 8):
        sb, _ = outputs.plan_for_campaign(campaign, type_id="checklist", use_ai=False, count=n)
        assert len(sb.card_slides) == n


def test_edit_card_style_applies_to_one_card_or_all_and_rejects_bad_values(campaign, monkeypatch):
    from cards import edit as card_edit
    monkeypatch.setattr(card_edit, "get_configured_vendor", lambda slot=None: "google")
    sb, _ = outputs.plan_for_campaign(campaign, type_id="howto", use_ai=False, count=4)
    reply = '{"style": {"bg": "#DCE9F7", "title_scale": 3.0, "fg": "파란색", "accent": "#e07a5f"}, "scope": "card"}'
    out = card_edit.edit_card(sb, 1, "배경을 연한 파란색으로, 제목을 아주 크게", generate=lambda **k: reply)
    assert out["changed"] == ["style"] and out["style_scope"] == "card"
    assert sb.card_slides[1].style == {"bg": "#DCE9F7", "title_scale": 2.0, "accent": "#E07A5F"}   # 배율은 범위로 자르고 색 이름(fg)은 버린다
    assert all(not c.style for i, c in enumerate(sb.card_slides) if i != 1)
    out = card_edit.edit_card(sb, 1, "모든 카드 글자 크게", generate=lambda **k: '{"style": {"body_scale": 1.2}, "scope": "all"}')
    assert out["style_scope"] == "all" and all(c.style.get("body_scale") == 1.2 for c in sb.card_slides)
    assert sb.card_slides[1].style["bg"] == "#DCE9F7"                                           # 기존 값은 합쳐진다
    card_edit.edit_card(sb, 1, "원래대로", generate=lambda **k: '{"style": {"reset": true}}')
    assert sb.card_slides[1].style == {} and sb.card_slides[0].style == {"body_scale": 1.2}


def test_card_style_changes_the_rendered_picture(campaign):
    import asyncio
    from PIL import Image, ImageChops
    from cards.card_renderer import CardNewsRendererService
    sb, _ = outputs.plan_for_campaign(campaign, type_id="howto", use_ai=False, count=3)
    renderer = CardNewsRendererService(export_dir=str(os.path.join(os.path.dirname(__file__), "_style_tmp")))
    try:
        base = Image.open(asyncio.run(renderer.render_slide(sb, 1))).convert("RGB").copy()
        sb.card_slides[1].style = {"bg": "#1B3A5C", "title_scale": 1.3}
        styled = Image.open(asyncio.run(renderer.render_slide(sb, 1))).convert("RGB").copy()
    finally:
        import shutil
        shutil.rmtree(os.path.join(os.path.dirname(__file__), "_style_tmp"), ignore_errors=True)
    assert ImageChops.difference(base, styled).getbbox() is not None
    assert styled.getpixel((5, 5)) == (0x1B, 0x3A, 0x5C)               # 배경이 실제로 바뀌었다


def test_text_scale_also_works_on_non_3tier_designs_without_touching_small_labels(campaign):
    import asyncio
    import shutil
    from PIL import Image, ImageChops
    from cards.card_renderer import CardNewsRendererService
    sb, _ = outputs.plan_for_campaign(campaign, type_id="event_notice", design_id="classic", use_ai=False, count=4)
    idx = next(i for i, c in enumerate(sb.card_slides) if c.slide_type == "event_info")
    out = os.path.join(os.path.dirname(__file__), "_scale_tmp")
    try:
        r = CardNewsRendererService(export_dir=out)
        base = Image.open(asyncio.run(r.render_slide(sb, idx))).convert("RGB").copy()
        sb.card_slides[idx].style = {"body_scale": 2.0}
        big = Image.open(asyncio.run(r.render_slide(sb, idx))).convert("RGB").copy()
    finally:
        shutil.rmtree(out, ignore_errors=True)
    assert ImageChops.difference(base, big).getbbox() is not None                       # 기본(글 중심) 디자인에서도 그림이 달라진다
    footer = (0, 1302, 1080, 1350)
    assert ImageChops.difference(base.crop(footer), big.crop(footer)).getbbox() is None  # 아래 연락처 줄(작은 글자)은 그대로


def test_tri_designs_draw_event_and_table_cards_in_the_same_3_tier_look(campaign):
    import asyncio
    import shutil
    from PIL import Image
    from cards import preview
    from cards.card_renderer import CardNewsRendererService
    sb, _ = outputs.plan_for_campaign(campaign, type_id="event_notice", design_id="tri-2-5-3", use_ai=False, count=4)
    sb.card_slides[1].slide_type = "event_info"
    sb.card_slides[1].body_content = "일시: 11월 25일\n장소: 센터 1층\n대상: 누구나"
    sb.card_slides[2].slide_type = "comparison_table"
    sb.card_slides[2].comparison_table = {"항목": ["혼자", "함께"], "부담": ["큼", "나눠짐"]}
    out = os.path.join(os.path.dirname(__file__), "_tri_tmp")
    try:
        r = CardNewsRendererService(export_dir=out)
        for i in (1, 2):
            im = Image.open(asyncio.run(r.render_slide(sb, i))).convert("RGB")
            assert im.size == (1080, 1350)
            assert im.getpixel((5, 5)) == (0xFA, 0xF8, 0xF5)      # 3단 바탕(헤더 줄이 있는 기본 모양이 아니다)
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_card_size_changes_height_only_for_3_tier_designs_and_not_for_shorts_frames(campaign):
    import asyncio
    import shutil
    from PIL import Image
    from cards.card_renderer import CardNewsRendererService
    out = os.path.join(os.path.dirname(__file__), "_size_tmp")
    try:
        sizes = {}
        for design, aspect in (("tri-2-5-3", "3:4"), ("tri-2-5-3", "9:16"), ("tri-2-5-3", "1:1"), ("classic", "9:16")):
            sb, _ = outputs.plan_for_campaign(campaign, type_id="howto", design_id=design, use_ai=False, count=3, aspect=aspect)
            assert sb.aspect == aspect
            sizes[(design, aspect)] = Image.open(asyncio.run(CardNewsRendererService(export_dir=out).render_slide(sb, 1))).size
        assert sizes[("tri-2-5-3", "3:4")] == (1080, 1440) and sizes[("tri-2-5-3", "9:16")] == (1080, 1920)
        assert sizes[("tri-2-5-3", "1:1")] == (1080, 1080)
        assert sizes[("classic", "9:16")] == (1080, 1350)               # 3단이 아니면 4:5 그대로
        # 쇼츠가 쓰는 3단 프레임은 카드 크기를 따르지 않고 자기 높이(1920)를 쓴다
        r = CardNewsRendererService(export_dir=out)
        r.HEIGHT, r.safe_top, r.safe_bottom, r.FOLLOW_ASPECT = 1920, 250, 250, False
        sb, _ = outputs.plan_for_campaign(campaign, type_id="howto", design_id="tri-2-5-3", use_ai=False, count=3, aspect="3:4")
        assert Image.open(asyncio.run(r.render_slide(sb, 1))).size == (1080, 1920)
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_card_only_photos_stay_out_of_the_blog_and_naver_publish(campaign, tmp_path):
    from ai_workers import formatting
    from PIL import Image
    paths = []
    for i, name in enumerate(("a", "b", "c")):
        p = tmp_path / f"{name}.jpg"
        Image.new("RGB", (50, 50), "#336699").save(p)
        paths.append(str(p))
    repo.update_campaign(campaign, storage_file_paths=["a.jpg", "b.jpg", "c.jpg"],
                         content="첫 문단.\n\n[IMAGE: a.jpg]\n\n둘째 문단.\n\n[IMAGE: b.jpg]\n\n끝.")
    c = repo.get_campaign(campaign)
    assert card_studio.blog_only_extras(c) == ["c.jpg"]                       # 본문에 안 쓰여 게시 때 뒤에 붙을 사진
    assert formatting.unplaced_photos(c["content"], c["storage_file_paths"]) == ["c.jpg"]
    assert card_studio.move_to_card_only(campaign, ["c.jpg"]) == 1
    c = repo.get_campaign(campaign)
    assert c["storage_file_paths"] == ["a.jpg", "b.jpg"] and c["card_photo_paths"] == ["c.jpg"]
    assert formatting.unplaced_photos(c["content"], c["storage_file_paths"]) == []   # 이제 게시에 안 붙는다
    assert card_studio.card_photo_list(c) == ["a.jpg", "b.jpg", "c.jpg"]              # 카드는 셋 다 쓴다
    assert card_studio.blog_only_extras(c) == []
