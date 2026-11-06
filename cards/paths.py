"""카드 엔진의 경로. 읽기 전용 글꼴은 패키지 안(cards/fonts), 쓰기 가능한 것은 앱 데이터 폴더(core.db.DATA_DIR) —
설치 폴더(Program Files)에는 쓰지 않습니다."""
from __future__ import annotations

import os

from core.db import DATA_DIR as _DATA_DIR

CARDS_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(CARDS_DIR, "fonts")

DATA_DIR = str(_DATA_DIR)
EXPORTS_DIR = os.path.join(DATA_DIR, "exports")
CUSTOM_FONTS_DIR = os.path.join(DATA_DIR, "fonts", "custom")
BRAND_ASSETS_DIR = os.path.join(DATA_DIR, "brand")
