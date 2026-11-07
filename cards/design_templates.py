"""카드 디자인 템플릿 — 카드를 어떤 모양으로 그릴지 정하는 규격.

레이아웃·모양 설정·그림 스타일 설명(글)·색 덮어쓰기를 담는다. 색은 기본적으로 브랜드 킷 색을 따른다.
- 내장 템플릿: classic(기본, 글 중심), illustrated(일러스트형: 제목 + 큰 그림 + 항목 박스)
- 사용자 템플릿: DATA_DIR/design_templates/<id>.json (다음 단계에서 '참조 이미지 → 디자인 안 → 저장'으로 만듦)
템플릿에는 업로드한 원본 이미지나 타인의 그림을 저장하지 않는다. 그림 스타일은 일반적인 설명(글)만 쓴다.
"""
import os
import re
import json
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from cards.paths import DATA_DIR

TEMPLATES_DIR = os.path.join(DATA_DIR, "design_templates")
DEFAULT_ID = "classic"

NO_TEXT_RULE = ("ABSOLUTELY NO TEXT of any kind in the image: no letters, words, numbers, signs, labels, captions, banners, logos or watermarks. "
                "Anything that normally carries writing (passports, tickets, maps, documents, screens, signboards) must be drawn blank or as abstract shapes only.")


class DesignTemplate(BaseModel):
    id: str
    name: str
    description: str = ""
    builtin: bool = False
    layout: str = Field(default="classic", description="classic | illustrated | color_block (꽉 찬 색 배경 + 줄 목록) | poster (포스터 표지 + 색 배경 목록) | typo (그림 없는 타이포그래피) | gov (공공 안내형)")
    radius: int = Field(default=28, description="그림·박스 모서리 둥글기(px)")
    box_style: str = Field(default="filled", description="항목 박스: filled(색 채움) | outlined(윤곽선)")
    show_numbers: bool = Field(default=True, description="항목 박스에 번호 원 표시")
    illustration_height: int = Field(default=440, description="본문 카드의 그림 영역 높이(px)")
    colors: Dict[str, str] = Field(default_factory=dict, description="브랜드 킷 색을 덮어쓸 값 (primary/secondary/accent/background), 비우면 브랜드 색")
    style_prompt: str = Field(default="", description="AI 그림을 만들 때 덧붙이는 스타일 설명 (글자·로고 없는 그림)")
    heading_font: str = Field(default="", description="제목 글꼴 ID (services/fonts.py font_families, 비우면 기본)")
    body_font: str = Field(default="", description="본문 글꼴 ID (비우면 기본)")
    image_aspect: str = Field(default="4:5", description="AI 그림 화면비 (그림 영역 모양에 맞춤: 일러스트형은 가로로 넓은 16:9)")
    ratio: List[int] = Field(default_factory=lambda: [2, 5, 3], description="tri(3단) 레이아웃의 위:가운데:아래 높이 비율")
    variant: str = Field(default="warm", description="oj(온자람 전용) 레이아웃의 변형: warm(공감·회복) | trust(전문·신뢰)")
    tri_theme: str = Field(default="light", description="tri 레이아웃 색: light(브랜드 밝은 배경) | dark(어두운 배경)")

    def uses_photo(self, slide_type: str) -> bool:
        """이 디자인에서 그 종류의 카드가 사진·그림을 쓰는지 (안 쓰는 카드는 AI 그림을 만들지 않아 비용을 아낌)"""
        if self.layout == "tri":   # 사진·영상 자리가 있는 모양: 인포그래픽 종류는 사진 없이 그린다
            return slide_type not in ("numbered", "steps", "checklist", "big_number", "comparison_table", "event_info")
        if self.layout == "oj":   # 온자람 전용: 표지·본문류만 사진 칸이 있고 나머지는 카드 안에서 그린다
            return slide_type in ("cover", "body", "single", "quote", "qa")
        if self.layout in ("typo", "gov"):
            return False   # AI 그림을 만들지 않음 (첨부 사진만 사용)
        if self.layout in ("color_block", "poster"):
            return slide_type == "cover"
        if self.layout == "illustrated":
            return slide_type in ("cover", "body", "numbered", "single", "call_to_action")
        return slide_type not in ("comparison_table", "big_number", "event_info")

    def image_suffix(self) -> str:
        return f"{self.style_prompt.strip()} {NO_TEXT_RULE}".strip() if self.style_prompt.strip() else ""


BUILTINS: List[DesignTemplate] = [
    DesignTemplate(id="onjaram-warm", name="온자람 · 공감·회복 (세이지 + 크림, 세리프 제목)", builtin=True, layout="oj", variant="warm", radius=32,
                   heading_font="gowunbatang", ratio=[2, 5, 3],
                   description="브랜드 킷 문서의 비주얼 규칙을 옮긴 개인 상담·청년·학부모용 모양. 크림 바탕에 세이지 그린, 핵심어만 코랄로 강조하고 "
                               "위 카테고리 태그·아래 워터마크·연락처를 모든 카드에 고정합니다. 마지막 카드는 전화번호를 크게 보여 줍니다.",
                   colors={"primary": "#35593F", "secondary": "#4A7C59", "accent": "#E07A5F", "background": "#FAF8F5"}),
    DesignTemplate(id="onjaram-trust", name="온자람 · 전문·신뢰 (네이비 + 크림, 번호 칸·인증 배지)", builtin=True, layout="oj", variant="trust", radius=14,
                   description="기업 EAP·학교·관공서 대상의 단정한 모양. 딥 네이비 주조색, 번호 칸과 각진 상자, 사회적기업 인증 배지를 보여 줍니다.",
                   colors={"primary": "#2C4A6F", "secondary": "#2C4A6F", "accent": "#E07A5F", "background": "#FAF8F5"}),
    DesignTemplate(id="tri-2-5-3", name="3단 (위 제목 · 가운데 사진/인포그래픽 · 아래 소속) 2:5:3", builtin=True, layout="tri",
                   ratio=[2, 5, 3], radius=32,
                   description="위에 제목, 가운데에 사진·영상 또는 번호 단계 인포그래픽, 아래에 한 줄 요약과 소속·연락처. "
                               "병원·기관 카드뉴스에서 흔한 구성이며 카드와 쇼츠가 같은 모양을 씁니다. 사진이 없으면 AI 호출 없이 인포그래픽으로 그립니다."),
    DesignTemplate(id="tri-1-1-1", name="3단 균등 1:1:1", builtin=True, layout="tri", ratio=[1, 1, 1], radius=32,
                   description="세 영역을 같은 높이로 나눈 3단 구성."),
    DesignTemplate(id="tri-dark-2-5-3", name="3단 어두운 배경 2:5:3", builtin=True, layout="tri", ratio=[2, 5, 3], tri_theme="dark",
                   radius=32, description="어두운 배경에 흰 제목·강조색 포인트. 영상·사진이 돋보입니다."),
    DesignTemplate(id="classic", name="기본 (글 중심)", builtin=True, layout="classic",
                   description="제목과 글을 또렷하게 보여 주는 기본 모양. 사진이 있으면 위쪽에 넣습니다."),
    DesignTemplate(id="gov", name="공공 안내형 (연한 남색 + 흰 패널 + 줄 목록)", builtin=True, layout="gov", radius=40,
                   description="공공기관 안내 카드뉴스에서 흔한 구성: 연한 남색 바탕에 흰 패널, 번호·소제목 알약, 핵심어만 초록 강조 제목, "
                               "라벨 칸·화살표(이전 → 이후)·체크·날짜 알약 줄 목록, 남색 결론 띠. 제도·지원사업·법령 안내에 어울립니다. AI 그림 0원(첨부 사진은 표지에 사용).",
                   colors={"primary": "#2C4A6F", "secondary": "#4A7C59", "accent": "#E07A5F", "background": "#E6ECF4"},
                   heading_font="", body_font=""),
    DesignTemplate(id="typo", name="타이포그래피형 (큰 글씨 + 형광펜, 그림 없음)", builtin=True, layout="typo",
                   description="AI 그림 없이 큰 제목, 형광펜 강조, 넉넉한 여백으로 전달합니다(AI 그림 비용 0원). 사진을 첨부하면 그 카드는 사진을 배경으로 깔고 흰 글씨로 그립니다. 제목에서 *강조어*처럼 별표로 감싼 말이 형광펜으로 칠해집니다."),
    DesignTemplate(id="color_block", name="색 배경 일정표형 (꽉 찬 색 + 줄 목록)", builtin=True, layout="color_block", radius=36, image_aspect="16:9",
                   description="위쪽 밝은 제목 영역 아래를 꽉 찬 색 면으로 채우고 줄 목록으로 정리하는 모양. 일정·행사 안내에 어울립니다. 표지만 그림을 씁니다.",
                   colors={"secondary": "#4A7C59", "accent": "#F0ECE1", "primary": "#35593F", "background": "#FAF8F5"},
                   style_prompt="Soft flat vector landscape illustration, palette of sage green, deep navy, coral accents on warm cream, simple rounded shapes, calm and safe mood."),
    DesignTemplate(id="poster", name="포스터 표지형 (큰 제목 표지 + 색 배경 목록)", builtin=True, layout="poster", radius=36, image_aspect="4:5",
                   description="표지는 큰 제목과 아래쪽을 가득 채운 그림, 나머지 카드는 색 배경 목록으로 구성합니다. 행사·일정 안내에 어울립니다.",
                   colors={"secondary": "#4A7C59", "accent": "#F0ECE1", "primary": "#35593F", "background": "#FAF8F5"},
                   style_prompt="Soft flat vector landscape illustration, palette of sage green, deep navy, coral accents on warm cream, simple rounded shapes, calm and safe mood."),
    DesignTemplate(id="illustrated", name="일러스트형 (그림 + 항목 박스)", builtin=True, layout="illustrated", radius=36, image_aspect="16:9",
                   box_style="filled", show_numbers=True, illustration_height=440,
                   description="제목 아래 큰 그림, 그 아래 항목을 둥근 박스로 정리하는 친근한 모양. 사진이 없는 카드는 AI 일러스트로 채웁니다.",
                   style_prompt="Friendly flat vector illustration, soft pastel colors, simple rounded shapes, clean composition with plenty of "
                                "empty space, cheerful and approachable mood, editorial infographic style."),
]


def _path(template_id: str) -> str:
    return os.path.join(TEMPLATES_DIR, f"{template_id}.json")


def list_all() -> List[DesignTemplate]:
    out = list(BUILTINS)
    if os.path.isdir(TEMPLATES_DIR):
        for name in sorted(os.listdir(TEMPLATES_DIR)):
            if name.endswith(".json"):
                try:
                    with open(os.path.join(TEMPLATES_DIR, name), encoding="utf-8") as f:
                        t = DesignTemplate.model_validate(json.load(f))
                    t.builtin = False
                    out.append(t)
                except Exception:
                    continue
    return out


# 온자람 브랜드 컬러(core/brand_seed.BRAND_COLORS: 세이지 #4A7C59 · 네이비 #2C4A6F · 코랄 #E07A5F · 오트 #F0ECE1 · 크림 #FAF8F5)로
# 짠 배색. 어떤 디자인에든 "디자인id@배색id"로 입혀서 같은 모양을 브랜드 색 안에서 다르게 보여 줍니다.
# (진한 계열 #35593F·#26372C·#1C2F47·#1F2F40 은 브랜드 색을 어둡게 한 파생색 — 문서에 없는 값이니 필요하면 조정)
# dark_bg는 3단 어두운 배경 디자인의 바탕색입니다.
BRAND_PALETTES: Dict[str, dict] = {
    "sage": {"name": "세이지 그린 (자람·회복)", "colors": {
        "primary": "#35593F", "secondary": "#4A7C59", "accent": "#E07A5F", "background": "#FAF8F5", "dark_bg": "#26372C"}},
    "navy": {"name": "트러스트 네이비 (전문·신뢰)", "colors": {
        "primary": "#2C4A6F", "secondary": "#2C4A6F", "accent": "#E07A5F", "background": "#FAF8F5", "dark_bg": "#1C2F47"}},
    "coral": {"name": "코랄 포인트 (따뜻한 온기)", "colors": {
        "primary": "#2B2D2F", "secondary": "#E07A5F", "accent": "#4A7C59", "background": "#FAF8F5", "dark_bg": "#2B2D2F"}},
    "oat": {"name": "소프트 오트 (차분한 바탕)", "colors": {
        "primary": "#35593F", "secondary": "#2C4A6F", "accent": "#E07A5F", "background": "#F0ECE1", "dark_bg": "#26372C"}},
    "duo": {"name": "네이비 + 세이지 투톤", "colors": {
        "primary": "#2C4A6F", "secondary": "#4A7C59", "accent": "#E07A5F", "background": "#FAF8F5", "dark_bg": "#1F2F40"}},
}


def with_palette(design_id: Optional[str], palette_id: Optional[str]) -> str:
    """디자인 id에 배색을 붙인 id. 배색이 없거나 모르는 것이면 디자인 id 그대로(브랜드 킷 색)."""
    base = (design_id or DEFAULT_ID).partition("@")[0]
    return f"{base}@{palette_id}" if palette_id in BRAND_PALETTES else base


def split_id(design_id: Optional[str]):
    """"디자인@배색" → (디자인 id, 배색 id 또는 '')."""
    base, _, pal = (design_id or "").partition("@")
    return base, (pal if pal in BRAND_PALETTES else "")


def get(template_id: Optional[str]) -> DesignTemplate:
    """없는 ID(삭제된 템플릿 등)는 기본 템플릿으로. "디자인@배색"이면 그 디자인에 브랜드 배색을 입힌다."""
    base_id, pal = split_id(template_id or DEFAULT_ID)
    found = next((t for t in list_all() if t.id == (base_id or DEFAULT_ID)), BUILTINS[0])
    if not pal:
        return found
    return found.model_copy(update={"id": f"{found.id}@{pal}", "colors": dict(BRAND_PALETTES[pal]["colors"])})


def save(t: DesignTemplate) -> None:
    if not re.fullmatch(r"[a-z0-9_\-]{2,40}", t.id) or any(b.id == t.id for b in BUILTINS):
        raise ValueError("템플릿 ID는 영문 소문자·숫자·-·_ 2~40자이고, 내장 템플릿과 같을 수 없습니다.")
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    with open(_path(t.id), "w", encoding="utf-8") as f:
        json.dump(t.model_dump(exclude={"builtin"}), f, ensure_ascii=False, indent=2)


def unique_id(base: str = "my-design") -> str:
    """겹치지 않는 새 템플릿 ID (영문 소문자·숫자·-)"""
    base = re.sub(r"[^a-z0-9_\-]", "", (base or "").lower())[:30] or "my-design"
    existing = {t.id for t in list_all()}
    n, cand = 1, base
    while cand in existing or len(cand) < 2:
        n += 1
        cand = f"{base}-{n}"
    return cand


# 분위기별 자동 추천 (글꼴 쌍 + 모양 + 색). 글꼴·색 고르기가 어려운 사용자를 위한 출발점이며, 적용 뒤 직접 고칠 수 있다.
MOODS = {
    "friendly": {"label": "친근하고 따뜻한", "heading": "jua", "body": "nanumhuman", "radius": 36, "box": "filled",
                 "colors": {"primary": "#5C3A21", "secondary": "#F29B38", "accent": "#FFD27A", "background": "#FFF6E8"}},
    "clean": {"label": "단정하고 믿음직한", "heading": "notosanskr", "body": "pretendard", "radius": 12, "box": "outlined",
              "colors": {"primary": "#1F3A5F", "secondary": "#3E6FA8", "accent": "#F2B84B", "background": "#F4F7FB"}},
    "bold": {"label": "강렬하고 눈에 띄는", "heading": "blackhansans", "body": "pretendard", "radius": 8, "box": "filled",
             "colors": {"primary": "#7A1F1F", "secondary": "#D8432E", "accent": "#FFC83D", "background": "#FFF5EC"}},
    "elegant": {"label": "차분하고 고급스러운", "heading": "notoserifkr", "body": "gowunbatang", "radius": 4, "box": "outlined",
                "colors": {"primary": "#2B2A33", "secondary": "#8A6F47", "accent": "#C9A66B", "background": "#F7F3EC"}},
    "natural": {"label": "편안한 자연 느낌", "heading": "gowunbatang", "body": "nanumhuman", "radius": 24, "box": "filled",
                "colors": {"primary": "#234B3F", "secondary": "#4F8A6B", "accent": "#E8B04B", "background": "#F3F7F1"}},
}


# 브랜드 색을 쓰지 않을 때 고르는 추천 배색 (모두 흰 글씨가 읽히는 진한 주 색 + 밝은 바탕)
PALETTES = [
    {"primary": "#1E3A8A", "secondary": "#2563EB", "accent": "#FFB800", "background": "#F4F7FC"},
    {"primary": "#5C2E14", "secondary": "#E8772E", "accent": "#FFD27A", "background": "#FFF6EC"},
    {"primary": "#234B3F", "secondary": "#4F8A6B", "accent": "#F4B942", "background": "#F4F8F5"},
    {"primary": "#483880", "secondary": "#A02840", "accent": "#E09038", "background": "#F8F7FC"},
    {"primary": "#1E293B", "secondary": "#0D9488", "accent": "#F59E0B", "background": "#F8FAFC"},
    {"primary": "#7A1F1F", "secondary": "#D8432E", "accent": "#FFC83D", "background": "#FFF5EC"},
]
LAYOUT_NAMES = {"classic": "기본", "illustrated": "일러스트형", "color_block": "색 배경 일정표형", "poster": "포스터 표지형",
                "typo": "타이포그래피형", "gov": "공공 안내형"}


def style_variants(n: int = 3, keep_brand_colors: bool = True, has_photos: bool = False, avoid_layout: str = "",
                   seed: Optional[int] = None) -> List[DesignTemplate]:
    """'스타일 바꿔 보기': 내장 레이아웃 × 분위기(글꼴 쌍·모양) × 배색을 섞어 서로 다른 스타일 n개 (AI 호출 없음).
    그림이 꼭 필요한 레이아웃(포스터·일러스트)은 사진이 있을 때만 후보에 넣는다."""
    import random
    from cards import fonts
    rng = random.Random(seed)
    pool = ["typo", "gov", "color_block", "classic"] + (["poster", "illustrated"] if has_photos else [])
    rng.shuffle(pool)
    pool.sort(key=lambda l: l == avoid_layout)          # 지금 쓰는 레이아웃은 뒤로
    moods = list(MOODS.values())
    rng.shuffle(moods)
    avail = fonts.font_families()
    out = []
    for i, layout in enumerate(pool[:n]):
        m = moods[i % len(moods)]
        base = get(layout)
        colors = {} if keep_brand_colors else dict(rng.choice([m["colors"], *PALETTES]))
        out.append(base.model_copy(update={
            "id": f"style-preview-{i + 1}", "builtin": False,
            "name": f"{LAYOUT_NAMES.get(layout, layout)} · {m['label']}",
            "description": "스타일 바꿔 보기로 만든 조합",
            "heading_font": m["heading"] if m["heading"] in avail else "",
            "body_font": m["body"] if m["body"] in avail else "",
            "radius": base.radius if layout == "gov" else m["radius"],
            "box_style": m["box"],
            "colors": colors,
        }))
    return out


def delete(template_id: str) -> None:
    if any(b.id == template_id for b in BUILTINS):
        raise ValueError("내장 템플릿은 지울 수 없습니다.")
    try:
        os.remove(_path(template_id))
    except OSError:
        pass
