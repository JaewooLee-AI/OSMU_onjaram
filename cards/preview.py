"""카드 종류·디자인 미리보기 — 설정 화면에서 '이 종류/디자인을 고르면 이렇게 나온다'를 그림으로 보여 줍니다.

- 샘플 문구와 회색조 자리표시 사진(가짜 사진)으로 실제 렌더러가 그린 카드 PNG를 만듭니다(AI·네트워크 호출 0원).
- 브랜드 킷(연락처·이름)은 기본 킷 값, 색·비율·레이아웃은 선택한 디자인을 따릅니다.
- 결과는 데이터 폴더 `previews/<지문>/`에 캐시합니다. 카드 종류·디자인·킷 값이 바뀌면 지문이 달라져 새로 그립니다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from cards import card_types, design_templates
from cards.card_renderer import CardNewsRendererService
from cards.images import PHOTO_TYPES
from cards.paths import DATA_DIR
from cards.schema import CardSlide, EditableStoryboard, MediaAsset
from core import repo

PREVIEW_DIR = os.path.join(DATA_DIR, "previews")
_VERSION = "v1"   # 샘플 문구나 그리는 방식을 바꾸면 올려서 캐시를 버린다

# 원형별 샘플(제목·본문·마무리 한 줄). 실제 내담자·사실이 아닌 일반적인 예시 문구입니다.
_SAMPLES: Dict[str, Dict[str, str]] = {
    "cover": {"h": "요즘 마음이 자꾸 무겁다면", "b": "", "t": "나를 돌보는 작은 시작"},
    "body": {"h": "지친 마음에도 이유가 있어요", "b": "해야 할 일이 쌓이면 누구나 마음이 지칩니다.", "t": "당신 잘못이 아니에요"},
    "numbered": {"h": "오늘 해볼 세 가지", "b": "1. 같은 시간에 눕기\n2. 화면 멀리하기\n3. 따뜻한 차 마시기", "t": "하나만 해도 충분해요"},
    "steps": {"h": "마음을 가라앉히는 3단계", "b": "1. 숨을 천천히 들이쉬기\n2. 지금 느낌 이름 붙이기\n3. 어깨 힘 빼기", "t": "천천히, 한 단계씩"},
    "checklist": {"h": "마음 점검 체크리스트", "b": "- 잠이 얕아졌어요\n- 작은 일에 예민해져요\n- 쉬어도 개운하지 않아요", "t": "해당이 많다면 쉬어 가요"},
    "qa": {"h": "상담은 꼭 힘들어야 받나요?", "b": "아니요. 마음을 미리 돌보는 것도 좋은 이유가 됩니다.", "t": "편하게 문의하세요"},
    "quote": {"h": "쉬어가도 괜찮아요", "b": "잠시 멈추는 것도 앞으로 가는 방법이에요.", "t": "온자람"},
    "big_number": {"h": "숫자로 보는 마음 건강", "b": "", "t": "예시 숫자입니다", "v": "3가지", "l": "오늘의 작은 실천"},
    "comparison_table": {"h": "혼자 vs 함께", "b": "", "t": "함께하면 부담이 줄어요"},
    "event_info": {"h": "마음 돌봄 프로그램 안내", "b": "일시: 예시 일정\n장소: 예시 장소\n대상: 누구나", "t": "자세한 내용은 문의 주세요"},
    "call_to_action": {"h": "혼자 해결하기 어려우시다면", "b": "편하게 문의해 주세요.", "t": "상담 문의"},
    "single": {"h": "마음에도 쉼표가 필요해요", "b": "오늘 하루, 나에게 다정한 말 한 마디를 건네 보세요.", "t": "나를 아끼는 연습"},
}
_ARCHETYPE_NAMES = {
    "cover": "표지", "body": "본문", "numbered": "번호 목록", "steps": "단계", "checklist": "체크리스트", "qa": "질문·답",
    "quote": "한 줄 문구", "big_number": "큰 숫자", "comparison_table": "비교표", "event_info": "행사 안내",
    "call_to_action": "상담 안내", "single": "한 장 요약",
}


def archetype_name(archetype: str) -> str:
    return _ARCHETYPE_NAMES.get(archetype, archetype)


def _slide(number: int, archetype: str, hint: str, photo_id: Optional[str]) -> CardSlide:
    s = _SAMPLES.get(archetype) or _SAMPLES["body"]
    return CardSlide(
        slide_number=number, slide_type=archetype, lead_headline=s["h"], body_content=s["b"], takeaway=s["t"],
        stat_value=s.get("v", ""), stat_label=s.get("l", ""), badge=f"{number:02d}",
        comparison_table={"항목": ["혼자", "함께"], "부담": ["큼", "나눠짐"], "시간": ["오래", "줄어듦"]} if archetype == "comparison_table" else None,
        asset_id=photo_id,
    )


def _placeholder_photo(path: str) -> None:
    """회색조 가짜 사진(하늘·언덕 모양) — 사진 칸이 어디인지만 보이게 한다."""
    w, h = 1080, 900
    img = Image.new("RGB", (w, h), "#D9DDD8")
    d = ImageDraw.Draw(img)
    for y in range(h):
        v = 222 - int(34 * y / h)
        d.line([(0, y), (w, y)], fill=(v, v + 2, v))
    d.ellipse([w * 0.62, h * 0.12, w * 0.62 + 150, h * 0.12 + 150], fill="#F1F2EF")
    d.polygon([(0, h), (0, h * 0.72), (w * 0.3, h * 0.55), (w * 0.55, h * 0.74), (w * 0.8, h * 0.5), (w, h * 0.68), (w, h)], fill="#B3BAB1")
    d.polygon([(0, h), (0, h * 0.86), (w * 0.4, h * 0.74), (w * 0.75, h * 0.88), (w, h * 0.8), (w, h)], fill="#9AA399")
    d.text((w // 2, h // 2), "사진", fill="#7F887E", anchor="mm")
    img.save(path, "PNG")


def _storyboard(slides: List[Tuple[str, str]], design_id: str, photo: MediaAsset, aspect: str = "4:5") -> EditableStoryboard:
    design = design_templates.get(design_id)
    cards: List[CardSlide] = []
    for i, (arche, hint) in enumerate(slides, 1):
        use_photo = arche in PHOTO_TYPES and design.uses_photo(arche)
        cards.append(_slide(i, arche, hint, photo.id if use_photo else None))
    kit = repo.get_brand_kit(None)
    return EditableStoryboard(
        title="미리보기", target_audience="", tone_and_manner="", visual_style="", is_anonymized=False, card_slides=cards,
        sns_caption="", design_id=design.id, aspect=aspect, brand_id=str(kit.get("id") or ""), assets=[photo],
    )


def _fingerprint(slides: List[Tuple[str, str]], design_id: str, aspect: str = "4:5") -> str:
    design = design_templates.get(design_id)
    kit = repo.get_brand_kit(None)
    payload = {"v": _VERSION, "slides": slides, "design": design.model_dump(), "aspect": aspect,
               "kit": [kit.get("id"), kit.get("brand_name"), kit.get("phone"), kit.get("sub_brand")]}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _render(slides: List[Tuple[str, str]], design_id: str, aspect: str = "4:5") -> List[Tuple[str, str]]:
    """[(원형, PNG 경로)] — 캐시가 있으면 그대로 돌려줍니다."""
    out = os.path.join(PREVIEW_DIR, _fingerprint(slides, design_id, aspect))
    expected = [os.path.join(out, f"slide_{i + 1:02d}.png") for i in range(len(slides))]
    if not all(os.path.exists(p) for p in expected):
        os.makedirs(out, exist_ok=True)
        photo_path = os.path.join(PREVIEW_DIR, "placeholder.png")
        if not os.path.exists(photo_path):
            os.makedirs(PREVIEW_DIR, exist_ok=True)
            _placeholder_photo(photo_path)
        photo = MediaAsset(id="A1", kind="image", source="user", path=photo_path, original_name="placeholder.png")
        sb = _storyboard(slides, design_id, photo, aspect)
        asyncio.run(CardNewsRendererService(export_dir=out).render_all_slides(sb))
    return [(arche, p) for (arche, _), p in zip(slides, expected)]


def render_type_preview(pack: dict, design_id: Optional[str] = None, aspect: str = "4:5") -> List[Tuple[str, str]]:
    """카드 종류의 장 구성을 기본 장수로 펼쳐 그린 [(원형 이름, PNG 경로)]."""
    slots = card_types.expand_sequence(pack, (pack.get("count") or {}).get("default"))
    slides = [(s["archetype"], s.get("hint", "")) for s in slots]
    return _render(slides, design_id or pack.get("layout_default") or "tri-2-5-3", aspect)


def render_design_preview(design_id: str) -> List[Tuple[str, str]]:
    """디자인이 표지·본문·단계·상담 안내를 어떻게 그리는지 보여 주는 4장."""
    return _render([("cover", ""), ("body", ""), ("steps", ""), ("call_to_action", "")], design_id)
