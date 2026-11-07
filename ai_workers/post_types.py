"""글 유형 — 온자람 네이버 블로그(blog.naver.com/onjaram)의 실제 글 구조에서 뽑은 3가지 틀.

공개 RSS 50개 글을 분석하니 글은 크게 세 종류였습니다(기관 활동 후기 약 60%, 심리교육 칼럼 약 25%, 모집·안내).
세 종류 모두 고정 인사로 시작하고, 번호 소제목으로 나뉘고, 문의 전화·주소 푸터로 끝났습니다.
이 모듈은 그 틀을 (1) 초안 프롬프트의 구조 지시, (2) 제목 지시, (3) 발행 전 푸터 자동 삽입으로 옮깁니다.

글 유형은 글마다 고르는 선택값입니다(`campaigns.post_type`). 비워 두면 예전처럼 구조를 지정하지 않고,
푸터도 붙이지 않습니다 — 기존 글·기존 동작을 바꾸지 않으려는 것입니다.
전화·주소는 브랜드 킷 값만 씁니다(지어내지 않음). 킷에 없으면 그 줄은 빼고, 둘 다 없으면 푸터를 붙이지 않습니다.
"""
from __future__ import annotations

from typing import Dict, List

AUTO = ""

TYPES: Dict[str, dict] = {
    "review": {
        "label": "📸 현장 후기",
        "caption": "강의·캠프·부스·집단상담 등 활동 후기. 인사 → 개요 → 번호 소제목 3~4개 → 응원 맺음.",
        "title_hint": "제목은 `[온자람 현장]` 또는 `[출강 후기]` 같은 대괄호 말머리로 시작하고, 프로그램 이름과 지역·서비스 키워드(예: 창원 심리상담) 하나를 담으세요.",
        "structure": (
            "이 글은 '현장 후기'입니다. 다음 틀로 쓰세요.\n"
            "1) 첫 문장은 인사: '{greeting}'\n"
            "2) 이어서 한 문단으로 개요(무엇을·누구와·어떤 자리였는지)를 씁니다. 날짜·기관명·인원은 메모에 있는 것만 씁니다.\n"
            "3) 본문은 '1. 소제목', '2. 소제목'처럼 번호를 붙인 소제목 3~4개로 나눕니다. 흐름은 현장 장면 → 참여자의 반응·소감 → 프로그램이 전하려던 의미 순서입니다.\n"
            "4) 마지막은 참여자와 함께해 주신 분들에 대한 감사와 응원 한두 문장으로 맺습니다. 연락처·주소는 쓰지 마세요(글 끝에 자동으로 붙습니다)."
        ),
    },
    "column": {
        "label": "📝 칼럼·마음 이야기",
        "caption": "보편 심리교육 칼럼. 인사 → 공감 서론 → 번호 소제목 3개 → 작은 실천 → 맺음.",
        "title_hint": "제목은 독자의 마음 고민을 담은 문장에 지역·서비스 키워드(예: 창원 심리상담) 하나를 넣고, 대괄호 말머리는 `[창원 심리상담]`처럼 키워드로 쓰세요.",
        "structure": (
            "이 글은 '칼럼'입니다. 다음 틀로 쓰세요.\n"
            "1) 첫 문장은 인사: '{greeting}'\n"
            "2) 독자가 일상에서 겪는 마음 고충에 공감하는 서론으로 시작하고, 그 감정이 이상한 것이 아님을 알려 줍니다.\n"
            "3) 본문은 번호 소제목 3개로 나눕니다: 왜 그럴 수 있는지 → 마음을 살피는 방법 → 오늘 해 볼 작은 실천.\n"
            "4) 상담 안내는 주제와 이어질 때만 마지막에 한 문장으로 부드럽게. 개별 내담자 사례(나이·시기·상황)는 쓰지 마세요."
        ),
    },
    "notice": {
        "label": "📣 모집·안내",
        "caption": "프로그램 모집·제도·운영 안내. 요약 → 일시·대상·비용·신청 → 문의.",
        "title_hint": "제목은 `[모집]`, `[안내]` 같은 말머리로 시작하고, 대상과 핵심 내용(무엇을 모집·안내하는지)이 한눈에 보이게 쓰세요.",
        "structure": (
            "이 글은 '모집·안내'입니다. 다음 틀로 쓰세요.\n"
            "1) 첫 문장은 인사: '{greeting}'\n"
            "2) 무엇을 안내하는지 한두 문장으로 먼저 요약합니다.\n"
            "3) 일시·장소·대상·비용·신청 방법처럼 독자가 알아야 할 사실을 번호 소제목이나 항목으로 정리합니다. "
            "메모·공지 정보에 없는 사실은 쓰지 말고 비워 둡니다.\n"
            "4) 마지막은 신청·문의를 부드럽게 권하는 한 문장으로 맺습니다."
        ),
    },
}

ORDER: List[str] = list(TYPES)

# 모든 유형에 공통으로 붙는 안전 규칙 — 후기·칼럼에는 참여자 소감·프로그램 이름이 자주 나오기 때문입니다.
SAFETY = (
    "[글쓰기 안전 규칙]\n"
    "- 참여자·아동·내담자의 소감을 인용할 때는 메모나 사진 설명에 있는 것만 쓰고, 누구인지 알 수 있는 나이·학교·개인 사정은 쓰지 마세요. "
    "소감은 '마음이 가벼워졌어요'처럼 느낌으로만 쓰고, '효과가 있어요', '나았어요', '치료됐어요'처럼 효과를 단정하는 말은 쓰지 마세요.\n"
    "- 프로그램 이름에 '약국', '처방', '약' 같은 말이 있어도 이름일 뿐입니다. 실제 약·진단·처방·치료 효과를 말하지 마세요.\n"
    "- 기관명·학교명은 메모에 있을 때만 쓰고, 사진 속 사람의 얼굴·이름을 묘사하지 마세요."
)


def normalize(key: str | None) -> str:
    return key if key in TYPES else AUTO


def label_of(key: str | None) -> str:
    return TYPES[key]["label"] if key in TYPES else "자동 (구조를 정하지 않음)"


def greeting(brand_kit: dict | None, key: str) -> str:
    name = ((brand_kit or {}).get("brand_name") or "").strip() or "온자람"
    if key == "review":
        return f"안녕하세요, 온전한 나를 찾아가는 여정에 늘 함께하는 마음성장파트너 {name}입니다."
    return f"안녕하세요, 마음성장파트너 {name}입니다."


def structure_block(key: str | None, brand_kit: dict | None = None) -> List[str]:
    """초안 시스템 프롬프트에 붙일 구조 지시. 유형이 없으면 빈 목록."""
    key = normalize(key)
    if not key:
        return []
    return [TYPES[key]["structure"].format(greeting=greeting(brand_kit, key)), SAFETY]


def title_hint(key: str | None) -> str:
    key = normalize(key)
    return TYPES[key]["title_hint"] if key else ""


def footer_text(brand_kit: dict | None) -> str:
    """문의 푸터. 킷의 전화·주소만 씁니다(둘 다 없으면 빈 문자열)."""
    kit = brand_kit or {}
    lines = []
    if (kit.get("phone") or "").strip():
        lines.append(f"전화: {kit['phone'].strip()}")
    if (kit.get("address") or "").strip():
        lines.append(f"위치: {kit['address'].strip()}")
    if not lines:
        return ""
    return "📞 상담 및 프로그램 문의\n" + "\n".join(lines)


def apply_footer(content: str, brand_kit: dict | None, key: str | None) -> str:
    """글 유형이 있으면 본문 끝에 문의 푸터를 붙입니다. 이미 전화번호가 끝부분에 있으면 다시 붙이지 않습니다."""
    if not normalize(key):
        return content
    footer = footer_text(brand_kit)
    if not footer:
        return content
    phone = ((brand_kit or {}).get("phone") or "").strip()
    if phone and phone in (content or "")[-400:]:
        return content
    return f"{(content or '').rstrip()}\n\n{footer}"
