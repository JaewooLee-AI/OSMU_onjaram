"""카드 → 쇼츠 대본(장면 목록) 변환.

원칙(형제 프로젝트의 '확정 카드 → 쇼츠'를 온자람용으로 다시 쓴 것):
- 장면 순서와 사진은 카드를 그대로 따른다(새 AI 이미지를 만들지 않음 — 카드의 사진을 재사용).
- 화면 큰 문구(display_caption) = 카드 제목, 내레이션 = 카드 본문을 듣기 좋은 문장으로 이은 것, 첫 장면은 3초 훅,
  마지막 장면은 상담 안내(연락처·슬로건은 브랜드 킷 값으로 고정 — 말로 읽는 숫자를 AI가 만들지 않게).
- 카드에 없는 숫자는 만들지 않고(경고), 금기어 사전을 대본에 다시 적용한다.
- AI 변환은 선택(기본 글쓰기 모델 슬롯). 꺼 두거나 실패하면 규칙 기반으로 만든다(AI 호출 0원).
카드를 고치면 `is_stale`이 참이 되어 대본을 다시 만들라고 안내한다.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ai_workers.guardrail import apply_blacklist_dictionary
from ai_workers.multi_llm_router import generate_text, get_configured_vendor
from cards import emphasis
from cards.brand import from_db
from cards.schema import CardSlide, EditableStoryboard, ShortsScene
from core import repo
from core.brand_seed import SLOGAN_SUB

CHARS_PER_SEC = 6.5   # 한국어 내레이션 초당 글자 수(공백 포함) 어림값
MIN_SCENE_SEC = 2.5
_NUM_RE = re.compile(r"\d[\d,.]*")


def card_hash(sb: EditableStoryboard) -> str:
    """카드 내용 지문 — 카드가 바뀌었는지 알아보는 데 쓴다."""
    parts = [(c.slide_type, c.lead_headline, c.body_content, c.takeaway, c.stat_value, c.stat_label, c.asset_id) for c in sb.card_slides]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:16]


def is_stale(sb: Optional[EditableStoryboard]) -> bool:
    return bool(sb and sb.shorts_scenes and sb.shorts_source_hash != card_hash(sb))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", emphasis.strip(text).replace("…", "")).strip().rstrip(".")


def _sentence(text: str) -> str:
    t = _clean(text)
    return t if not t or t[-1] in "?!.。" else t + "."


def _items(body: str) -> List[str]:
    out = []
    for line in (body or "").replace("\\n", "\n").splitlines():
        line = re.sub(r"^\s*(?:[-•·*]|\d+[.)])\s*", "", line).strip()
        if line:
            out.append(line)
    return out


def _numbers(text: str) -> set:
    return {n.strip(".,").replace(",", "") for n in _NUM_RE.findall(text or "") if n.strip(".,")}


def _cta_narration(brand) -> str:
    contact = f"전화 {brand.phone}이나 네이버 예약으로" if brand.phone else "네이버 예약으로"
    return f"혼자 해결하기 어려우시다면, {contact} 편하게 문의해 주세요. {SLOGAN_SUB}, {brand.brand_name}입니다."


def _card_narration(card: CardSlide, budget: int) -> str:
    """카드 하나의 내레이션(글자 예산 안에서 항목을 차례로 이어 붙인다)."""
    head = _sentence(card.lead_headline)
    pieces: List[str] = []
    if card.slide_type == "big_number" and card.stat_value:
        pieces.append(_sentence(f"{card.stat_label} {card.stat_value}".strip()))
    elif card.slide_type in ("steps", "numbered", "checklist"):
        for i, item in enumerate(_items(card.body_content)):
            pieces.append(_sentence(("첫째, " if i == 0 else "둘째, " if i == 1 else "셋째, " if i == 2 else "") + _clean(item)))
    else:
        pieces += [_sentence(x) for x in _items(card.body_content)]
    text = head
    head_key = _clean(card.lead_headline)
    for piece in pieces:
        if _clean(re.sub(r"^(첫째|둘째|셋째), ", "", piece)) == head_key:   # 제목과 같은 항목은 두 번 읽지 않는다
            continue
        if len(text) + 1 + len(piece) > budget and text != head:
            break
        text = f"{text} {piece}".strip()
    return text


def _rule_based(sb: EditableStoryboard, seconds: int, brand) -> List[Dict[str, Any]]:
    cards = sb.card_slides
    body = [c for c in cards if c.slide_type != "call_to_action"]
    has_cta = any(c.slide_type == "call_to_action" for c in cards)
    cta_chars = len(_cta_narration(brand))
    budget_total = max(60, int(seconds * CHARS_PER_SEC) - (cta_chars if has_cta else 0))
    per_card = max(30, budget_total // max(1, len(body)))
    scenes: List[Dict[str, Any]] = []
    for i, card in enumerate(cards):
        number = card.slide_number or i + 1
        if card.slide_type == "call_to_action":
            scenes.append({"source_cards": [number], "section_type": "conclusion", "narration_script": _cta_narration(brand),
                           "display_caption": _clean(card.lead_headline)[:30], "emphasis_words": []})
            continue
        _, terms = emphasis.parse(card.lead_headline)
        scenes.append({"source_cards": [number], "section_type": "hook" if not scenes else "body",
                       "narration_script": _card_narration(card, per_card),
                       "display_caption": _clean(card.lead_headline)[:30], "emphasis_words": terms[:2]})
    if scenes and not has_cta:
        scenes[-1]["section_type"] = "conclusion"
    return scenes


def _prompt(sb: EditableStoryboard, seconds: int, kit: dict) -> str:
    cards = [{"번호": c.slide_number, "종류": c.slide_type, "제목": emphasis.strip(c.lead_headline), "내용": _items(c.body_content),
              "마지막한줄": c.takeaway, "큰숫자": c.stat_value, "숫자설명": c.stat_label}
             for c in sb.card_slides if c.slide_type != "call_to_action"]
    return (
        f"[말투]\n{kit.get('tone_and_manner') or ''}\n\n"
        f"아래 카드뉴스를 약 {seconds}초 쇼츠 내레이션으로 바꿉니다. 카드마다 한 장면입니다(순서 유지). 첫 장면은 3초 안의 훅입니다.\n"
        "내레이션은 귀로 듣기 좋게 카드 문장을 풀어 쓰되, **카드에 없는 숫자·사실·가격을 만들지 말고**, 치료·완치·효과 보장 표현과 "
        "낙인 표현을 쓰지 마세요. 차분하고 따뜻한 말투로, 한 장면은 2~3문장 이내입니다. 마지막 상담 안내는 시스템이 붙입니다.\n\n"
        f"[카드]\n{json.dumps(cards, ensure_ascii=False)}\n\n"
        '반드시 JSON만 출력: {"scenes": [{"source_cards": [1], "narration_script": "...", "display_caption": "30자 이내", '
        '"emphasis_words": ["문구 속 단어"]}]}'
    )


def _from_llm(raw: str, sb: EditableStoryboard) -> List[Dict[str, Any]]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    data = json.loads(text[text.find("{"):text.rfind("}") + 1])
    scenes = [s for s in data.get("scenes") or [] if isinstance(s, dict) and str(s.get("narration_script") or "").strip()]
    if not scenes:
        raise ValueError("장면이 없습니다.")
    return scenes


def convert(sb: EditableStoryboard, kit_id: Optional[int] = None, seconds: int = 45, use_llm: bool = False,
            generate=generate_text) -> Tuple[List[ShortsScene], Dict[str, Any]]:
    """카드 → (쇼츠 장면, 보고서). 보고서: engine, warnings, blacklist_hits."""
    if not sb.card_slides:
        raise ValueError("카드가 없습니다. 먼저 카드뉴스를 기획하세요.")
    kit = repo.get_brand_kit(kit_id)
    brand = from_db(kit_id)
    blacklist = kit.get("blacklist_map") or {}
    report: Dict[str, Any] = {"engine": "rule-based", "warnings": [], "blacklist_hits": []}
    drafts = None
    if use_llm:
        try:
            raw = generate(vendor=get_configured_vendor("text"), prompt=_prompt(sb, seconds, kit),
                           system="당신은 심리상담 기관의 쇼츠 대본 작가입니다. 카드에 없는 사실을 만들지 않습니다.",
                           max_tokens=3000, note="shorts-script")
            drafts = _from_llm(raw, sb)
            report["engine"] = "llm"
        except Exception as exc:  # noqa: BLE001 — 실패하면 규칙 기반으로 계속
            report["warnings"].append(f"AI 변환을 쓰지 못해 규칙 기반으로 만들었습니다: {exc}")
    rule = _rule_based(sb, seconds, brand)
    if drafts is not None:
        # AI는 카드 장면 부분만 쓰고, 마지막 상담 안내는 규칙 기반(고정) 장면을 그대로 쓴다.
        cta = [s for s in rule if s["section_type"] == "conclusion" and any(
            sb.card_slides[min(n, len(sb.card_slides)) - 1].slide_type == "call_to_action" for n in s["source_cards"])]
        drafts = [d for d in drafts][:max(1, len([c for c in sb.card_slides if c.slide_type != "call_to_action"]))]
        for i, d in enumerate(drafts):
            d.setdefault("source_cards", [i + 1])
            d["section_type"] = "hook" if i == 0 else "body"
        drafts += cta
        if not cta and drafts:
            drafts[-1]["section_type"] = "conclusion"
    scenes_raw = drafts if drafts is not None else rule

    allowed = _numbers(" ".join(f"{c.lead_headline} {c.body_content} {c.takeaway} {c.stat_value}" for c in sb.card_slides)) \
        | _numbers(f"{brand.phone} {brand.email}")
    scenes: List[ShortsScene] = []
    for i, d in enumerate(scenes_raw):
        narration, hits1 = apply_blacklist_dictionary(str(d.get("narration_script") or "").strip(), blacklist)
        caption, hits2 = apply_blacklist_dictionary(_clean(str(d.get("display_caption") or ""))[:30], blacklist)
        report["blacklist_hits"] += hits1 + hits2
        extra = sorted(_numbers(narration) - allowed)
        if extra:
            report["warnings"].append(f"{i + 1}번 장면에 카드에 없는 숫자가 있습니다: {', '.join(extra)} — 확인하세요.")
        sources = [int(n) for n in (d.get("source_cards") or []) if str(n).isdigit()] or [i + 1]
        first = sb.card_slides[min(sources[0], len(sb.card_slides)) - 1]
        words = [w for w in (d.get("emphasis_words") or []) if w and w in caption][:2]
        scenes.append(ShortsScene(
            scene_number=i + 1, section_type=d.get("section_type") or "body", narration_script=narration, display_caption=caption,
            duration_seconds=max(MIN_SCENE_SEC, round(len(narration) / CHARS_PER_SEC, 1)),
            asset_id=first.asset_id if first.slide_type not in ("call_to_action",) else None, emphasis_words=words, source_cards=sources,
        ))
    if report["blacklist_hits"]:
        terms = ", ".join(sorted({h["forbidden"] for h in report["blacklist_hits"]}))
        report["warnings"].append(f"금기어({terms})를 사전의 대체 표현으로 자동으로 바꿨습니다 — 문장이 어색하지 않은지 확인하세요.")
    return scenes, report


def apply_to_storyboard(sb: EditableStoryboard, scenes: List[ShortsScene]) -> None:
    sb.shorts_scenes = scenes
    sb.shorts_source_hash = card_hash(sb)
