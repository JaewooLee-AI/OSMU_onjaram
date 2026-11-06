"""DB의 브랜드 킷(core.repo)을 카드 렌더러가 쓰는 BrandKit으로 바꿉니다.

렌더러가 쓰는 값은 색·연락처·한 줄 소개·로고 정도라서, 킷의 다른 값(페르소나·팩트 등)은 기획 단계(cards.director)가
repo에서 직접 읽습니다. 색은 문서 §3 토큰(core.brand_seed.BRAND_COLORS)이며 보이스 트랙에 따라 주조색이 바뀝니다:
공감·회복(B2C)은 세이지 그린, 전문·신뢰(B2B·B2G)는 트러스트 네이비.
"""
from __future__ import annotations

import os
import re
from typing import List, Optional

from pydantic import BaseModel, Field

from cards.paths import BRAND_ASSETS_DIR
from core import repo
from core.brand_seed import BRAND_COLORS, SLOGAN_SUB


class BrandColors(BaseModel):
    primary: str = "#4A7C59"      # 헤더·헤드라인·요약 바
    secondary: str = "#2C4A6F"    # 강조 정보(연락처·수치)
    accent: str = "#E07A5F"       # 라벨·형광펜
    background: str = "#FAF8F5"   # 카드 바탕


class BrandKit(BaseModel):
    id: str = ""
    brand_name: str = ""
    tagline: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    homepage: str = ""
    sns_handle: str = ""
    footer_text: str = Field(default="", description="카드 하단 왼쪽 문구 (비우면 홈페이지 주소)")
    colors: BrandColors = Field(default_factory=BrandColors)
    logo_file: str = ""
    value_headline: str = ""
    cta_headline: str = ""
    core_facts: List[str] = Field(default_factory=list)

    @property
    def logo_path(self) -> Optional[str]:
        if not self.logo_file:
            return None
        path = os.path.join(BRAND_ASSETS_DIR, self.logo_file)
        return path if os.path.exists(path) else None

    @property
    def homepage_short(self) -> str:
        return re.sub(r"^https?://(www\.)?", "", self.homepage or "").rstrip("/")

    @property
    def contact_line(self) -> str:
        parts = [f"상담 {self.phone}" if self.phone else "", self.email, self.homepage_short]
        return "  |  ".join(p for p in parts if p)


def _is_professional_track(kit_name: str) -> bool:
    return any(token in (kit_name or "") for token in ("B2B", "B2G", "전문"))


def from_db(kit_id: Optional[int] = None) -> BrandKit:
    """kit_id 킷(None이면 기본 킷)의 값으로 BrandKit을 만듭니다."""
    kit = repo.get_brand_kit(kit_id)
    pro = _is_professional_track(kit.get("name", ""))
    green, navy = BRAND_COLORS["primary"], BRAND_COLORS["secondary"]
    colors = BrandColors(
        primary=navy if pro else green,
        secondary=green if pro else navy,
        accent=BRAND_COLORS["accent"],
        background=BRAND_COLORS["bg"],
    )
    handle = (kit.get("instagram_handle") or "").strip().lstrip("@")
    return BrandKit(
        id=str(kit.get("id") or ""),
        brand_name=kit.get("brand_name") or "",
        tagline=SLOGAN_SUB,
        phone=kit.get("phone") or "",
        email=kit.get("email") or "",
        address=kit.get("address") or "",
        homepage=kit.get("homepage") or "",
        sns_handle=f"@{handle}" if handle else "",
        footer_text=kit.get("sub_brand") or "",
        colors=colors,
        core_facts=list(kit.get("core_facts") or []),
    )


def load_kit(brand_id) -> BrandKit:
    """렌더러 호환 이름 — 스토리보드의 brand_id(킷 ID 문자열)로 불러옵니다."""
    try:
        return from_db(int(brand_id))
    except (TypeError, ValueError):
        return from_db(None)


def active_kit() -> BrandKit:
    return from_db(None)
