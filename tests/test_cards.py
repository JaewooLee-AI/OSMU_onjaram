"""카드 엔진: 종류 팩·장 구성·기획(AI 없이)·렌더링 (LLM 호출 없음)."""
import asyncio
import json
import os

import pytest

from cards import card_types, design_templates
from cards.card_renderer import CardNewsRendererService
from cards.director import plan_cards
from cards.schema import MediaAsset
from core import repo
from core.brand_seed import seed_if_empty


@pytest.fixture(autouse=True)
def seeded():
    seed_if_empty()


def test_builtin_packs_all_valid_and_listed():
    packs, errors = card_types.load_all()
    assert not errors, errors
    assert {"info_summary", "empathy", "checklist", "howto", "qna", "big_number", "event_notice", "expert"} <= set(packs)
    for p in packs.values():
        assert card_types.validate(p) == []
        if len(p["sequence"]) == 1:   # 한 장 카드는 표지·상담 안내 없이 한 장으로 끝난다
            assert p["count"]["max"] == 1
            continue
        assert p["sequence"][0]["archetype"] == "cover" and p["sequence"][-1]["archetype"] == "call_to_action"


@pytest.mark.parametrize("count", [3, 4, 6, 8, 20])
def test_expand_sequence_fits_count_and_keeps_cover_and_cta(count):
    pack = card_types.get("info_summary")
    seq = card_types.expand_sequence(pack, count)
    want = card_types.clamp_count(pack, count)
    assert len(seq) == want
    assert seq[0]["archetype"] == "cover" and seq[-1]["archetype"] == "call_to_action"
    assert all(s["archetype"] == "numbered" for s in seq[1:-1])


def test_pack_without_repeat_keeps_fixed_length():
    seq = card_types.expand_sequence(card_types.get("event_notice"), 5)
    assert [s["archetype"] for s in seq] == ["cover", "event_info", "body", "call_to_action"]


def test_invalid_pack_is_rejected_with_reasons():
    bad = {"id": "Bad Id", "name": "", "sequence": [{"archetype": "hologram"}], "count": {"min": 5, "max": 2, "default": 3}}
    problems = card_types.validate(bad)
    assert len(problems) >= 4
    with pytest.raises(card_types.CardTypeError):
        card_types.save_custom(bad)


def test_custom_pack_added_overrides_and_survives_bad_files(tmp_path, monkeypatch):
    monkeypatch.setattr(card_types, "CUSTOM_DIR", str(tmp_path))
    mine = card_types.duplicate("howto", "my-howto", "내 안내")
    assert mine["status"] == "draft"
    packs, errors = card_types.load_all()
    assert "my-howto" in packs and not errors
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "bad.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")
    packs, errors = card_types.load_all()
    assert "my-howto" in packs and len(errors) == 2  # 깨진 팩은 목록에서 빠지고 이유만 남는다
    assert card_types.import_json(card_types.export_json("my-howto").replace("my-howto", "again"))["id"] == "again"
    assert card_types.delete_custom("my-howto") is True


def test_fit_warning():
    assert card_types.fit_warning(card_types.get("big_number"), "수치가 없는 글입니다.")
    assert not card_types.fit_warning(card_types.get("big_number"), "상담은 평균 15회기, 1회 50분 80,000원입니다.")
    assert card_types.fit_warning(card_types.get("event_notice"), "오늘 날씨가 좋네요.")
    assert card_types.has_placeholder("【제목】") and not card_types.has_placeholder("제목")


SOURCE = ("요즘 이유 없이 지치고 잠도 오지 않아요. 마음이 보내는 신호일 수 있어요.\n"
          "1. 같은 시간에 눕기\n2. 잠들기 전 화면 멀리하기\n3. 따뜻한 차 한 잔 마시기\n"
          "혼자 해결하기 어려우면 상담이라는 안전한 선택지가 있어요.")


def _fake_llm(slides_text, extra=None):
    def gen(vendor, prompt, system=None, max_tokens=0, note=None):
        slides = [{"slide_type": "x", "lead_headline": h, "body_content": b, "takeaway": t} for h, b, t in slides_text]
        return "```json\n" + json.dumps({"title": "제목", "slides": slides, "sns_caption": "캡션", "hashtags": ["마음돌봄"], **(extra or {})}) + "\n```"
    return gen


def _llm_ready(monkeypatch):
    monkeypatch.setattr("cards.director.get_configured_vendor", lambda slot=None: "google")


def test_plan_rule_based_without_llm():
    sb, report = plan_cards(SOURCE, "info_summary", use_llm=False, count=5)
    assert report["engine"] == "rule-based"
    assert [s.slide_type for s in sb.card_slides] == ["cover", "numbered", "numbered", "numbered", "call_to_action"]
    cta = sb.card_slides[-1]
    assert "055-255-1365" in cta.body_content and "onjaram@naver.com" in cta.body_content  # 연락처는 킷 값
    assert sb.card_format == "info_summary" and sb.design_id == "editorial"


def test_plan_llm_forces_structure_blacklist_and_fixed_cta(monkeypatch):
    _llm_ready(monkeypatch)
    gen = _fake_llm([("*지친* 마음", "정신병 아니에요\n마음의 신호예요", "괜찮아요"),
                     ("같은 시간에 눕기", "수면 리듬 만들기", ""), ("화면 멀리하기", "잠들기 전 30분", ""),
                     ("AI가 쓴 마무리", "전화 010-0000-0000", "아무 말")])
    sb, report = plan_cards(SOURCE, "info_summary", use_llm=True, count=5, generate=gen)
    assert report["engine"].startswith("llm") or report["engine"] == "rule-based"
    types = [s.slide_type for s in sb.card_slides]
    assert types[0] == "cover" and types[-1] == "call_to_action" and len(types) == 5
    joined = " ".join(s.body_content for s in sb.card_slides)
    assert "정신병" not in joined and "마음의 어려움" in joined          # 금기어 치환
    assert "010-0000-0000" not in sb.card_slides[-1].body_content          # CTA 연락처는 AI가 못 바꾼다
    assert "055-255-1365" in sb.card_slides[-1].body_content
    assert any(h["forbidden"] == "정신병" for h in report["blacklist_hits"])
    assert sb.hashtags == ["#마음돌봄"]


def test_plan_llm_failure_falls_back_and_flags_invented_numbers(monkeypatch):
    _llm_ready(monkeypatch)
    def boom(**kw):
        raise RuntimeError("API 키 없음")
    sb, report = plan_cards(SOURCE, "info_summary", use_llm=True, generate=lambda *a, **k: boom())
    assert report["engine"] == "rule-based" and any("규칙 기반" in w for w in report["warnings"])
    gen = _fake_llm([("제목", "하루 99%가 낫습니다", "")] * 5)
    sb, report = plan_cards(SOURCE, "info_summary", use_llm=True, count=5, generate=gen)
    assert any("99" in w and "숫자" in w for w in report["warnings"])   # 팩트 락 경고


def test_checklist_cta_carries_disclaimer():
    sb, _ = plan_cards("이런 마음 있으신가요? 이유 없이 피곤해요. 작은 일에도 눈물이 나요.", "checklist", use_llm=False)
    assert "진단이 아" in sb.card_slides[-1].body_content


def test_user_uploaded_photo_is_assigned_first():
    asset = MediaAsset(id="A1", kind="image", path="/nonexistent.jpg")
    sb, _ = plan_cards(SOURCE, "info_summary", use_llm=False, assets=[asset])
    assert sb.card_slides[0].asset_id == "A1"                       # 표지에 사용자 사진
    assert all(s.asset_id is None for s in sb.card_slides[1:])       # 번호형은 인포그래픽(사진 자리 없음)


@pytest.mark.parametrize("type_id", ["info_summary", "empathy", "checklist", "howto", "qna", "big_number", "event_notice", "expert"])
def test_every_type_plans_and_renders(type_id, tmp_path):
    text = "상담은 평균 15회기, 1회 50분 80,000원으로 진행돼요.\n일시: 12월 5일\n대상: 직장인\n1단계: 예약\n2단계: 첫 상담\n마음이 지칠 땐 쉬어가도 괜찮아요."
    sb, report = plan_cards(text, type_id, use_llm=False)
    paths = asyncio.run(CardNewsRendererService(export_dir=str(tmp_path)).render_all_slides(sb))
    assert len(paths) == len(sb.card_slides) and all((tmp_path / f"slide_{i + 1:02d}.png").exists() for i in range(len(paths)))


def test_tri_layout_zones_follow_ratio_and_shorts_safe_margin(tmp_path):
    r = CardNewsRendererService(export_dir=str(tmp_path))
    (t0, t1), (m0, m1), (b0, b1) = r._tri_zones([2, 5, 3])
    assert (t0, b1) == (0, r.HEIGHT) and t1 - t0 == 270 and m1 - m0 == 675 and b1 - b0 == 405
    r.HEIGHT, r.safe_top, r.safe_bottom = 1920, 250, 250     # 쇼츠: 위아래 UI 안전 여백을 비운다
    (t0, _), _, (_, b1) = r._tri_zones([2, 5, 3])
    assert t0 == 250 and b1 == 1920 - 250


def test_design_templates_include_tri_and_ratio_is_editable():
    assert design_templates.get("tri-2-5-3").layout == "tri" and design_templates.get("tri-1-1-1").ratio == [1, 1, 1]


def test_bundled_fonts_have_ofl_license_files_and_serif_is_available():
    import os
    from cards import fonts
    from cards.paths import FONTS_DIR
    assert "gowunbatang" in fonts.font_families()                     # 세리프(명조) 제목 글꼴
    names = os.listdir(FONTS_DIR)
    for family in ("GmarketSans", "Pretendard", "GowunBatang"):       # 동봉 글꼴마다 라이선스 원문 파일이 있어야 한다
        assert any(f.startswith(family) and f.endswith((".otf", ".ttf")) for f in names), family
        assert f"OFL-{family}.txt" in names, family
    assert "SIL OPEN FONT LICENSE" in open(os.path.join(FONTS_DIR, "OFL-GowunBatang.txt"), encoding="utf-8").read().upper()


def test_long_title_stays_inside_top_zone(tmp_path):
    from PIL import Image
    from cards.schema import CardSlide, EditableStoryboard
    long_h = "*아무것도 하지 않았는데도* 몸과 마음이 하루 종일 무겁고 지치는 이유와 오늘 바로 해볼 수 있는 작은 방법들"
    sb = EditableStoryboard(title="t", target_audience="a", tone_and_manner="b", visual_style="c", is_anonymized=True,
                            sns_caption="", brand_id="1", design_id="tri-1-1-1",
                            card_slides=[CardSlide(slide_number=1, slide_type="body", lead_headline=long_h, body_content="내용", takeaway="끝")])
    r = CardNewsRendererService(export_dir=str(tmp_path))
    path = asyncio.run(r.render_all_slides(sb))[0]
    img = Image.open(path).convert("RGB")
    (t0, t1), (m0, _), _ = r._tri_zones([1, 1, 1])
    bg = img.getpixel((2, 2))
    # 제목 영역 맨 아래 8px(가운데 영역 패널 바로 위)에는 글자가 없어야 한다
    band = img.crop((0, m0 - 8, img.width, m0 - 1))
    assert all(band.getpixel((x, y)) == bg for x in range(0, img.width, 7) for y in range(band.height))


def test_default_card_type_is_the_most_general_not_alphabetical():
    ordered = [p["id"] for p in card_types.available()]
    assert ordered[0] == "empathy" and ordered.index("big_number") > ordered.index("info_summary")
    assert card_types.get(None)["id"] == "empathy"


def test_preview_renders_every_type_and_design(tmp_path, monkeypatch):
    """카드 종류·디자인 미리보기: 모든 내장 종류와 디자인이 샘플 PNG로 그려지고 두 번째는 캐시를 쓴다."""
    from cards import card_types, design_templates, preview
    monkeypatch.setattr(preview, "PREVIEW_DIR", str(tmp_path))
    packs, _ = card_types.load_all(include_hidden=True)
    for pack in packs.values():
        items = preview.render_type_preview(pack)
        assert items and all(os.path.exists(p) for _, p in items)
    for d in design_templates.list_all():
        assert len(preview.render_design_preview(d.id)) == 4
    first = preview.render_design_preview("tri-2-5-3")[0][1]
    mtime = os.path.getmtime(first)
    assert preview.render_design_preview("tri-2-5-3")[0][1] == first and os.path.getmtime(first) == mtime


def test_brand_palettes_apply_to_every_design_and_render(tmp_path, monkeypatch):
    """브랜드 배색 5종 × 모든 디자인: '디자인@배색' id가 풀리고 색이 바뀌며 모두 그려진다."""
    from cards import preview
    monkeypatch.setattr(preview, "PREVIEW_DIR", str(tmp_path))
    assert design_templates.split_id("tri-2-5-3@navy") == ("tri-2-5-3", "navy")
    assert design_templates.split_id("tri-2-5-3@nope") == ("tri-2-5-3", "")      # 모르는 배색은 무시
    assert design_templates.with_palette("classic", "") == "classic"
    base = design_templates.get("tri-dark-2-5-3")
    navy = design_templates.get("tri-dark-2-5-3@navy")
    assert navy.layout == base.layout and navy.colors["primary"] == "#2C4A6F" and navy.colors["dark_bg"] == "#1C2F47"
    brand = {"#4A7C59", "#2C4A6F", "#E07A5F", "#F0ECE1", "#FAF8F5", "#2B2D2F", "#35593F", "#26372C", "#1C2F47", "#1F2F40"}
    for p in design_templates.BRAND_PALETTES.values():
        assert set(p["colors"].values()) <= brand                                  # 브랜드 색(과 그 어두운 파생색)만 쓴다
    for d in design_templates.list_all():
        for pal in design_templates.BRAND_PALETTES:
            assert len(preview.render_design_preview(design_templates.with_palette(d.id, pal))) == 4
    # 내장 디자인의 기본 색도 더 이상 브랜드 밖의 색(하늘색·주황)이 아니다
    for did in ("gov", "color_block", "poster"):
        assert set(design_templates.get(did).colors.values()) <= brand | {"#E6ECF4"}


def test_onjaram_layout_renders_all_slide_types_and_cta_extras(tmp_path):
    """온자람 전용 디자인: 모든 카드 종류가 그려지고, 마지막 안내 카드는 QR·할인 배지를 붙이면 모양이 달라진다."""
    import asyncio
    from PIL import Image
    from cards.card_renderer import CardNewsRendererService
    from cards.schema import CardSlide, EditableStoryboard
    kinds = ["cover", "body", "numbered", "steps", "checklist", "qa", "quote", "big_number", "comparison_table", "event_info", "call_to_action", "single"]
    slides = [CardSlide(slide_number=i + 1, slide_type=k, lead_headline="요즘 *마음*이 자꾸 무겁다면", body_content="1. 숨 쉬기\n2. 쉬어 가기\n3. 물 마시기\n4. 걷기",
                        takeaway="천천히, 한 단계씩", stat_value="3가지", stat_label="오늘의 실천",
                        comparison_table={"항목": ["혼자", "함께"], "부담": ["큼", "나눔"]}) for i, k in enumerate(kinds)]
    for design in ("onjaram-warm", "onjaram-trust", "onjaram-warm@navy"):
        sb = EditableStoryboard(title="t", target_audience="", tone_and_manner="", visual_style="", is_anonymized=False,
                                card_slides=slides, sns_caption="", design_id=design)
        out = tmp_path / design.replace("@", "_")
        paths = asyncio.run(CardNewsRendererService(export_dir=str(out)).render_all_slides(sb))
        assert len(paths) == len(kinds)
        assert all(Image.open(p).size == (1080, 1350) for p in paths)
    qr = tmp_path / "qr.png"
    Image.new("RGB", (200, 200), "black").save(qr)
    cta = slides[kinds.index("call_to_action")]
    plain = Image.open(paths[kinds.index("call_to_action")]).convert("RGB")
    sb.card_slides = [cta.model_copy(update={"qr_image": str(qr), "promo_badge": "청년 5회기 할인"})]
    p2 = asyncio.run(CardNewsRendererService(export_dir=str(tmp_path / "qr")).render_all_slides(sb))[0]
    with_extras = Image.open(p2).convert("RGB")
    from PIL import ImageChops
    assert ImageChops.difference(plain, with_extras).getbbox() is not None
    assert with_extras.getpixel((120, 800)) == (0, 0, 0) or with_extras.getbbox() is not None


def test_slide_fingerprint_changes_with_qr_and_badge():
    from flet_app.views.card_studio import slide_fingerprint
    from cards.schema import CardSlide, EditableStoryboard
    sb = EditableStoryboard(title="t", target_audience="", tone_and_manner="", visual_style="", is_anonymized=False, sns_caption="",
                            card_slides=[CardSlide(slide_number=1, slide_type="call_to_action", lead_headline="a", body_content="b", takeaway="c")])
    before = slide_fingerprint(sb, 0)
    sb.card_slides[0].promo_badge = "할인"
    assert slide_fingerprint(sb, 0) != before
