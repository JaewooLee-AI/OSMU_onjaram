"""발행 전 동의 점검 — 현장 후기에는 아동·청소년·참여자 사진과 소감이 자주 들어갑니다.

앱은 사진 속 사람을 알아볼 수 없으므로 '동의했는지'를 사람이 확인하게 합니다. 현장 후기이고 사진이 있으면
세 가지를 모두 체크해야 [게시]가 켜집니다(체크 기록은 글에 저장). 사진 설명에 사람이 보이는 단서(얼굴·아이·학생 등)가 있으면
그 사진 수를 알려 줍니다. 칼럼·모집 글은 점검하지 않습니다.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

ITEMS: List[Tuple[str, str]] = [
    ("faces", "사진 속 아동·참여자의 얼굴은 보호자·기관의 동의를 받았거나 가렸습니다."),
    ("org", "기관·학교 이름을 글에 쓰는 것에 동의를 받았습니다."),
    ("quotes", "참여자 소감은 누구인지 알 수 없게(익명) 썼습니다."),
]
KEYS = [k for k, _ in ITEMS]

PEOPLE_WORDS = ("얼굴", "아이", "아동", "학생", "어린이", "청소년", "참여자", "사람들", "웃는", "손을", "친구")


def photo_flags(captions: Dict[str, str]) -> int:
    """사진 설명에 사람이 보이는 단서가 있는 사진 수."""
    return sum(1 for c in (captions or {}).values() if any(w in (c or "") for w in PEOPLE_WORDS))


def required(campaign: dict) -> bool:
    """이 글은 발행 전에 동의 확인이 필요한가(현장 후기 + 사진이 있음)."""
    return campaign.get("post_type") == "review" and bool(campaign.get("storage_file_paths"))


def missing(campaign: dict) -> List[str]:
    """아직 확인하지 않은 항목 키."""
    if not required(campaign):
        return []
    done = set(campaign.get("consent") or [])
    return [k for k in KEYS if k not in done]


def label(key: str) -> str:
    return dict(ITEMS).get(key, key)
