"""카드뉴스 기획 — 원고(메모·블로그 본문)와 카드 종류 팩에서 스토리보드(카드 N장)를 만듭니다.

- AI 기획(기본 글쓰기 모델 슬롯 `text`, repo.resolve_slot_model) → 실패하거나 키가 없으면 규칙 기반으로 대체합니다.
- 모든 문구에 금기어 사전을 결정론적으로 적용하고, 원문·브랜드 팩트에 없는 숫자와 근거가 약한 줄을 경고로 알립니다
  (팩트 락: 수치·가격·연락처를 새로 만들지 않음).
- 마지막 안내(call_to_action) 카드의 연락처·슬로건은 AI가 쓰지 않고 브랜드 킷 값으로 고정합니다.
- 사용자가 올린 사진이 있으면 그 사진을 먼저 배치합니다(AI 이미지 비용 0). M3에서 배치 UI를 붙입니다.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ai_workers.guardrail import apply_blacklist_dictionary
from ai_workers.multi_llm_router import generate_text, get_configured_vendor
from cards import card_types, design_templates, images, source_check
from cards.brand import BrandKit, from_db
from cards.schema import BrandElements, CardSlide, EditableStoryboard, MediaAsset
from core import repo
from core.brand_seed import SLOGAN_MAIN, SLOGAN_SUB

_NUM_RE = re.compile(r"\d[\d,.]*")
_TEXT_FIELDS = ("lead_headline", "body_content", "takeaway", "stat_label", "badge")


def _nl(text: Any) -> str:
    return str(text or "").replace("\\n", "\n").strip()


def _numbers(text: str) -> set:
    return {n.strip(".,").replace(",", "") for n in _NUM_RE.findall(text or "") if n.strip(".,")}


# --- 프롬프트 ---------------------------------------------------------------

def _build_prompt(source: str, pack: dict, sequence: List[dict], kit: dict, brand: BrandKit, blacklist: dict) -> Tuple[str, str]:
    plan = "\n".join(
        f"  {i}. {slot['archetype']}" + (f" — {slot['hint']}" if slot.get("hint") else "")
        for i, slot in enumerate(sequence, 1)
    )
    terms = "; ".join(f"{k}: {v}" for k, v in list((kit.get("terminology") or {}).items())[:12])
    facts = "\n".join(f"- {f}" for f in (kit.get("core_facts") or [])[:14])
    banned = ", ".join(list(blacklist)[:30])
    system = (
        f"당신은 '{brand.brand_name}'의 카드뉴스 기획자입니다. 인스타그램 카드뉴스 {len(sequence)}장을 기획합니다. "
        "원문과 [브랜드 팩트]에 없는 수치·가격·날짜·기관명·연락처를 절대 만들지 마세요. "
        "치료·완치·효과 보장 표현과 낙인·공포 표현을 쓰지 마세요. 개별 내담자의 나이·시기·상황이 드러나는 사례는 쓰지 말고 보편적인 내용으로 쓰세요."
    )
    prompt = (
        f"[페르소나]\n{kit.get('persona') or ''}\n\n[말투]\n{kit.get('tone_and_manner') or ''}\n\n"
        f"[브랜드 팩트 — 이 범위 안에서만 사실로 씁니다]\n{facts}\n\n[용어]\n{terms}\n\n[쓰지 않을 표현]\n{banned}\n\n"
        f"[카드 종류] {pack['name']} — {pack.get('desc', '')}\n구성 지침: {pack['llm_structure']}\n\n"
        f"[장 구성 — 정확히 {len(sequence)}장, 이 순서]\n{plan}\n\n"
        f"[원고]\n{source.strip()[:6000]}\n\n"
        "카드 글자 규칙: lead_headline은 한 문장 28자 안팎(수식어 줄이고 핵심만), body_content는 줄바꿈으로 나눈 2~4줄(한 줄 22자 안팎), "
        "takeaway는 20자 안팎의 한 줄. 제목에서 강조할 말은 *별표*로 감쌉니다. "
        "steps·checklist·numbered 카드의 body_content는 한 줄에 항목 하나. big_number 카드는 stat_value에 원문 수치를 단위와 함께 그대로, stat_label에 한 줄 설명.\n"
        "call_to_action 카드는 lead_headline만 정성껏 쓰면 됩니다(연락처는 시스템이 채웁니다).\n"
        "cover·body 카드의 image_prompt에는 그 카드에 어울리는 그림 장면을 영어 한 문장으로 쓰되(자연·빛·손·사물처럼 차분한 장면), "
        "사람의 얼굴·글자·로고는 넣지 마세요. 다른 카드는 비워 두세요.\n\n"
        "반드시 아래 JSON만 출력하세요:\n"
        '{"title": "콘텐츠 제목", "slides": [{"slide_type": "cover", "lead_headline": "...", "body_content": "...", '
        '"takeaway": "...", "stat_value": "", "stat_label": "", "badge": "", "image_prompt": ""}], '
        '"sns_caption": "인스타그램 본문 2~3문장", "hashtags": ["#태그"]}'
    )
    return system, prompt


def _extract_json(raw: str) -> dict:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON을 찾지 못했습니다.")
    return json.loads(text[start:end + 1])


# --- 규칙 기반 대체 -----------------------------------------------------------

def _split_source(source: str) -> List[str]:
    parts = []
    for line in (source or "").replace("\\n", "\n").splitlines():
        line = re.sub(r"^\s*(?:[-•·*]|\d+[.)]|[QA]\d*[.)]?)\s*", "", line.strip())
        line = card_types.PLACEHOLDER_RE.sub("", line).strip()
        if not line:
            continue
        parts += [p.strip() for p in re.split(r"(?<=[.!?])\s+", line) if p.strip()]
    return parts


def _rule_based(source: str, sequence: List[dict]) -> Dict[str, Any]:
    """AI 없이 원고 문장을 장 구성에 나눠 담는다(문장을 새로 쓰지 않고 그대로 배분)."""
    sentences = _split_source(source) or ["(원고를 입력하세요)"]
    slides, cursor = [], 1  # 첫 문장은 표지 제목
    title = sentences[0]
    for slot in sequence:
        kind = slot["archetype"]
        if kind == "cover":
            slides.append({"slide_type": "cover", "lead_headline": title, "body_content": "", "takeaway": ""})
        elif kind == "call_to_action":
            slides.append({"slide_type": "call_to_action", "lead_headline": "혼자 해결하기 어렵다면", "body_content": "", "takeaway": ""})
        elif kind in ("steps", "checklist", "numbered"):
            chunk = sentences[cursor:cursor + 4] or sentences[-1:]
            cursor += len(chunk)
            slides.append({"slide_type": kind, "lead_headline": chunk[0][:28], "body_content": "\n".join(chunk), "takeaway": "",
                           "badge": f"{len(slides):02d}" if kind == "numbered" else ""})
        elif kind == "big_number":
            found = next((s for s in sentences[cursor:] if _NUM_RE.search(s)), sentences[min(cursor, len(sentences) - 1)])
            cursor = min(cursor + 1, len(sentences))
            num = _NUM_RE.search(found)
            slides.append({"slide_type": "big_number", "lead_headline": found[:28], "body_content": "",
                           "stat_value": num.group(0) if num else "", "stat_label": found[:30], "takeaway": ""})
        elif kind == "single" and len(sequence) == 1:
            # 카드 한 장 요약: 첫 문장 = 제목, 다음 한두 문장 = 핵심, 그다음 문장 = 마무리 한 줄
            body = sentences[1:3]
            slides.append({"slide_type": "single", "lead_headline": title[:40], "body_content": "\n".join(body),
                           "takeaway": sentences[3] if len(sentences) > 3 else ""})
        else:
            chunk = sentences[cursor:cursor + 2] or sentences[-1:]
            cursor += len(chunk)
            slides.append({"slide_type": kind, "lead_headline": chunk[0][:28], "body_content": "\n".join(chunk[1:] or chunk), "takeaway": ""})
    return {"title": title, "slides": slides, "sns_caption": "", "hashtags": []}


# --- 후처리 -----------------------------------------------------------------

def _cta_slide(brand: BrandKit, headline: str, disclaimer: str = "") -> Dict[str, Any]:
    """연락처·슬로건은 브랜드 킷 값으로 고정한다(AI가 숫자를 만들지 않게)."""
    lines = ["네이버 예약 또는 전화로 편하게 문의하세요"]
    if brand.phone:
        lines.append(f"전화 {brand.phone}")
    if brand.email:
        lines.append(f"이메일 {brand.email}")
    if disclaimer:
        lines.append(disclaimer)
    return {"slide_type": "call_to_action", "lead_headline": headline or "혼자 해결하기 어렵다면",
            "body_content": "\n".join(lines), "takeaway": SLOGAN_SUB}


def plan_cards(
    source_text: str,
    type_id: Optional[str] = None,
    kit_id: Optional[int] = None,
    count: Optional[int] = None,
    design_id: Optional[str] = None,
    use_llm: bool = True,
    assets: Optional[List[MediaAsset]] = None,
    elements: Optional[BrandElements] = None,
    image_mode: str = "own_first",
    generate=generate_text,
) -> Tuple[EditableStoryboard, Dict[str, Any]]:
    """원고 → (스토리보드, 보고서). 보고서: engine, warnings, fit_warning, blacklist_hits."""
    if not (source_text or "").strip():
        raise card_types.CardTypeError("원고가 비어 있습니다.")
    pack = card_types.get(type_id)
    sequence = card_types.free_sequence(pack, count) if count else card_types.expand_sequence(pack, count)
    kit = repo.get_brand_kit(kit_id)
    brand = from_db(kit_id)
    blacklist = kit.get("blacklist_map") or {}
    design = design_templates.get(design_id or pack.get("layout_default"))
    report: Dict[str, Any] = {"engine": "rule-based", "warnings": [], "blacklist_hits": [],
                              "fit_warning": card_types.fit_warning(pack, source_text), "card_type": pack["id"]}

    data: Optional[Dict[str, Any]] = None
    if use_llm:
        try:
            system, prompt = _build_prompt(source_text, pack, sequence, kit, brand, blacklist)
            vendor = get_configured_vendor("text")
            data = _extract_json(generate(vendor=vendor, prompt=prompt, system=system, max_tokens=4000, note="card-plan"))
            model = repo.resolve_slot_model("text")
            report["engine"] = f"llm:{model['model_id'] if model else vendor}"
        except Exception as exc:  # noqa: BLE001 — AI가 없거나 실패해도 규칙 기반으로 계속한다
            report["warnings"].append(f"AI 기획을 쓰지 못해 규칙 기반으로 만들었습니다: {exc}")
            data = None
    if data is None:
        data = _rule_based(source_text, sequence)

    raw_slides = [s for s in (data.get("slides") or []) if isinstance(s, dict)]
    slides: List[CardSlide] = []
    for i, slot in enumerate(sequence):
        raw = dict(raw_slides[i]) if i < len(raw_slides) else {}
        raw["slide_type"] = slot["archetype"]      # 종류의 장 구성이 원형을 정한다(AI가 바꾸지 못함)
        if slot["archetype"] == "call_to_action":
            disclaimer = pack.get("disclaimer", "")
            raw = _cta_slide(brand, _nl(raw.get("lead_headline")), disclaimer)
        fields = {k: _nl(raw.get(k)) for k in ("lead_headline", "body_content", "takeaway", "stat_value", "stat_label", "badge", "image_prompt")}
        fields["lead_headline"] = fields["lead_headline"].replace("\n", " ")
        for key in _TEXT_FIELDS:
            fields[key], hits = apply_blacklist_dictionary(fields[key], blacklist)
            report["blacklist_hits"] += hits
        if slot["archetype"] == "numbered" and not fields["badge"]:
            fields["badge"] = f"{i:02d}"
        slides.append(CardSlide(slide_number=i + 1, slide_type=slot["archetype"], **fields))

    if report["fit_warning"]:
        report["warnings"].append(report["fit_warning"])
    if report["blacklist_hits"]:
        terms = ", ".join(sorted({h["forbidden"] for h in report["blacklist_hits"]}))
        report["warnings"].append(f"금기어({terms})를 사전의 대체 표현으로 자동으로 바꿨습니다 — 문장이 어색하지 않은지 확인하세요.")

    # 팩트 락: 원문·브랜드 팩트에 없는 숫자와 근거가 약한 줄을 알린다.
    allowed = _numbers(source_text) | _numbers(" ".join(kit.get("core_facts") or [])) | _numbers(f"{brand.phone} {brand.email} {brand.address}")
    for s in slides:
        if s.slide_type == "call_to_action":
            continue
        extra = sorted(_numbers(" ".join(getattr(s, k) for k in _TEXT_FIELDS + ("stat_value",))) - allowed - {str(s.slide_number), s.badge.lstrip("0")})
        if extra:
            report["warnings"].append(f"{s.slide_number}번 카드에 원문·팩트에 없는 숫자가 있습니다: {', '.join(extra)} — 확인하세요.")
    for num, line in source_check.unsupported_lines(slides, [source_text, " ".join(kit.get("core_facts") or [])]):
        report["warnings"].append(f"{num}번 카드의 '{line[:24]}…'은(는) 원문에 근거가 약합니다 — 확인하세요.")

    assets = list(assets or [])
    title = _nl(data.get("title")) or (slides[0].lead_headline if slides else "")
    caption, hits = apply_blacklist_dictionary(_nl(data.get("sns_caption")), blacklist)
    report["blacklist_hits"] += hits
    tags = [t if str(t).startswith("#") else f"#{t}" for t in (data.get("hashtags") or []) if str(t).strip()][:10]
    storyboard = EditableStoryboard(
        title=title, target_audience=kit.get("name") or "", tone_and_manner=(kit.get("tone_and_manner") or "").splitlines()[0] if kit.get("tone_and_manner") else "",
        visual_style="", is_anonymized=True, card_slides=slides, sns_caption=caption, hashtags=tags,
        fact_check_log=list(report["warnings"]), engine=report["engine"], card_format=pack["id"],
        brand_id=str(kit.get("id") or ""), brand_elements=elements or BrandElements(), design_id=design.id, assets=assets,
        image_mode=image_mode if image_mode in images.IMAGE_MODES else "own_first",
    )
    images.apply_mode(storyboard)     # 내 사진을 사진 칸에 먼저 배치(AI 이미지보다 먼저)
    return storyboard, report
