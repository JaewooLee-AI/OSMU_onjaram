"""신뢰 리포트 디자인(layout rp): 모든 카드 종류·비율·변형이 그려지고, 쇼츠 전용 화면이 쓰는 칸 위치를 남기는지."""
import asyncio

import pytest
from PIL import Image

from cards import design_templates
from cards.card_renderer import CardNewsRendererService
from cards.schema import CardSlide, EditableStoryboard, MediaAsset
from test_layout_editorial import TYPES


def _sb(design, aspect="4:5", photo=None):
    slides = [CardSlide(slide_number=i + 1, slide_type=t, lead_headline=h, body_content=b, takeaway=k,
                        stat_value="3분" if t == "big_number" else "", stat_label="하루 숨 고르기" if t == "big_number" else "",
                        asset_id="A1" if (photo and t in ("cover", "body")) else None)
              for i, (t, h, b, k) in enumerate(TYPES)]
    assets = [MediaAsset(id="A1", kind="image", source="ai", path=str(photo))] if photo else []
    return EditableStoryboard(title="t", target_audience="a", tone_and_manner="b", visual_style="c", is_anonymized=False,
                              sns_caption="", card_slides=slides, design_id=design, aspect=aspect, assets=assets)


@pytest.mark.parametrize("design,aspect", [("report", "4:5"), ("report-navy", "4:5"), ("report", "9:16"), ("report@sage", "3:4")])
def test_all_slide_types_render(tmp_path, design, aspect):
    photo = tmp_path / "p.png"
    Image.new("RGB", (800, 600), "#88AA99").save(photo)
    r = CardNewsRendererService(export_dir=str(tmp_path / "o"))
    paths = asyncio.run(r.render_all_slides(_sb(design, aspect, photo)))
    assert len(paths) == len(TYPES)
    h = {"4:5": 1350, "9:16": 1920, "3:4": 1440}[aspect]
    for p in paths:
        assert Image.open(p).size == (1080, h)


def test_report_records_regions_and_band(tmp_path):
    photo = tmp_path / "p.png"
    Image.new("RGB", (800, 600), "#88AA99").save(photo)
    sb = _sb("report", photo=photo)
    r = CardNewsRendererService(export_dir=str(tmp_path / "o"))
    first = asyncio.run(r.render_slide(sb, 0))
    assert r.ed_regions["photo"]["radius"] == 10 and r.ed_regions["pad"] == r.RP_PAD
    # 위 네이비 띠(브랜드 주조색)
    assert Image.open(first).convert("RGB").getpixel((540, 20)) == (0x2C, 0x4A, 0x6F)
    steps = next(i for i, (t, *_rest) in enumerate(TYPES) if t == "steps")
    asyncio.run(r.render_slide(sb, steps))
    rows = r.ed_regions["rows"]
    assert len(rows) == 3 and all(b[1] >= a[3] for a, b in zip(rows, rows[1:]))
    cta = next(i for i, (t, *_rest) in enumerate(TYPES) if t == "call_to_action")
    asyncio.run(r.render_slide(sb, cta))
    assert len(r.ed_regions["rows"]) == 3          # 안내 문장 + 전화 + 이메일


def test_report_is_current_design_with_native_shorts():
    ids = [t.id for t in design_templates.choices(include_legacy=False)]
    assert "report" in ids and "report-navy" in ids
    assert not design_templates.is_legacy(design_templates.get("report"))
    assert design_templates.native_shorts("rp") and design_templates.native_shorts("ed")
    assert not design_templates.native_shorts("tri")
    assert design_templates.get("report").uses_photo("cover") and not design_templates.get("report").uses_photo("steps")
