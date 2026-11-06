"""카드뉴스·쇼츠 렌더러가 함께 쓰는 폰트 로더와 픽셀 기준 줄바꿈 유틸리티.

폰트 역할
- display_font : 타이틀·장면 핵심 문구·강조 단어·대형 숫자·카드 헤드라인 → Gmarket Sans Bold
- korean_font  : 하단 말자막·카드 본문·표 → Pretendard(번들에 있을 때) → 시스템 한글 폰트

모든 폰트는 먼저 assets/fonts(배포 번들 포함)에서 찾고, 없을 때만 시스템 폰트를 쓴다.
디스플레이 폰트에 없는 글자(예: ✔)가 들어간 문구는 본문 폰트로 자동 대체한다.
"""
import os
import contextvars
from functools import lru_cache
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
from cards.paths import FONTS_DIR, CUSTOM_FONTS_DIR

_HOME_FONTS = os.path.join(os.path.expanduser("~"), "Library", "Fonts")


def _first_existing(*paths: str) -> Optional[str]:
    return next((p for p in paths if p and os.path.exists(p)), None)


# 디스플레이 폰트 (Gmarket Sans Bold, SIL OFL 1.1 — assets/fonts/OFL-GmarketSans.txt)
DISPLAY_FONT_PATH = _first_existing(
    os.path.join(FONTS_DIR, "GmarketSansBold.otf"),
    os.path.join(_HOME_FONTS, "GmarketSansBold.otf"),
    "/Library/Fonts/GmarketSansBold.otf",
    "C:/Windows/Fonts/GmarketSansBold.otf",
)

# 본문/자막: 번들된 Pretendard(있으면) → 시스템 한글 폰트 → 번들된 Gmarket Sans Medium
_PRETENDARD = {w: os.path.join(FONTS_DIR, f"Pretendard-{n}.otf")
               for w, n in {"regular": "Regular", "medium": "Medium", "semibold": "SemiBold", "bold": "Bold"}.items()}

# (경로, {굵기: ttc 인덱스 또는 별도 파일 경로})
_FONT_CANDIDATES: List[Tuple[str, dict]] = [
    (_PRETENDARD["regular"], {w: p for w, p in _PRETENDARD.items()}),
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", {"regular": 0, "medium": 2, "semibold": 4, "bold": 6}),
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", {"regular": 0, "medium": 0,
                                                         "semibold": "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
                                                         "bold": "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"}),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", {"regular": 1, "medium": 1,
                                                                "semibold": "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                                                                "bold": "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"}),
    ("C:/Windows/Fonts/malgun.ttf", {"regular": 0, "medium": 0,
                                     "semibold": "C:/Windows/Fonts/malgunbd.ttf", "bold": "C:/Windows/Fonts/malgunbd.ttf"}),
    (os.path.join(FONTS_DIR, "GmarketSansMedium.otf"), {"regular": 0, "medium": 0,
                                                       "semibold": os.path.join(FONTS_DIR, "GmarketSansBold.otf"),
                                                       "bold": os.path.join(FONTS_DIR, "GmarketSansBold.otf")}),
    ("/System/Library/Fonts/Supplemental/AppleGothic.ttf", {"regular": 0, "medium": 0, "semibold": 0, "bold": 0}),
]


def find_korean_font_path() -> Optional[str]:
    for path, _ in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def korean_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """본문·자막용 한글 폰트 (카드 디자인 템플릿이 본문 글꼴을 정했으면 그것, 아니면 기본)"""
    size = _scaled(size, 1, weight)
    body = _ACTIVE.get()[1]
    if body:
        f = _family_font(body, size, weight)
        if f is not None:
            return f
    return _default_korean_font(size, weight)


@lru_cache(maxsize=128)
def _default_korean_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """기본 본문 글꼴(Pretendard → 시스템 한글 폰트)을 굵기별로 로드 (없으면 Pillow 기본 폰트)"""
    for path, weights in _FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        spec = weights.get(weight, 0)
        try:
            if isinstance(spec, str):
                if not os.path.exists(spec):
                    spec = weights.get("regular", 0)
                if isinstance(spec, str):
                    index = 1 if spec.endswith(".ttc") else 0
                    return ImageFont.truetype(spec, size, index=index)
            return ImageFont.truetype(path, size, index=spec)
        except Exception:
            continue
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=128)
def _display_font(size: int) -> Optional[ImageFont.FreeTypeFont]:
    if not DISPLAY_FONT_PATH:
        return None
    try:
        return ImageFont.truetype(DISPLAY_FONT_PATH, size)
    except Exception:
        return None


@lru_cache(maxsize=4096)
def _display_has(ch: str) -> bool:
    """디스플레이 폰트에 해당 글자가 있는지 (없는 글자는 '대체 상자'와 같은 모양으로 그려지는 것으로 판별)"""
    font = _display_font(48)
    if font is None or ch.isspace():
        return True

    def bitmap(c: str) -> bytes:
        im = Image.new("L", (72, 72), 0)
        ImageDraw.Draw(im).text((8, 4), c, font=font, fill=255)
        return im.tobytes()

    return bitmap(ch) != bitmap("\U000F0000")


# ----------------------------------------------------------------------
# 글꼴 목록 (디자인 템플릿에서 제목·본문 글꼴로 고를 수 있음)
#   files: {굵기: 파일 경로} — 없는 굵기는 가까운 굵기로 대체. 파일이 없는 글꼴은 목록에 나타나지 않는다.
#   assets/fonts/custom/ 폴더에 .otf/.ttf 파일을 넣으면 'custom:<파일명>' 글꼴로 자동 등록된다 (한 파일 = 한 굵기).
# ----------------------------------------------------------------------
_CUSTOM_DIR = CUSTOM_FONTS_DIR


_MANAGED_CUSTOM = {"NotoSansKR-VF.ttf", "NotoSerifKR-VF.ttf", "BlackHanSans-Regular.ttf", "DoHyeon-Regular.ttf", "Jua-Regular.ttf",
                   }


def _home(name: str) -> str:
    return os.path.join(_HOME_FONTS, name)


_BUILTIN_FAMILIES = {
    "pretendard": ("Pretendard (깔끔한 고딕 · 본문 기본)", {w: p for w, p in _PRETENDARD.items()}),
    "gmarket": ("Gmarket Sans (굵고 개성 있는 제목 · 제목 기본)", {
        "regular": os.path.join(FONTS_DIR, "GmarketSansMedium.otf"), "medium": os.path.join(FONTS_DIR, "GmarketSansMedium.otf"),
        "semibold": os.path.join(FONTS_DIR, "GmarketSansBold.otf"), "bold": os.path.join(FONTS_DIR, "GmarketSansBold.otf")}),
    "nanumhuman": ("나눔휴먼 (부드러운 고딕 · 이 PC에 설치된 글꼴)", {
        "regular": _home("NanumHumanRegular.otf"), "medium": _home("NanumHumanRegular.otf"),
        "semibold": _home("NanumHumanBold.otf"), "bold": _home("NanumHumanEB.otf")}),
    "applesd": ("Apple SD 산돌고딕 Neo (맥 시스템 글꼴)", {
        "regular": "/System/Library/Fonts/AppleSDGothicNeo.ttc#0", "medium": "/System/Library/Fonts/AppleSDGothicNeo.ttc#2",
        "semibold": "/System/Library/Fonts/AppleSDGothicNeo.ttc#4", "bold": "/System/Library/Fonts/AppleSDGothicNeo.ttc#6"}),
    # 아래는 assets/fonts/custom 에 내려받아 둔 오픈 폰트 (SIL OFL 1.1, assets/fonts/OFL-*.txt). '@숫자'는 가변 글꼴의 굵기 값
    "notosanskr": ("Noto Sans KR (가변 굵기 · 균형 잡힌 고딕)", {w: f"{_CUSTOM_DIR}/NotoSansKR-VF.ttf@{v}" for w, v in
                                                            (("regular", 400), ("medium", 500), ("semibold", 600), ("bold", 800))}),
    "notoserifkr": ("Noto Serif KR (가변 굵기 · 신뢰감 있는 명조)", {w: f"{_CUSTOM_DIR}/NotoSerifKR-VF.ttf@{v}" for w, v in
                                                              (("regular", 400), ("medium", 500), ("semibold", 600), ("bold", 800))}),
    "blackhansans": ("Black Han Sans (아주 굵은 제목용)", {w: f"{_CUSTOM_DIR}/BlackHanSans-Regular.ttf" for w in ("regular", "medium", "semibold", "bold")}),
    "dohyeon": ("Do Hyeon 도현 (또렷한 제목용)", {w: f"{_CUSTOM_DIR}/DoHyeon-Regular.ttf" for w in ("regular", "medium", "semibold", "bold")}),
    "jua": ("Jua 주아 (둥글고 귀여운 제목용)", {w: f"{_CUSTOM_DIR}/Jua-Regular.ttf" for w in ("regular", "medium", "semibold", "bold")}),
    # 고운바탕: SIL OFL 1.1(cards/fonts/OFL-GowunBatang.txt) — 앱에 동봉하는 세리프(명조) 제목 글꼴
    "gowunbatang": ("고운바탕 (따뜻한 바탕체 · 세리프 제목용)", {"regular": os.path.join(FONTS_DIR, "GowunBatang-Regular.ttf"),
                                                          "medium": os.path.join(FONTS_DIR, "GowunBatang-Regular.ttf"),
                                                          "semibold": os.path.join(FONTS_DIR, "GowunBatang-Bold.ttf"),
                                                          "bold": os.path.join(FONTS_DIR, "GowunBatang-Bold.ttf")}),
    "applemyungjo": ("Apple 명조 (맥 시스템 · 단정한 명조)", {w: "/System/Library/Fonts/Supplemental/AppleMyungjo.ttf"
                                                      for w in ("regular", "medium", "semibold", "bold")}),
}


def font_families() -> dict:
    """사용 가능한 글꼴 {id: (표시 이름, 굵기별 파일)} — 파일이 있는 것만"""
    out = {}
    for fid, (name, files) in _BUILTIN_FAMILIES.items():
        if os.path.exists(files["regular"].split("@")[0].split("#")[0]):
            out[fid] = (name, files)
    if os.path.isdir(_CUSTOM_DIR):
        for fn in sorted(os.listdir(_CUSTOM_DIR)):
            if fn.lower().endswith((".otf", ".ttf")) and fn not in _MANAGED_CUSTOM:
                path = os.path.join(_CUSTOM_DIR, fn)
                out[f"custom:{fn}"] = (f"{os.path.splitext(fn)[0]} (직접 넣은 글꼴)", {w: path for w in ("regular", "medium", "semibold", "bold")})
    return out


@lru_cache(maxsize=512)
def _family_font(fid: str, size: int, weight: str) -> Optional[ImageFont.FreeTypeFont]:
    fam = font_families().get(fid)
    if not fam:
        return None
    spec = fam[1].get(weight) or fam[1]["regular"]
    spec, _, wght = spec.partition("@")          # 가변 글꼴 굵기
    path, _, idx = spec.partition("#")
    if not os.path.exists(path):
        path, _, idx = fam[1]["regular"].partition("@")[0].partition("#")
    try:
        font = ImageFont.truetype(path, size, index=int(idx or 0))
        if wght:
            try:
                font.set_variation_by_axes([int(wght)])
            except Exception:
                pass
        return font
    except Exception:
        return None


@lru_cache(maxsize=4096)
def _family_has(fid: str, ch: str) -> bool:
    font = _family_font(fid, 48, "bold")
    if font is None or ch.isspace():
        return font is not None

    def bitmap(c: str) -> bytes:
        im = Image.new("L", (72, 72), 0)
        ImageDraw.Draw(im).text((8, 4), c, font=font, fill=255)
        return im.tobytes()

    return bitmap(ch) != bitmap("\U000F0000")


# 지금 그리는 카드의 제목·본문 글꼴 (카드 디자인 템플릿이 정함). 비어 있으면 기본 글꼴.
_ACTIVE = contextvars.ContextVar("osmu_fonts", default=("", ""))


def use_fonts(heading: str = "", body: str = ""):
    """현재 작업(스레드)에서 쓸 제목·본문 글꼴 지정 → reset_fonts(token)로 되돌림"""
    return _ACTIVE.set((heading or "", body or ""))


def reset_fonts(token) -> None:
    _ACTIVE.reset(token)


# 카드별 글자 크기 배율(말로 고치기): 제목(display_font)용·본문(korean_font)용. 3단 레이아웃은 자기 코드에서 직접 배율을
# 쓰므로 여기서는 쓰지 않고, 그 밖의 레이아웃(기본·일러스트·공공 안내…)이 이 값으로 글자를 키우고 줄인다.
_TEXT_SCALE = contextvars.ContextVar("osmu_text_scale", default=None)


def use_text_scale(title: float = 1.0, body: float = 1.0):
    if title == 1.0 and body == 1.0:
        return None
    return _TEXT_SCALE.set((title, body))


def reset_text_scale(token) -> None:
    if token is not None:
        _TEXT_SCALE.reset(token)


# 작은 글자(라벨·알약·머리말·연락처 줄)와 굵은 아이콘 글자는 키우지 않는다 — 큰 제목과 본문 글자만 배율을 받는다.
_TITLE_MIN, _BODY_MIN = 40, 26


# 휴대폰 가독성 보정: 카드(1080px)는 휴대폰에서 폭 약 360px(1/3)로 보이므로 21~26px 글자는 7~9px가 되어 읽기 어렵다.
# 작은 글자일수록 더 키우고 큰 글자는 거의 그대로 둔다(단조 증가 — 맞춤 반복문이 크기를 줄여 가며 찾는 방식과 어긋나지 않는다).
_LEGIBLE = contextvars.ContextVar("osmu_legible", default=False)
LEGIBLE_BOOST = 0.35        # 가장 작은 글자에 더해지는 최대 배율(+35%)
_LEGIBLE_FULL, _LEGIBLE_NONE = 20, 110     # 이 크기 이하는 최대 보정, 이 크기 이상은 보정 없음


def use_legible(on: bool = True):
    return _LEGIBLE.set(bool(on))


def reset_legible(token) -> None:
    _LEGIBLE.reset(token)


def legible_size(size: int) -> int:
    t = max(0.0, min(1.0, (_LEGIBLE_NONE - size) / (_LEGIBLE_NONE - _LEGIBLE_FULL)))
    return int(round(size * (1 + LEGIBLE_BOOST * t)))


def _scaled(size: int, which: int, weight: str = "") -> int:
    if _LEGIBLE.get():
        size = legible_size(size)
    s = _TEXT_SCALE.get()
    if not s or size < (_TITLE_MIN if which == 0 else _BODY_MIN) or (which == 1 and weight == "bold"):
        return size
    return max(8, int(round(size * s[which])))


# 선택한 글꼴에 없는 기호를 읽기 쉬운 비슷한 글자로 바꿈 (예: Jua·Black Han Sans에는 '·', '…'가 없음)
_SAFE_CHARS = {"·": "/", "ㆍ": "/", "・": "/", "•": "-", "∙": "-", "‧": "-", "…": "...", "’": "'", "‘": "'", "※": "*",
               "①": "1", "→": ">", "↓": "v", "✔": "v"}


def sanitize_text(text: str, heading: str = "", body: str = "") -> str:
    """제목·본문 글꼴에 없는 기호만 대체 (기본 글꼴이면 그대로)"""
    if not text or not (heading or body):
        return text
    out = []
    for ch in text:
        sub = _SAFE_CHARS.get(ch)
        if sub and any(fid and not _family_has(fid, ch) for fid in (heading, body)):
            out.append(sub)
        else:
            out.append(ch)
    return "".join(out)


def display_font(size: int, text: str = "") -> ImageFont.FreeTypeFont:
    """타이틀·강조용 Gmarket Sans Bold. 문구에 없는 글자가 있거나 폰트가 없으면 본문 굵은 폰트로 대체"""
    size = _scaled(size, 0)
    heading = _ACTIVE.get()[0]
    if heading:
        f = _family_font(heading, size, "bold")
        if f is not None and (not text or all(_family_has(heading, c) for c in set(text))):
            return f
    font = _display_font(size)
    if font is None or (text and not all(_display_has(c) for c in set(text))):
        return korean_font(size, "bold")
    return font


def wrap_text_px(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """실제 픽셀 폭 기준 줄바꿈 (단어 단위, 한 단어가 너무 길면 글자 단위로 분할)"""
    lines: List[str] = []
    for paragraph in (text or "").split("\n"):
        words = paragraph.split(" ")
        curr = ""
        for word in words:
            candidate = f"{curr} {word}" if curr else word
            if font.getlength(candidate) <= max_width:
                curr = candidate
                continue
            if curr:
                lines.append(curr)
            # 단어 자체가 한 줄보다 긴 경우 글자 단위로 분할
            curr = ""
            for ch in word:
                if font.getlength(curr + ch) <= max_width:
                    curr += ch
                else:
                    lines.append(curr)
                    curr = ch
        if curr:
            lines.append(curr)
    return lines


def wrap_text_balanced(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """제목용 균형 줄바꿈: 마지막 줄에 짧은 어절 하나만 떨어지지 않게 윗줄 끝 어절을 내림"""
    lines = wrap_text_px(text, font, max_width)
    for i in range(len(lines) - 1, 0, -1):
        prev = lines[i - 1].split(" ")
        if len(prev) < 2:
            continue
        if font.getlength(lines[i]) < font.getlength(lines[i - 1]) * 0.45:
            moved = f"{prev[-1]} {lines[i]}"
            if font.getlength(moved) <= max_width:
                lines[i - 1], lines[i] = " ".join(prev[:-1]), moved
    return lines


def text_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent
