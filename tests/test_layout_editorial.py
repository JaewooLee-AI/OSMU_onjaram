"""에디토리얼 디자인: 모든 카드 종류가 오류 없이 그려지고 크기·사진 규칙이 맞는지."""
import asyncio

from PIL import Image

from cards import design_templates
from cards.card_renderer import CardNewsRendererService
from cards.schema import CardSlide, EditableStoryboard

TYPES = [
    ("cover", "요즘 *마음이 답답*한가요?", "바쁜 일상 속 지친 마음의 신호", "내 마음에 귀 기울이는 시간"),
    ("body", "누구에게나 찾아옵니다", "일정을 챙기다 보면\n숨이 가빠집니다", "당신만 겪는 일이 아닙니다"),
    ("checklist", "이런 날이 있나요?", "몸이 무겁다\n짜증이 난다\n잠이 늦다\n귀찮다", "쉬어 가도 괜찮아요"),
    ("steps", "오늘의 실천 3가지", "숨 내쉬기\n어깨 힘 빼기\n다정한 한마디", "작은 실천"),
    ("big_number", "숫자로 보기", "", "요약"),
    ("event_info", "프로그램 안내", "일시: 12월 3일\n장소: 상담센터", ""),
    ("call_to_action", "함께 걸어요", "네이버 예약 또는 전화로 문의하세요\n전화 055-000-0000\n이메일 a@b.c", "마음이 쉬어가는 곳"),
]


def test_all_slide_types_render(tmp_path):
    slides = [CardSlide(slide_number=i + 1, slide_type=t, lead_headline=h, body_content=b, takeaway=k,
                        stat_value="3분" if t == "big_number" else "", stat_label="하루 숨 고르기" if t == "big_number" else "")
              for i, (t, h, b, k) in enumerate(TYPES)]
    sb = EditableStoryboard(title="t", target_audience="a", tone_and_manner="b", visual_style="c", is_anonymized=False,
                            sns_caption="", card_slides=slides, design_id="editorial", aspect="3:4")
    r = CardNewsRendererService(export_dir=str(tmp_path))
    paths = asyncio.run(r.render_all_slides(sb))
    assert len(paths) == len(TYPES)
    for p in paths:
        assert Image.open(p).size == (1080, 1440)   # 에디토리얼은 카드 비율을 따른다


def test_editorial_photo_rules():
    d = design_templates.get("editorial")
    assert d.layout == "ed"
    assert d.uses_photo("body") and d.uses_photo("cover")
    assert not d.uses_photo("checklist") and not d.uses_photo("call_to_action")


def test_variants_and_shorts_frame_render(tmp_path):
    slides = [CardSlide(slide_number=i + 1, slide_type=t, lead_headline=h, body_content=b, takeaway=k)
              for i, (t, h, b, k) in enumerate(TYPES[:4])]
    for design in ("editorial-dark", "editorial-serif", "editorial-photo", "editorial@navy", "editorial-dark@coral"):
        sb = EditableStoryboard(title="t", target_audience="a", tone_and_manner="b", visual_style="c", is_anonymized=False,
                                sns_caption="", card_slides=slides, design_id=design)
        r = CardNewsRendererService(export_dir=str(tmp_path / design.replace("@", "_")))
        assert len(asyncio.run(r.render_all_slides(sb))) == 4
    # 쇼츠 프레임: 9:16 높이에 위·아래 가림 영역을 두고 그린다
    r = CardNewsRendererService(export_dir=str(tmp_path / "short"))
    r.HEIGHT, r.safe_top, r.safe_bottom, r.FOLLOW_ASPECT, r.ED_SHORTS = 1920, 120, 240, False, True
    sb = EditableStoryboard(title="t", target_audience="a", tone_and_manner="b", visual_style="c", is_anonymized=False,
                            sns_caption="", card_slides=slides, design_id="editorial")
    path = asyncio.run(r.render_slide(sb, 1))
    im = Image.open(path).convert("RGB")
    assert im.size == (1080, 1920)
    bg = im.getpixel((5, 5))
    assert all(im.getpixel((x, y)) == bg for x in (100, 540, 980) for y in (20, 1900))   # 가림 영역은 비어 있음


def test_legacy_designs_listed_after_editorial():
    ids = [t.id for t in design_templates.list_all()]
    assert ids[0] == "editorial" and ids.index("editorial-photo") < ids.index("tri-2-5-3")
    assert design_templates.get("tri-2-5-3").name.startswith(design_templates.LEGACY_PREFIX)
