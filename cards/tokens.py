"""디자인 토큰 — 에디토리얼·리포트 카드와 쇼츠 전용 화면이 함께 쓰는 색·문구·글자 크기·간격을 한곳에 둡니다.

레이아웃 코드(cards/layout_editorial.py · layout_report.py · shorts_ed.py)는 색상 코드나 머리말 문구를 직접 쓰지 않고
여기 이름을 씁니다. 값의 출처는 두 단계입니다.

1. 이 파일의 기본값 — 특정 고객사와 무관한 중립 값.
2. `core/brand_seed.CARD_TOKENS` — 고객사별 값(색·머리말 문구). 있으면 기본값을 덮어씁니다.

그래서 다른 고객사용으로 바꿀 때는 레이아웃 코드를 고치지 않고 `core/brand_seed.py`만 바꾸면 됩니다.
브랜드 주조색(primary·secondary·accent·background)은 여기가 아니라 브랜드 킷·디자인 템플릿 색(`ctx.c`)에서 옵니다.
여기 색은 그 위에 얹는 고정 색(어두운 바탕, 밝은 글자, 대체 포인트 색)입니다.
"""
from __future__ import annotations

from typing import Dict

try:
    from core import brand_seed as _seed
    _BRAND: dict = dict(getattr(_seed, "CARD_TOKENS", {}) or {})
except Exception:   # 브랜드 시드를 읽지 못해도 카드는 기본값으로 그린다
    _BRAND = {}

_COLORS: Dict[str, str] = {
    "navy": "#111A2E",          # 어두운 바탕·진한 띠
    "navy_deep": "#0B1221",     # 더 어두운 바탕(표지 그라데이션, 어두운 디자인의 띠)
    "navy_chip": "#1E2B45",     # 어두운 띠 위의 작은 칸
    "navy_soft": "#1F2D4A",     # 어두운 바탕의 번호 칸
    "gold": "#B8860B",          # 포인트 색(브랜드 색을 못 읽을 때의 대체 값이기도 함)
    "gold_light": "#D4AF37",    # 어두운 바탕 위 포인트 색
    "ivory": "#FAF8F4",         # 어두운 바탕 위 글자
    "ivory_text": "#EBE7DF",    # 어두운 바탕 위 본문
    "ivory_dim": "#D9D5CC",     # 어두운 바탕 위 보조 글자
    "sand_mix": "#C8BEA8",      # 밝은 바탕에 섞어 목록 칸 색을 만드는 값
    "charcoal": "#22252A",      # 밝은 바탕 본문에 섞는 값
    "white": "#FFFFFF",
    "black": "#000000",
}
_COLORS.update({k: v for k, v in (_BRAND.get("colors") or {}).items() if k in _COLORS})

NAVY, NAVY_DEEP, NAVY_CHIP, NAVY_SOFT = _COLORS["navy"], _COLORS["navy_deep"], _COLORS["navy_chip"], _COLORS["navy_soft"]
GOLD, GOLD_LIGHT = _COLORS["gold"], _COLORS["gold_light"]
IVORY, IVORY_TEXT, IVORY_DIM = _COLORS["ivory"], _COLORS["ivory_text"], _COLORS["ivory_dim"]
SAND_MIX, CHARCOAL, WHITE, BLACK = _COLORS["sand_mix"], _COLORS["charcoal"], _COLORS["white"], _COLORS["black"]

# 카드 종류별 머리말(왼쪽 위 배지) — 고객사 값이 없으면 중립 문구
_KICKERS: Dict[str, str] = {
    "cover": "BRIEF", "body": "리포트", "single": "핵심 요약", "checklist": "체크", "steps": "단계별 가이드",
    "numbered": "체크 포인트", "howto": "실전 가이드", "qa": "Q&A", "big_number": "핵심 지표",
    "event_info": "안내", "comparison_table": "한눈에 비교", "call_to_action": "상담 안내", "quote": "핵심 요약",
}
_KICKERS.update(_BRAND.get("kickers") or {})
KICKERS = _KICKERS

_COPY: Dict[str, str] = {
    "cover_label": "REPORT",          # 리포트 표지 제목 위 작은 문구(시리즈 이름이 없을 때)
    "band_tag": "BRIEFING",           # 리포트 위 띠의 칩
    "band_tag_shorts": "REPORT",      # 쇼츠에서 위 띠의 칩
    "shorts_badge": "브리핑",          # 에디토리얼 쇼츠 표지 머리줄 배지
    "qr_caption": "QR을 스캔하면 바로 상담 안내로 연결됩니다",
    "cta_tag": "상담 문의",            # 상담 안내 카드의 큰 전화번호 칸 머리말
    "next": "NEXT >",
    "phone_prefix": "문의",
    "phone_prefix_report": "직통",
}
_COPY.update({k: v for k, v in (_BRAND.get("copy") or {}).items() if k in _COPY})
COPY = _COPY

# 글자 크기(1080px 폭 기준 시작 크기 — 자리가 모자라면 그리는 쪽에서 줄인다)
TYPE: Dict[str, int] = {
    "cover_title": 104,          # 표지 전용 화면 제목
    "title": 60,                 # 에디토리얼 카드 제목
    "title_shorts": 72,          # 에디토리얼 쇼츠 장면 제목
    "title_report": 58,          # 리포트 카드 제목
    "title_report_shorts": 70,   # 리포트 쇼츠 장면 제목
    "shorts_cover_title": 88,    # 쇼츠 표지(사진 칸 아래) 제목
    "phone": 124,                # 상담 안내 전화번호
    "caption": 60,               # 쇼츠 자막(최대)
    "caption_min": 38,
}

# 간격·영역(px)
SPACE: Dict[str, int] = {
    "pad": 72,                   # 에디토리얼 좌우 여백
    "pad_report": 80,            # 리포트 좌우 여백
    "band_report": 112,          # 리포트 위 띠 높이
    "shorts_safe_top": 120,      # 쇼츠 위 UI 가림 영역
    "shorts_safe_bottom": 240,   # 쇼츠 아래 UI 가림 영역
    "caption_h": 250,            # 쇼츠 자막 띠 높이
}
