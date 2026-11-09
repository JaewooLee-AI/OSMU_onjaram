"""Google(Gemini) 모델·가격 자동 불러오기 — '간편 설정'용.

사용자는 Google API 키만 넣으면 됩니다. 이 모듈이
1) 키로 쓸 수 있는 모델 목록을 조회하고(`list_available`, Gemini models.list),
2) 공식 가격 페이지(`PRICING_URL`, 로그인 없이 마크다운으로 내려옴)를 읽어 모델별 단가를 뽑고(`parse_pricing`),
3) 기능(슬롯)마다 추천 모델을 고르고(`recommend`),
4) 사용자가 [적용]을 누르면 모델·단가·슬롯을 저장합니다(`apply`).

원칙
- 모델 이름은 코드에 박지 않습니다. 추천은 '정식(미리보기 아님) 최신 Flash' 같은 **규칙**으로만 고릅니다.
- 가격표를 읽지 못한 값은 지어내지 않고 비워 둡니다('단가 미등록'). 금액은 참고용 예상치입니다.
- 가격표에 날짜가 붙은 변경(예: "$0.75 through December 31, 2026. $1.50 starting January 1, 2027.")은
  오늘 기준 단가를 저장하고, 앞으로의 변경은 모델 옵션 `price_schedule`에 넣어 두었다가 그날이 되면
  `apply_due_prices`가 바꿉니다(앱 시작·모델 탭을 열 때 호출).
- 단가는 'Standard' 탭의 유료(Paid Tier) 칸, 구간이 나뉘면 첫 구간(짧은 프롬프트·글자 입력)을 씁니다.
  이미지 모델은 1K 이미지 1장당 가격(앱이 1K로 요청)과 '글자·추론 출력' 100만 토큰당 가격을 씁니다.
"""
from __future__ import annotations

import datetime as _dt
import re
import urllib.request
from typing import Any, Callable, Dict, List, Optional

PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"
STATE_KEY = "google_catalog"

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"], 1)}
_DATE = r"([A-Z][a-z]+ \d{1,2}, \d{4})"
_SECTION_RE = re.compile(r"^## (.+?)\s*\{% id=\"[^\"]*\" %\}\s*$", re.M)
_ID_RE = re.compile(r"\*\[`([a-z0-9][a-z0-9.\-]*)`\]")
_PRICE_RE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?)")
_IMAGE_ANY_RE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?) per image")
_SHUTDOWN_RE = re.compile(r"deprecated\]?(?:\([^)]*\))?\s+and will be shut\s+down on " + r"([A-Z][a-z]+ \d{1,2}, \d{4})", re.S)
_IMAGE_1K_RE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?) per (?:[0-9.]+K/)*1K(?:/[0-9.]+K)*(?: resolution)? image")


# --- 가격표 읽기 --------------------------------------------------------------

def fetch_pricing_text(opener: Optional[Callable[[str], str]] = None, timeout: int = 20) -> str:
    if opener is not None:
        return opener(PRICING_URL)
    req = urllib.request.Request(PRICING_URL, headers={"User-Agent": "OSMU-Onjaram/1.0", "Accept": "text/markdown"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — 고정된 공식 주소
        return resp.read().decode("utf-8", "replace")


def _date(text: str) -> Optional[_dt.date]:
    m = re.match(r"([A-Za-z]+) (\d{1,2}), (\d{4})", text.strip())
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    return _dt.date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))


def _rows(table: str) -> List[List[str]]:
    """마크다운 표(`* 칸` 목록을 `---`로 나눈 형식)를 [기능, 무료, 유료] 줄 목록으로."""
    rows = []
    for chunk in re.split(r"^\s*---\s*$", table, flags=re.M):
        cells: List[str] = []
        for line in chunk.splitlines():
            s = line.strip()
            if not s or s.startswith("{%"):
                continue
            if s.startswith("* "):
                cells.append(s[2:].strip())
            elif cells:
                cells[-1] += "\n" + s
        if cells:
            rows.append(cells)
    return rows


def _segments(cell: str) -> List[Dict[str, Any]]:
    """유료 칸 한 개 → [{"value", "from", "until", "text"}]. 줄마다 가격 하나(+조건)."""
    out = []
    for line in re.split(r"\n|(?<=\.)\s{2,}", cell):
        line = re.sub(r"\{%.*?%\}", "", line).strip()
        if not line or line.lower().startswith("equivalent to") or "per hour" in line:
            continue
        m = _PRICE_RE.search(line)
        if not m:
            continue
        until = re.search(r"through " + _DATE, line)
        start = re.search(r"starting " + _DATE, line)
        out.append({"value": float(m.group(1)), "until": _date(until.group(1)) if until else None,
                    "from": _date(start.group(1)) if start else None, "text": line})
    return out


def _pick(segs: List[Dict[str, Any]], today: _dt.date) -> Optional[float]:
    for s in segs:
        if (s["from"] is None or s["from"] <= today) and (s["until"] is None or today <= s["until"]):
            return s["value"]
    return None


def _future(segs: List[Dict[str, Any]], today: _dt.date) -> Dict[_dt.date, float]:
    out: Dict[_dt.date, float] = {}
    for s in segs:
        if s["from"] and s["from"] > today and s["from"] not in out:
            out[s["from"]] = s["value"]
    return out


def _standard_table(body: str) -> str:
    m = re.search(r'\{% tab title="Standard" %\}(.*?)\{% /tab %\}', body, re.S)
    if m:
        return m.group(1)
    m = re.search(r"\{% table %\}(.*?)\{% /table %\}", body, re.S)
    return m.group(1) if m else ""


def parse_pricing(text: str, today: Optional[_dt.date] = None) -> Dict[str, Dict[str, Any]]:
    """가격 페이지 마크다운 → {model_id: {"name", "input", "output", "cache", "per_image", "schedule": [...]}}.
    값을 못 읽은 칸은 None. `schedule`은 오늘 이후 바뀌는 단가 [{"from": "YYYY-MM-DD", "input": …}]."""
    today = today or _dt.date.today()
    heads = list(_SECTION_RE.finditer(text or ""))
    result: Dict[str, Dict[str, Any]] = {}
    for i, h in enumerate(heads):
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        header = body.split("{% hr /%}", 1)[0]
        ids = _ID_RE.findall(header)
        if not ids:
            continue
        name = re.sub(r"\s*🍌", "", h.group(1)).strip()
        entry: Dict[str, Any] = {"name": name, "input": None, "output": None, "cache": None, "per_image": None,
                                 "shutdown": None}
        shut = _SHUTDOWN_RE.search(re.sub(r"\s+", " ", body[:3000]))
        if shut and _date(shut.group(1)):
            entry["shutdown"] = _date(shut.group(1)).isoformat()
        changes: Dict[_dt.date, Dict[str, float]] = {}
        for cells in _rows(_standard_table(body)):
            if len(cells) < 3:
                continue
            feature, paid = cells[0].lower(), cells[2]
            key = ("input" if feature.startswith("input price") else
                   "output" if feature.startswith("output price") else
                   "cache" if feature.startswith("context caching") else None)
            if key is None:
                continue
            segs = _segments(paid)
            entry[key] = _pick(segs, today)
            for d, v in _future(segs, today).items():
                changes.setdefault(d, {})[key] = v
            if key == "output":
                img = _IMAGE_1K_RE.search(paid) or _IMAGE_ANY_RE.search(paid)
                if img:
                    entry["per_image"] = float(img.group(1))
                    # 이미지 모델: 출력 칸 첫 줄 "$3 (text and thinking)"이 글자·추론 출력 단가
                    text_seg = next((s for s in segs if "text" in s["text"].lower()), None)
                    entry["output"] = text_seg["value"] if text_seg else None
        entry["schedule"] = [{"from": d.isoformat(), **v} for d, v in sorted(changes.items())]
        for mid in ids:
            result.setdefault(mid, dict(entry))
    return result


# --- 쓸 수 있는 모델 목록 -------------------------------------------------------

def list_available(api_key: str) -> List[str]:
    """이 키로 호출할 수 있는 Gemini 모델 ID 목록(`models/` 접두사 없이)."""
    from ai_workers.multi_llm_router import google_client

    client = google_client(api_key)
    out = []
    for m in client.models.list(config={"page_size": 1000}):
        name = (getattr(m, "name", "") or "").split("/", 1)[-1]
        if name:
            out.append(name)
    return out


# --- 추천 규칙 ----------------------------------------------------------------

# 슬롯 → 이름 규칙(앞에서부터 우선). 정식 버전이 있으면 미리보기(preview)는 고르지 않습니다.
# 블로그·사진 분석 슬롯은 비워 두면 기본 글쓰기 모델을 따르므로 추천하지 않습니다. 영상(Omni)은 아직 호출 코드가 없어 제외.
RULES = {
    "text": [r"^gemini-[\d.]+-flash$", r"^gemini-[\d.]+-flash-lite$"],
    "image": [r"^gemini-[\d.]+-flash-image$", r"^gemini-[\d.]+-pro-image$"],
    "tts": [r"^gemini-[\d.]+-flash-tts$", r"^gemini-[\d.]+-flash-lite-tts$"],
}
SLOT_NEEDS = {"text": "text", "image": "image", "tts": "tts"}
_EXCLUDE = ("live", "transcribe", "translate", "embedding", "robotics", "native-audio", "omni", "lyria", "gemma")


def _version(model_id: str) -> tuple:
    m = re.match(r"gemini-([\d.]+)", model_id)
    return tuple(int(x) for x in m.group(1).split(".") if x.isdigit()) if m else ()


def candidates(slot: str, priced: Dict[str, Dict[str, Any]], available: Optional[List[str]]) -> List[str]:
    """그 슬롯에 고를 수 있는 모델(가격표에 있고, 키로 쓸 수 있는 것). 추천 순서대로."""
    pool = [m for m in priced if not any(x in m for x in _EXCLUDE) and not priced[m].get("shutdown")]
    if available is not None:
        avail = set(available)
        pool = [m for m in pool if m in avail]
    need = SLOT_NEEDS[slot]
    if need == "image":
        pool = [m for m in pool if priced[m].get("per_image") is not None or "image" in m]
    elif need == "tts":
        pool = [m for m in pool if m.endswith("-tts")]
    else:
        pool = [m for m in pool if "image" not in m and not m.endswith("-tts")]
    ranked: List[str] = []
    for preview_ok in (False, True):
        for rule in RULES[slot]:
            hits = [m for m in pool if re.match(rule, m.replace("-preview", "")) and (preview_ok or "preview" not in m)]
            for m in sorted(hits, key=_version, reverse=True):
                if m not in ranked:
                    ranked.append(m)
    ranked += sorted([m for m in pool if m not in ranked], key=_version, reverse=True)
    return ranked


def recommend(priced: Dict[str, Dict[str, Any]], available: Optional[List[str]]) -> Dict[str, Optional[str]]:
    return {slot: (candidates(slot, priced, available) or [None])[0] for slot in RULES}


# --- 형식 점검 ----------------------------------------------------------------

FORMAT_MESSAGE = ("⚠️ Google 가격표 형식이 바뀌어 단가를 제대로 읽지 못했습니다. "
                  "아래 '⚙️ 고급 설정'에서 직접 입력하시거나 관리자에게 문의하세요.")


def _complete(slot: str, p: Optional[Dict[str, Any]]) -> bool:
    if not p or p.get("input") is None:
        return False
    return p.get("per_image") is not None if SLOT_NEEDS[slot] == "image" else p.get("output") is not None


def format_problems(priced: Dict[str, Dict[str, Any]], available: Optional[List[str]] = None) -> List[str]:
    """가격표를 제대로 읽었는지 점검합니다. 빈 목록이면 정상.
    모델을 하나도 못 읽었거나, 기능마다 단가가 온전히 읽힌 후보가 하나도 없으면 형식이 바뀐 것으로 봅니다."""
    if not priced:
        return ["가격표에서 모델을 하나도 찾지 못했습니다."]
    problems = []
    for slot in RULES:
        cands = candidates(slot, priced, available)
        if cands and not any(_complete(slot, priced.get(m)) for m in cands[:3]):
            problems.append(f"{SLOT_NEEDS[slot]} 모델의 단가를 읽지 못했습니다.")
    return problems


# --- 저장 --------------------------------------------------------------------

def price_line(p: Optional[Dict[str, Any]]) -> str:
    """화면용 한 줄 요약."""
    if not p:
        return "단가를 읽지 못했습니다 — 단가 미등록"
    parts = []
    if p.get("input") is not None:
        parts.append(f"입력 ${p['input']:g}")
    if p.get("per_image") is not None:
        parts.append(f"이미지 1장(1K) ${p['per_image']:g}")
    if p.get("output") is not None:
        parts.append(f"{'글자 출력' if p.get('per_image') is not None else '출력'} ${p['output']:g}")
    text = " · ".join(parts) + (" (100만 토큰당)" if p.get("input") is not None else "")
    if p.get("shutdown"):
        text += f"\n  ⚠️ {p['shutdown']} 서비스 종료 예정"
    for ch in p.get("schedule") or []:
        moved = ", ".join(f"{k} ${v:g}" for k, v in ch.items() if k != "from")
        text += f"\n  ↳ {ch['from']}부터 {moved.replace('input', '입력').replace('output', '출력').replace('cache', '캐시').replace('per_image', '이미지')}"
    return text or "단가를 읽지 못했습니다 — 단가 미등록"


def _save_price(vendor: str, model_id: str, p: Dict[str, Any]) -> None:
    from core import repo

    if p.get("input") is not None and p.get("output") is not None:
        repo.save_model_price(vendor, model_id, p["input"], p["output"], p.get("cache"))
    elif p.get("input") is not None and p.get("per_image") is not None:
        repo.save_model_price(vendor, model_id, p["input"], 0.0, p.get("cache"))


def _caps(slot_need: str) -> List[str]:
    return ["text", "vision"] if slot_need == "text" else [slot_need]


def apply(choices: Dict[str, Optional[str]], priced: Dict[str, Dict[str, Any]], today: Optional[_dt.date] = None) -> List[str]:
    """고른 모델을 등록하고 단가·슬롯을 저장합니다. 반환: 화면에 보일 결과 줄."""
    from core import repo

    today = today or _dt.date.today()
    done = []
    for slot, model_id in choices.items():
        if not model_id:
            continue
        need = SLOT_NEEDS.get(slot, slot)
        p = priced.get(model_id) or {}
        existing = repo.find_model("google", model_id)
        caps = list(dict.fromkeys(((existing or {}).get("capabilities") or []) + _caps(need)))
        options = dict((existing or {}).get("options") or {})
        options["price_schedule"] = p.get("schedule") or []
        options["price_source"] = f"{PRICING_URL} ({today.isoformat()} 불러옴)"
        ref = repo.upsert_model("google", model_id, display_name=p.get("name") or model_id, capabilities=caps,
                                enabled=True, per_image=p.get("per_image"),
                                per_second=(existing or {}).get("per_second"),
                                note=f"공식 가격표에서 자동으로 불러옴 ({today.isoformat()})", options=options,
                                model_ref=(existing or {}).get("id"))
        if p:
            _save_price("google", model_id, p)
        repo.set_slot(slot, ref)
        done.append(f"{repo.MODEL_SLOTS[slot][0]}: {p.get('name') or model_id}")
    repo.set_app_state(STATE_KEY, {"fetched": today.isoformat()})
    return done


def refresh_registered(priced: Dict[str, Dict[str, Any]], today: Optional[_dt.date] = None) -> int:
    """이미 등록된 Google 모델의 단가를 새 가격표로 갱신합니다. 갱신한 모델 수."""
    from core import repo

    today = today or _dt.date.today()
    n = 0
    for m in repo.list_models():
        if m["vendor"] != "google" or m["model_id"] not in priced:
            continue
        p = priced[m["model_id"]]
        options = dict(m.get("options") or {})
        options["price_schedule"] = p.get("schedule") or []
        options["price_source"] = f"{PRICING_URL} ({today.isoformat()} 불러옴)"
        repo.upsert_model("google", m["model_id"], display_name=m["display_name"], capabilities=m["capabilities"],
                          enabled=m["enabled"], per_image=p.get("per_image") if p.get("per_image") is not None else m.get("per_image"),
                          per_second=m.get("per_second"), note=m.get("note") or "", options=options, model_ref=m["id"])
        _save_price("google", m["model_id"], p)
        n += 1
    repo.set_app_state(STATE_KEY, {"fetched": today.isoformat()})
    return n


def apply_due_prices(today: Optional[_dt.date] = None) -> List[str]:
    """예정된 단가 변경 중 날짜가 된 것을 적용합니다(앱 시작·모델 탭을 열 때). 반환: 바꾼 모델 이름."""
    from core import repo

    today = today or _dt.date.today()
    changed = []
    for m in repo.list_models():
        options = dict(m.get("options") or {})
        sched = options.get("price_schedule") or []
        due = [c for c in sched if c.get("from") and c["from"] <= today.isoformat()]
        if not due:
            continue
        price = repo.get_model_price(m["vendor"], m["model_id"]) or {}
        cur = {"input": price.get("input_per_mtok"), "output": price.get("output_per_mtok"),
               "cache": price.get("cached_input_per_mtok"), "per_image": m.get("per_image")}
        for c in due:
            cur.update({k: v for k, v in c.items() if k != "from"})
        options["price_schedule"] = [c for c in sched if c not in due]
        repo.upsert_model(m["vendor"], m["model_id"], display_name=m["display_name"], capabilities=m["capabilities"],
                          enabled=m["enabled"], per_image=cur["per_image"], per_second=m.get("per_second"),
                          note=m.get("note") or "", options=options, model_ref=m["id"])
        if cur["input"] is not None and cur["output"] is not None:
            repo.save_model_price(m["vendor"], m["model_id"], cur["input"], cur["output"], cur["cache"])
        changed.append(m["display_name"])
    return changed
