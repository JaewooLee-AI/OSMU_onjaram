"""카드 한 장을 말로 고치기 — "제목을 더 짧게", "이미지를 따뜻한 햇살 느낌으로 바꿔줘", "배경을 연한 파란색으로",
"글자를 크게" 같은 요청.

글 모델을 한 번 불러 요청을 카드 값(제목·내용·마지막 줄·그림 장면 설명)과 모양(배경·글자·강조 색, 글자 크기 배율)으로
바꿉니다. 응답은 **바뀐 칸만** 담습니다. 모양은 `scope`가 "all"이면(모든 카드에 / 전체) 모든 카드에, 아니면 이 카드에만 적용합니다.
- 글: 원문·브랜드 팩트에 없는 숫자는 만들지 않게 하고(받은 뒤 새 숫자는 경고), 금기어 사전을 다시 적용합니다.
- 이미지: 모델이 새 장면 설명(`image_prompt`)만 돌려주고, 실제 AI 이미지는 **비용 확인을 거쳐** 화면에서 만듭니다.
  (실존 인물·글자 금지 규칙은 이미지 생성 쪽에서 항상 붙습니다.)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ai_workers.guardrail import apply_blacklist_dictionary
from ai_workers.multi_llm_router import generate_text, get_configured_vendor
from cards.director import _extract_json
from cards.schema import EditableStoryboard
from core import repo

_NUM_RE = re.compile(r"\d[\d,.]*")
FIELDS = ("lead_headline", "body_content", "takeaway", "image_prompt")
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
COLOR_KEYS = ("bg", "fg", "accent")
SCALE_KEYS = ("title_scale", "body_scale", "takeaway_scale")
SCALE_RANGE = (0.6, 2.0)


def _clean_style(raw: Any) -> Dict[str, Any]:
    """모델이 돌려준 모양 값을 검사해 쓸 수 있는 것만 남긴다. {"reset": True}면 초기화 표시를 남긴다."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    if raw.get("reset"):
        out["reset"] = True
    for k in COLOR_KEYS:
        v = raw.get(k)
        if isinstance(v, str) and _HEX_RE.match(v.strip()):
            out[k] = v.strip().upper()
    for k in SCALE_KEYS:
        try:
            v = float(raw.get(k))
        except (TypeError, ValueError):
            continue
        out[k] = round(max(SCALE_RANGE[0], min(SCALE_RANGE[1], v)), 2)
    return out


def _numbers(text: str) -> set:
    return {n.strip(".,").replace(",", "") for n in _NUM_RE.findall(text or "") if n.strip(".,")}


def _prompt(sb: EditableStoryboard, index: int, instruction: str, kit: dict) -> str:
    c = sb.card_slides[index]
    card = {"카드 종류": c.slide_type, "제목": c.lead_headline, "내용": c.body_content, "아래 한 줄": c.takeaway,
            "그림 장면 설명(영어)": c.image_prompt or "", "현재 모양(비어 있으면 디자인 기본값)": c.style or {}}
    banned = ", ".join(list((kit.get("blacklist_map") or {}))[:30])
    return (
        f"[말투]\n{kit.get('tone_and_manner') or ''}\n\n[쓰지 않을 표현]\n{banned}\n\n"
        f"[현재 카드 {index + 1}/{len(sb.card_slides)}]\n{card}\n\n[사용자 요청]\n{instruction.strip()}\n\n"
        "요청에 필요한 칸만 바꿔서 돌려주세요(바꾸지 않는 칸은 JSON에 넣지 마세요). 규칙: 제목은 28자 안팎(강조할 말은 *별표*), "
        "내용은 줄바꿈으로 나눈 2~4줄(한 줄 22자 안팎), 아래 한 줄은 20자 안팎. **현재 카드에 없는 숫자·가격·날짜·연락처를 만들지 말고**, "
        "치료·완치·효과 보장 표현과 낙인 표현을 쓰지 마세요. 요청이 그림(이미지·사진·분위기·색감·장면)에 관한 것이면 "
        "image_prompt에 새 장면을 영어 한 문장으로 쓰세요(차분한 자연·빛·사물, 사람 얼굴·글자·로고 없이). "
        "요청이 글에 관한 것이면 image_prompt는 넣지 마세요.\n"
        "요청이 카드 모양(배경색·글자색·강조색·글자 크기)에 관한 것이면 style에 넣으세요: bg·fg·accent는 반드시 #RRGGBB(색 이름은 "
        "차분하고 글자가 잘 읽히는 대비의 색으로 바꾸세요), title_scale·body_scale·takeaway_scale는 '현재 모양' 값(없으면 1)에 곱한 0.6~2.0 "
        "사이 숫자(\"크게\"=약 1.2배, \"2배\"=2.0, \"작게\"=약 0.85배). 가운데 칸의 목록·본문 글자는 body_scale, 위 제목은 title_scale, 아래 한 줄은 takeaway_scale입니다. \"원래대로\"면 style에 {\"reset\": true}. 요청이 \"모든 카드·전체\"에 관한 것이면 "
        'scope에 "all"을, 아니면 "card"를 넣으세요.\n'
        '반드시 JSON만 출력: {"lead_headline": "...", "body_content": "...", "takeaway": "...", "image_prompt": "...", '
        '"style": {"bg": "#RRGGBB", "fg": "#RRGGBB", "title_scale": 1.2}, "scope": "card"} (바꿀 칸만 넣으면 됩니다)'
    )


def edit_card(sb: EditableStoryboard, index: int, instruction: str, kit_id: Optional[int] = None,
              generate=generate_text) -> Dict[str, Any]:
    """요청을 카드 한 장에 반영합니다(스토리보드를 직접 고침). 반환: {"changed": [칸 이름], "image_changed": bool, "style_scope": "card"|"all"|None, "warnings": [...]}."""
    if not (instruction or "").strip():
        raise ValueError("요청을 입력하세요.")
    kit = repo.get_brand_kit(kit_id)
    card = sb.card_slides[index]
    raw = generate(vendor=get_configured_vendor("text"), prompt=_prompt(sb, index, instruction, kit),
                   system="당신은 심리상담 기관의 카드뉴스 편집자입니다. 카드에 없는 사실을 만들지 않습니다.",
                   max_tokens=1200, note="card-edit")
    data = _extract_json(raw)
    blacklist = kit.get("blacklist_map") or {}
    before = {f: getattr(card, f) for f in FIELDS}
    allowed = _numbers(" ".join(str(v) for v in before.values()))
    warnings: List[str] = []
    changed: List[str] = []
    for field in FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip() or value.strip() == (before[field] or "").strip():
            continue
        value = value.strip()
        if field != "image_prompt":
            value, hits = apply_blacklist_dictionary(value, blacklist)
            if hits:
                warnings.append("금기어를 사전의 대체 표현으로 바꿨습니다 — 문장을 확인하세요.")
            extra = sorted(_numbers(value) - allowed)
            if extra:
                warnings.append(f"카드에 없던 숫자가 들어갔습니다: {', '.join(extra)} — 확인하세요.")
        setattr(card, field, value)
        changed.append(field)
    # 모양(색·글자 크기): 이 카드만 또는 모든 카드. 글 요청과 달리 숫자·금기어 검사는 필요 없다.
    delta = _clean_style(data.get("style"))
    scope = "all" if str(data.get("scope") or "").lower() == "all" else "card"
    if delta:
        targets = sb.card_slides if scope == "all" else [card]
        for t in targets:
            if delta.get("reset"):
                t.style = {}
            current = dict(t.style or {})
            for k, v in delta.items():
                if k == "reset":
                    continue
                # 글자 크기는 '지금 값에 곱한 값'을 받는 것이 아니라 모델이 계산해 준 최종 배율이므로 그대로 쓴다
                current[k] = v
            t.style = current
        changed.append("style")
    return {"changed": changed, "image_changed": "image_prompt" in changed, "style_scope": scope if delta else None,
            "warnings": warnings}
