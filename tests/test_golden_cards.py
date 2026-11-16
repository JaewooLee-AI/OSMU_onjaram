"""디자인 기준 그림 비교 — 카드·쇼츠 화면이 의도치 않게 달라지면 알려 줍니다.

디자인마다 견본 카드 11종(쇼츠는 5장면)을 그려 작은 모음 그림 한 장으로 만들고, `tests/golden/`의 기준 그림과 비교합니다.
글꼴 렌더링은 OS·라이브러리 버전에 따라 조금씩 달라서 '거의 같음'(칸마다 평균 차이·크게 다른 점의 비율)으로 봅니다.

디자인을 일부러 바꿨다면 기준 그림을 다시 만듭니다:

    OSMU_UPDATE_GOLDEN=1 python -m pytest tests/test_golden_cards.py

다시 만든 뒤에는 `tests/golden/*.png`를 눈으로 확인하세요(그것이 새 기준이 됩니다).
"""
import asyncio
import os
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from cards import lint, preview, shorts_ed
from cards.card_renderer import CardNewsRendererService
from cards.schema import MediaAsset
from core.brand_seed import seed_if_empty

GOLDEN = Path(__file__).parent / "golden"
UPDATE = bool(os.environ.get("OSMU_UPDATE_GOLDEN"))
CARD_TYPES = ["cover", "body", "steps", "checklist", "qa", "quote", "big_number", "comparison_table", "event_info",
              "call_to_action", "single"]
SHORTS_TYPES = ["cover", "body", "steps", "big_number", "call_to_action"]
DESIGNS = ["editorial", "editorial-dark", "editorial-photo", "report", "report-navy"]
CELL_W = 216
MEAN_LIMIT = 5.0        # 칸 하나의 평균 밝기 차이(0~255)
BIG_DIFF_LIMIT = 0.03   # 칸 하나에서 크게(64 이상) 다른 점의 비율


@pytest.fixture(autouse=True)
def seeded():
    seed_if_empty()


def _photo(tmp_path) -> MediaAsset:
    path = str(tmp_path / "placeholder.png")
    preview._placeholder_photo(path)
    return MediaAsset(id="A1", kind="image", source="user", path=path)


def _sheet(paths, cell_h):
    sheet = Image.new("RGB", (CELL_W * len(paths), cell_h), "#808080")
    for i, p in enumerate(paths):
        sheet.paste(Image.open(p).convert("RGB").resize((CELL_W, cell_h), Image.LANCZOS), (i * CELL_W, 0))
    return sheet


def _compare(name: str, sheet: Image.Image, labels, tmp_path):
    target = GOLDEN / f"{name}.png"
    if UPDATE:
        GOLDEN.mkdir(exist_ok=True)
        sheet.save(target, optimize=True)
        return
    assert target.exists(), f"기준 그림이 없습니다: {target} — OSMU_UPDATE_GOLDEN=1 로 만드세요"
    gold = Image.open(target).convert("RGB")
    assert gold.size == sheet.size, f"{name}: 크기가 다릅니다 {gold.size} != {sheet.size}"
    bad = []
    for i, label in enumerate(labels):
        box = (i * CELL_W, 0, (i + 1) * CELL_W, sheet.height)
        diff = ImageChops.difference(gold.crop(box), sheet.crop(box)).convert("L")
        mean = ImageStat.Stat(diff).mean[0]
        big = sum(diff.histogram()[64:]) / (diff.width * diff.height)
        if mean > MEAN_LIMIT or big > BIG_DIFF_LIMIT:
            bad.append(f"{i + 1}번({label}) 평균 {mean:.1f}, 큰 차이 {big:.1%}")
    if bad:
        actual = tmp_path / f"{name}_actual.png"
        sheet.save(actual)
        pytest.fail(f"{name}: 기준 그림과 다릅니다 — {'; '.join(bad)}. 지금 그림: {actual} "
                    f"(일부러 바꾼 것이면 OSMU_UPDATE_GOLDEN=1 로 기준을 다시 만드세요)")


@pytest.mark.parametrize("design", DESIGNS)
def test_cards_match_golden_and_nothing_is_clipped(tmp_path, design):
    sb = preview._storyboard([(a, "") for a in CARD_TYPES], design, _photo(tmp_path))
    r = CardNewsRendererService(export_dir=str(tmp_path / "out"))
    paths = asyncio.run(r.render_all_slides(sb))
    clipped = {i: v for i, v in r.clips.items() if v}
    assert not clipped, f"견본 문구가 잘렸습니다: {lint.message(clipped)}"
    _compare(f"cards_{design}", _sheet(paths, 270), CARD_TYPES, tmp_path)


@pytest.mark.parametrize("design", ["editorial", "report"])
def test_shorts_frames_match_golden(tmp_path, design):
    from cards.shorts_renderer import ShortsRendererService
    sb = preview._storyboard([(a, "") for a in SHORTS_TYPES], design, _photo(tmp_path))
    r = CardNewsRendererService(export_dir=str(tmp_path / "out"))
    r.HEIGHT, r.safe_top = 1920, ShortsRendererService.ED_SAFE_TOP
    r.safe_bottom = ShortsRendererService.ED_SAFE_BOTTOM + shorts_ed.CAPTION_H
    r.FOLLOW_ASPECT, r.ED_SHORTS = False, True
    paths = []
    for i in range(len(SHORTS_TYPES)):
        p = asyncio.run(r.render_slide(sb, i))
        frame = Image.open(p).convert("RGBA")
        cap = shorts_ed.caption_png("지금 읽는 문장이 이 자리에 크게 나옵니다.", str(tmp_path / "cap.png"), 1080, r.ed_regions)
        frame.alpha_composite(Image.open(cap), (0, 1920 - ShortsRendererService.ED_SAFE_BOTTOM - shorts_ed.CAPTION_H))
        out = tmp_path / f"shorts_{i}.png"
        frame.convert("RGB").save(out)
        paths.append(out)
    _compare(f"shorts_{design}", _sheet(paths, 384), SHORTS_TYPES, tmp_path)


def test_lint_reports_clipped_text(tmp_path):
    sb = preview._storyboard([("steps", ""), ("body", "")], "editorial", _photo(tmp_path))
    sb.card_slides[0].body_content = "\n".join(["아주 긴 항목입니다 " * 9] * 5)
    clips = lint.check_storyboard(sb)
    assert 0 in clips and 1 not in clips
    msg = lint.message(clips)
    assert msg.startswith("✂️") and "1번" in msg
    assert lint.message({}) == "" and lint.message({2: []}) == ""
