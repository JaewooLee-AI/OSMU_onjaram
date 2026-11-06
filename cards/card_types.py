"""카드 종류 팩 — 카드뉴스의 종류(장 구성·작성 틀·AI 지침)를 JSON 파일 하나로 정의합니다.

종류를 늘릴 때 코드를 고치지 않습니다. 내장 팩은 `cards/types/*.json`, 사용자가 만든 팩은 데이터 폴더의
`card_types/*.json`(같은 id면 사용자 팩이 내장 팩을 덮어씁니다). 설계: docs/설계안_온자람_OSMU_v0.1.md §5.

팩의 `sequence`는 슬라이드 원형(archetype)을 순서대로 적은 것이고, `repeat: true`인 칸이 장수에 따라 늘어납니다.
원형은 렌더러가 그릴 수 있는 슬라이드 종류(VALID_ARCHETYPES)여야 하며, 팩이 잘못되면 로드를 거부하고 이유를 돌려줍니다
(`load_all()`의 errors) — 사용자가 만든 팩 때문에 앱이 깨지지 않게 하려는 것입니다.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from cards.paths import CARDS_DIR, DATA_DIR

BUILTIN_DIR = os.path.join(CARDS_DIR, "types")
CUSTOM_DIR = os.path.join(DATA_DIR, "card_types")

# 렌더러(cards/card_renderer.py)가 그릴 수 있는 슬라이드 종류. 새 모양을 만들면 여기와 렌더러에 같이 등록합니다.
VALID_ARCHETYPES = (
    "cover", "body", "numbered", "steps", "checklist", "qa", "quote",
    "big_number", "comparison_table", "event_info", "call_to_action", "single",
)
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


class CardTypeError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 오류."""


def validate(pack: Any) -> List[str]:
    """팩의 문제 목록(비어 있으면 정상)."""
    if not isinstance(pack, dict):
        return ["JSON 객체가 아닙니다."]
    problems: List[str] = []
    if not _ID_RE.match(str(pack.get("id") or "")):
        problems.append("id는 영소문자·숫자·-·_ 만 쓸 수 있고 41자 이내여야 합니다.")
    if not str(pack.get("name") or "").strip():
        problems.append("name(화면 이름)이 필요합니다.")
    if pack.get("status", "available") not in ("available", "draft", "hidden"):
        problems.append("status는 available | draft | hidden 이어야 합니다.")
    seq = pack.get("sequence")
    if not isinstance(seq, list) or not seq:
        problems.append("sequence(장 구성)가 비어 있습니다.")
    else:
        for i, slot in enumerate(seq, 1):
            if not isinstance(slot, dict) or slot.get("archetype") not in VALID_ARCHETYPES:
                problems.append(f"sequence {i}번째: 알 수 없는 원형 '{(slot or {}).get('archetype') if isinstance(slot, dict) else slot}'"
                                f" (사용 가능: {', '.join(VALID_ARCHETYPES)})")
    count = pack.get("count") or {}
    try:
        lo, hi, df = int(count.get("min", 1)), int(count.get("max", 10)), int(count.get("default", 5))
        if not (1 <= lo <= df <= hi <= 12):
            problems.append("count는 1 ≤ min ≤ default ≤ max ≤ 12 이어야 합니다.")
    except (TypeError, ValueError):
        problems.append("count의 min·max·default는 숫자여야 합니다.")
    if not str(pack.get("llm_structure") or "").strip():
        problems.append("llm_structure(AI에게 줄 구성 지침)가 필요합니다.")
    fit = pack.get("fit_check")
    if fit is not None and not (isinstance(fit, dict) and isinstance(fit.get("need_any", []), list)):
        problems.append("fit_check는 {need_any: [...], min_hits: 숫자} 형태여야 합니다.")
    return problems


def _read_dir(folder: str, source: str) -> Tuple[Dict[str, dict], Dict[str, List[str]]]:
    packs: Dict[str, dict] = {}
    errors: Dict[str, List[str]] = {}
    if not os.path.isdir(folder):
        return packs, errors
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as f:
                pack = json.load(f)
        except (OSError, ValueError) as exc:
            errors[name] = [f"파일을 읽지 못했습니다: {exc}"]
            continue
        problems = validate(pack)
        if problems:
            errors[name] = problems
            continue
        pack["source"] = source
        packs[pack["id"]] = pack
    return packs, errors


# 목록·기본 선택 순서(가장 무난한 종류가 앞). 여기 없는 종류(사용자 팩 등)는 그 뒤에 이름순으로 놓는다.
PREFERRED_ORDER = ("empathy", "info_summary", "checklist", "howto", "qna", "expert", "big_number", "event_notice")


def _ordered(packs: Dict[str, dict]) -> Dict[str, dict]:
    rank = {k: i for i, k in enumerate(PREFERRED_ORDER)}
    return dict(sorted(packs.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[1].get("name", ""))))


def load_all(include_hidden: bool = False) -> Tuple[Dict[str, dict], Dict[str, List[str]]]:
    """(id → 팩, 파일 이름 → 문제 목록). 사용자 팩이 같은 id의 내장 팩을 덮어씁니다."""
    packs, errors = _read_dir(BUILTIN_DIR, "builtin")
    custom, custom_errors = _read_dir(CUSTOM_DIR, "custom")
    packs.update(custom)
    errors.update({f"사용자:{k}": v for k, v in custom_errors.items()})
    if not include_hidden:
        packs = {k: v for k, v in packs.items() if v.get("status", "available") != "hidden"}
    return _ordered(packs), errors


def available(include_draft: bool = False) -> List[dict]:
    packs, _ = load_all()
    ok = ("available", "draft") if include_draft else ("available",)
    return [p for p in packs.values() if p.get("status", "available") in ok]


def get(type_id: Optional[str]) -> dict:
    """id의 팩. 없거나 쓸 수 없으면 첫 번째 사용 가능한 팩."""
    packs, _ = load_all()
    pack = packs.get(type_id or "")
    if pack and pack.get("status", "available") != "hidden":
        return pack
    usable = [p for p in packs.values() if p.get("status", "available") == "available"]
    if not usable:
        raise CardTypeError("사용할 수 있는 카드 종류가 없습니다.")
    return usable[0]


def default_count(pack: dict) -> int:
    return int((pack.get("count") or {}).get("default", len(pack["sequence"])))


def clamp_count(pack: dict, count: Optional[int]) -> int:
    c = pack.get("count") or {}
    lo, hi = int(c.get("min", 1)), int(c.get("max", 12))
    return max(lo, min(hi, int(count or default_count(pack))))


def expand_sequence(pack: dict, count: Optional[int] = None) -> List[dict]:
    """팩의 장 구성을 `count`장에 맞게 펼칩니다. `repeat`가 없는 팩은 정해진 장수 그대로입니다."""
    seq = [dict(s) for s in pack["sequence"]]
    fixed = [s for s in seq if not s.get("repeat")]
    repeating = [s for s in seq if s.get("repeat")]
    want = clamp_count(pack, count)
    if not repeating:
        return seq
    extra = max(0, want - len(fixed))
    if want < len(fixed):  # 고정 칸보다 적게 요청하면 표지와 마지막 칸은 지키고 가운데부터 뺀다
        keep = fixed[:1] + fixed[-1:] if len(fixed) > 1 else fixed
        middle = fixed[1:-1]
        room = max(0, want - len(keep))
        return keep[:1] + middle[:room] + keep[1:]
    per = [extra // len(repeating) + (1 if i < extra % len(repeating) else 0) for i in range(len(repeating))]
    out: List[dict] = []
    rep_i = 0
    for s in seq:
        if s.get("repeat"):
            out += [{k: v for k, v in s.items() if k != "repeat"} for _ in range(per[rep_i])]
            rep_i += 1
        else:
            out.append(s)
    return out


MAX_FREE_COUNT = 8


def free_sequence(pack: dict, count: int) -> List[dict]:
    """사용자가 고른 장수(1~8)에 맞춘 장 구성 — 종류가 허용하는 범위(min~max)와 상관없이 만듭니다.

    1장은 '한 장 카드'. 2장 이상은 표지·마지막 안내 카드를 지키고, 가운데는 그 종류의 기본 구성을 앞에서부터 쓰되
    모자라면 되풀이 칸(없으면 본문 카드)을 늘려 채우고, 남으면 뒤에서부터 뺍니다.
    """
    n = max(1, min(MAX_FREE_COUNT, int(count)))
    if n == 1:
        return [{"archetype": "single", "hint": "제목 + 핵심 한두 문장 + 마무리 한 줄"}]
    base = expand_sequence(pack, None)
    first = base[0] if base and base[0]["archetype"] == "cover" else None
    last = base[-1] if base and base[-1]["archetype"] == "call_to_action" else None
    middle = base[(1 if first else 0):(len(base) - 1 if last else len(base))]
    need = n - (1 if first else 0) - (1 if last else 0)
    if need < 0:     # 표지·안내 카드를 다 넣을 수 없는 2장: 표지와 안내만
        return [s for s in (first, last) if s][:n] or base[:n]
    if need <= len(middle):
        middle = middle[:need]
    else:
        filler = next((s for s in reversed(middle) if s["archetype"] not in ("steps", "numbered", "big_number")),
                      {"archetype": "body", "hint": "핵심 내용 이어서"})
        filler = {k: v for k, v in filler.items() if k != "repeat"}
        # 늘어나는 카드는 비슷한 종류 바로 뒤에 붙인다(마지막 안내 카드 앞)
        middle = middle + [dict(filler) for _ in range(need - len(middle))]
    return [dict(s) for s in ([first] if first else []) + middle + ([last] if last else [])]


_NUMBER_RE = re.compile(r"\d[\d,.]*\s*(?:%|원|명|점|회기|회|일|개|시간|분|장|가지|주)?")


def fit_warning(pack: dict, text: str) -> str:
    """원고가 이 종류에 맞는지 간단히 점검합니다. 맞지 않으면 안내 문구, 괜찮으면 빈 문자열."""
    text = text or ""
    fit = pack.get("fit_check")
    if fit:
        keywords = [k for k in fit.get("need_any", []) if k]
        hits = sum(1 for k in keywords if k in text)
        if keywords and hits < int(fit.get("min_hits", 1)):
            return (f"원고에 '{pack['name']}'에 어울리는 내용이 거의 보이지 않습니다. "
                    f"작성 틀을 쓰거나 다른 종류(예: 정보 요약형)를 골라 보세요.")
    need_numbers = int(pack.get("min_numbers", 0) or 0)
    if need_numbers and len(_NUMBER_RE.findall(text)) < need_numbers:
        return f"이 종류는 원고에 수치가 {need_numbers}개 이상 있어야 잘 맞습니다."
    return ""


def template_text(pack: dict) -> str:
    return pack.get("template", "")


PLACEHOLDER_RE = re.compile(r"【[^】]*】")


def has_placeholder(text: str) -> bool:
    """작성 틀의 【 】 칸이 채워지지 않고 남아 있는지."""
    return bool(PLACEHOLDER_RE.search(text or ""))


# --- 사용자 팩 관리 ---------------------------------------------------------

def save_custom(pack: dict) -> str:
    problems = validate(pack)
    if problems:
        raise CardTypeError("; ".join(problems))
    os.makedirs(CUSTOM_DIR, exist_ok=True)
    path = os.path.join(CUSTOM_DIR, f"{pack['id']}.json")
    body = {k: v for k, v in pack.items() if k != "source"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=1)
    return path


def duplicate(type_id: str, new_id: str, new_name: Optional[str] = None) -> dict:
    """내장·사용자 팩을 복제해 새 사용자 팩(draft)으로 저장합니다."""
    base = get(type_id)
    packs, _ = load_all(include_hidden=True)
    if new_id in packs:
        raise CardTypeError(f"이미 같은 id('{new_id}')의 종류가 있습니다.")
    pack = json.loads(json.dumps({k: v for k, v in base.items() if k != "source"}))
    pack.update({"id": new_id, "name": new_name or f"{base['name']} (복사)", "status": "draft"})
    save_custom(pack)
    return pack


def delete_custom(type_id: str) -> bool:
    path = os.path.join(CUSTOM_DIR, f"{type_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def import_json(raw: str) -> dict:
    """JSON 문자열로 받은 팩을 사용자 팩으로 저장합니다(검증 실패 시 CardTypeError)."""
    try:
        pack = json.loads(raw)
    except ValueError as exc:
        raise CardTypeError(f"JSON을 읽지 못했습니다: {exc}") from exc
    save_custom(pack)
    return pack


def export_json(type_id: str) -> str:
    pack = {k: v for k, v in get(type_id).items() if k != "source"}
    return json.dumps(pack, ensure_ascii=False, indent=1)
