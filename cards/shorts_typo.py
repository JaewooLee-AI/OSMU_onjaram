"""쇼츠 '글자 중심' 모양(typo) — 말은 말대로, 화면은 카드 내용을 충실하게.

자막을 음성에 맞추지 않습니다. 장면마다 카드의 제목·요약·본문·항목을 처음부터 화면에 담고, 장면 시작 약 1~2초 동안만
글자가 움직인 뒤(낱말 차례로 떠오르기, 강조어 형광펜, 내용 줄 차례로, 큰 숫자 올라가기) 멈춰서 읽게 합니다.
장면이 끝날 때는 글자가 위로 빠지며 사라집니다(마지막 장면 제외).

미디어에 따라 배치가 다릅니다.
- fill   : 세로 영상·세로 사진 — 화면 가득, 아래 그라데이션 위에 제목과 내용
- window : 가로 영상·가로 사진 — 제목 아래 폭 가득한 창, 그 아래 내용 패널
- none   : 미디어 없음 — 디자인 색 바탕에 큰 글자만

프레임을 파이썬(Pillow)으로 한 장씩 그려 FFmpeg로 보냅니다. 움직이는 동안만 글자 층을 다시 그리고,
멈춘 뒤에는 같은 글자 층을 미디어 위에 얹기만 합니다. 시안: docs/design/siman_쇼츠_타이포.py
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageOps

from cards import ffmpeg_tools
from cards import tokens as T
from cards.card_renderer import mix
from cards.fonts import display_font, korean_font, wrap_text_px

LAYOUT = "typo"
W, H, FPS = 1080, 1920, 30
SAFE_TOP = T.SPACE["shorts_safe_top"]
SAFE_BOTTOM = 150                     # 영상 위주 모양과 같은 아래 UI 가림 영역(shorts_ed.FULL_BOTTOM_SAFE)
BAR_H = 8
BAR_Y = H - SAFE_BOTTOM - BAR_H - 10   # 진행 막대
CONTENT_BOTTOM = BAR_Y - 34            # 내용이 내려올 수 있는 맨 아래
MIN_WIN = 420                          # 가로 미디어 창의 최소 높이(글자가 많아도 이보다 줄이지 않음)
FILL_TOP_FRAC = 0.30                   # 세로 미디어: 화면 위쪽 이만큼은 미디어가 보이게 비운다
EXIT = 0.2                             # 장면 끝 글자가 빠지는 시간(초)
TITLE_START = 0.0                      # 장면 시작에 제목 낱말이 떠오르기 시작하는 시각(초) — 늦으면 장면 첫머리가 비어 보임
ROW_STEP = 0.18                        # 내용 줄이 차례로 나타나는 간격(초)
READ_CPS = 10.0                        # 화면 글자를 읽는 속도(글자/초) — 장면 최소 길이 계산용
READ_MIN, READ_MAX = 3.0, 14.0
PAD_MAX = 1.0                          # 읽을 시간 때문에 음성 뒤에 덧붙이는 쉼은 장면당 이만큼까지(그 이상은 말이 끊겨 들림)
SCALES = (1.24, 1.12, 1.0, 0.93, 0.86, 0.8, 0.74)     # 글자가 적은 장면은 크게, 많으면 줄여서 맞춘다
GAP_MAX = 72                           # 가로 미디어 배치: 블록 사이 최대 간격(남는 자리는 위아래로 나눠 가운데 정렬)
LIST_TYPES = ("steps", "numbered", "checklist", "event_info", "howto")
NUMBERED = ("steps", "numbered", "howto")
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def rgb(c: str) -> Tuple[int, int, int]:
    c = (c or "#000000").lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def prog(t: float, start: float, dur: float) -> float:
    return ease((t - start) / dur) if dur > 0 else (1.0 if t >= start else 0.0)


def clean(text: str) -> str:
    return " ".join((text or "").replace("*", "").replace("\\n", " ").split())


# =============================================================================
# 카드 → 화면 내용
# =============================================================================
@dataclass
class Content:
    kind: str                                      # prose | list | stat | cta
    title: str = ""                                # *강조* 표시 유지
    kicker: str = ""
    sub: str = ""                                  # 요약 한 줄(굵게, 강조색 막대)
    lines: List[str] = field(default_factory=list)     # 본문 줄(글머리표)
    items: List[Tuple[str, str]] = field(default_factory=list)   # (항목, 설명)
    marker: str = "check"                          # 목록 표시: number | check | label
    stat: Tuple[str, str] = ("", "")               # (큰 숫자, 설명)
    phone: str = ""
    address: str = ""
    quote: bool = False

    def chars(self) -> int:
        n = len(clean(self.title)) + len(clean(self.sub)) + sum(len(clean(x)) for x in self.lines)
        n += sum(len(clean(a)) + len(clean(b)) for a, b in self.items)
        n += len(self.stat[0]) + len(self.stat[1]) + len(self.phone) + len(self.address)
        return n


def split_item(text: str) -> Tuple[str, str]:
    """'항목: 설명' · '항목 - 설명' · '항목 — 설명' → (항목, 설명). 나눌 곳이 없으면 (전체, '')."""
    t = clean(text)
    m = re.match(r"^(.{2,28}?)\s*(?:[:：]|\s[-—–]\s)\s*(.{2,})$", t)
    return (m.group(1).strip(), m.group(2).strip()) if m else (t, "")


def body_lines(slide, limit: int = 5) -> List[str]:
    from cards import shorts_ed
    title = clean(slide.lead_headline)
    return [x for x in shorts_ed.card_body_lines(slide, limit + 1) if clean(x) != title][:limit]


def content_of(slide, kicker: str = "", phone: str = "", address: str = "") -> Content:
    from cards import shorts_script
    st = slide.slide_type
    c = Content(kind="prose", title=slide.lead_headline or "", kicker=kicker, sub=clean(slide.takeaway), quote=(st == "quote"))
    if st == "big_number" and (slide.stat_value or "").strip():
        c.kind, c.stat = "stat", (clean(slide.stat_value), clean(slide.stat_label))
        c.lines = body_lines(slide, 2)
        return c
    if st == "call_to_action":
        c.kind, c.phone, c.address = "cta", phone, address
        c.lines = [x for x in body_lines(slide, 3) if not (phone and phone.replace("-", "") in x.replace("-", ""))][:2]
        return c
    if st in LIST_TYPES:
        items = [split_item(x) for x in shorts_script.list_items(slide) if clean(x)]
        if items:
            c.kind, c.items = "list", items[:6]
            c.marker = "number" if st in NUMBERED else ("label" if st == "event_info" else "check")
            return c
    lines = body_lines(slide, 5)
    if c.sub and lines and clean(lines[0]) == c.sub:
        lines = lines[1:]
    if not c.sub and lines and st == "cover":
        c.sub, lines = lines[0], lines[1:]
    c.lines = lines
    return c


def read_seconds(content: Content, animated: bool = True) -> float:
    """화면 글자를 다 읽는 데 필요한 장면 최소 길이(초). 음성이 이보다 짧으면 장면을 늘린다."""
    sec = (1.4 if animated else 0.6) + content.chars() / READ_CPS
    return max(READ_MIN, min(READ_MAX, sec))


# =============================================================================
# 글자 조각
# =============================================================================
def _shadowed(text: str, font, color, shadow: bool) -> Image.Image:
    asc, desc = font.getmetrics()
    w = int(font.getlength(text)) + 10
    img = Image.new("RGBA", (max(1, w), asc + desc + 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if shadow:
        d.text((4, 5), text, font=font, fill=(0, 0, 0, 120))
    d.text((2, 2), text, font=font, fill=color)
    return img


class Title:
    """큰 제목: 낱말 차례로 떠오르기 + 강조어(*…*) 뒤 형광펜이 왼쪽에서 칠해짐. 폭·줄 수에 맞춰 글자 크기를 줄인다."""

    def __init__(self, text: str, width: int, start: int, minimum: int, max_lines: int, marker: str, shadow: bool = False):
        toks, em = [], False
        for seg in (text or "").split("*"):
            for wd in seg.split():
                toks.append((wd, em))
            em = not em
        if not toks:
            toks = [(" ", False)]
        plain = clean(text) or "가"
        size = start
        while True:
            font = display_font(size, plain)
            sp = font.getlength(" ")
            lines, cur, cw = [], [], 0.0
            for wd, e in toks:
                ww = font.getlength(wd)
                if cur and cw + sp + ww > width:
                    lines.append(cur)
                    cur, cw = [], 0.0
                cw += ww + (sp if cur else 0)
                cur.append((wd, e, ww))
            lines.append(cur)
            widest = max(sum(w for _, _, w in ln) + sp * (len(ln) - 1) for ln in lines)
            if (len(lines) <= max_lines and widest <= width) or size <= minimum:
                break
            size -= 4
        self.size, self.font = size, font
        asc, desc = font.getmetrics()
        self.asc, self.lh = asc, int((asc + desc) * 1.2)
        self.words: List[Tuple[Image.Image, int, int]] = []
        self.marks: List[Tuple[float, float, int]] = []
        for li, ln in enumerate(lines[:max_lines]):
            x, y, span = 0.0, li * self.lh, None
            for wd, e, ww in ln:
                self.words.append((_shadowed(wd, font, "#FFFFFF", shadow), int(x), y))
                if e:
                    span = [x, x + ww] if span is None else [span[0], x + ww]
                elif span:
                    self.marks.append((span[0], span[1], y))
                    span = None
                x += ww + sp
            if span:
                self.marks.append((span[0], span[1], y))
        self.h = self.lh * min(max_lines, len(lines))
        self.marker = marker

    def draw(self, canvas: Image.Image, ox: int, oy: int, t: float, animated: bool, exit_p: float = 0.0, stagger: float = 0.07) -> float:
        """그리고, 움직임이 끝나는 시각을 돌려준다."""
        mark_start = TITLE_START + stagger * len(self.words) + 0.1
        lift = -40 * ease(exit_p)
        if self.marks:
            for x0, x1, y in self.marks:
                p = prog(t, mark_start, 0.45) if animated else 1.0
                if p <= 0:
                    continue
                top, bot = oy + y + self.asc * 0.52 + lift, oy + y + self.asc * 1.1 + lift
                a = int(235 * (1 - exit_p))
                layer = Image.new("RGBA", (int(x1 - x0 + 24), int(bot - top) + 2), (0, 0, 0, 0))
                ImageDraw.Draw(layer).rounded_rectangle([0, 0, (x1 - x0 + 24) * p, bot - top], radius=8, fill=rgb(self.marker) + (a,))
                paste(canvas, layer, ox + x0 - 10, top)
        for i, (img, x, y) in enumerate(self.words):
            p = prog(t, TITLE_START + i * stagger, 0.32) if animated else 1.0
            paste(canvas, img, ox + x, oy + y + 28 * (1 - p) + lift, p * (1 - exit_p))
        return mark_start + 0.5 if self.marks else TITLE_START + stagger * len(self.words) + 0.32


def paste(canvas: Image.Image, img: Image.Image, x: float, y: float, alpha: float = 1.0) -> None:
    if alpha <= 0.01:
        return
    x, y = int(x), int(y)
    if x < 0 or y < 0:              # 화면 위·왼쪽으로 나간 부분은 잘라 낸다(Pillow는 음수 위치를 받지 않음)
        if -x >= img.width or -y >= img.height:
            return
        img = img.crop((max(0, -x), max(0, -y), img.width, img.height))
        x, y = max(0, x), max(0, y)
    if alpha < 0.99:
        img = img.copy()
        img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
    canvas.alpha_composite(img, (x, y))


def text_block(text: str, font, color, width: int, max_lines: int = 0, lh: float = 1.32, shadow: bool = False) -> Image.Image:
    lines = wrap_text_px(clean(text), font, width) or [""]
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,") + "…"
    asc, desc = font.getmetrics()
    step = int((asc + desc) * lh)
    w = int(max(font.getlength(x) for x in lines)) + 10
    img = Image.new("RGBA", (max(1, w), step * (len(lines) - 1) + asc + desc + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, x in enumerate(lines):
        if shadow:
            d.text((4, i * step + 4), x, font=font, fill=(0, 0, 0, 110))
        d.text((2, i * step), x, font=font, fill=color)
    return img


def chip(text: str, color: str, fg: str = "#FFFFFF", radius: int = 30) -> Image.Image:
    f = display_font(30, text)
    w = int(f.getlength(text)) + 48
    img = Image.new("RGBA", (w, 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, 59], radius=min(30, radius), fill=rgb(color) + (255,))
    d.text((w / 2, 31), text, font=f, fill=fg, anchor="mm")
    return img


def glass(w: int, h: int, radius: int, alpha: int = 150, tint: Tuple[int, int, int] = (14, 24, 18)) -> Image.Image:
    img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=tint + (alpha,), outline=(255, 255, 255, 64), width=2)
    return img


def badge(label: str, kind: str, color: str, size: int = 58) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, size - 1, size - 1], fill=rgb(color) + (255,))
    if kind == "check":
        c = size / 2
        d.line([(c - 13, c + 1), (c - 3, c + 12), (c + 15, c - 11)], fill="#FFFFFF", width=7, joint="curve")
    else:
        d.text((size / 2, size / 2 + 2), label, font=display_font(int(size * 0.48), label), fill="#FFFFFF", anchor="mm")
    return img


def vgrad(w: int, h: int, c0: str, c1: str) -> Image.Image:
    col = Image.new("RGB", (1, h))
    for y in range(h):
        col.putpixel((0, y), rgb(mix(c0, c1, y / max(1, h - 1))))
    return col.resize((w, h)).convert("RGBA")


def scrim(w: int, h: int, color: str, a0: int, a1: int) -> Image.Image:
    ramp = Image.linear_gradient("L").resize((w, max(1, h)))
    alpha = ramp.point(lambda v: int(a0 + (a1 - a0) * (v / 255) ** 1.2))
    layer = Image.new("RGBA", (w, max(1, h)), rgb(color) + (255,))
    layer.putalpha(alpha)
    return layer


# =============================================================================
# 내용 패널(요약·본문·항목·숫자·상담 안내)
# =============================================================================
@dataclass
class Piece:
    img: Image.Image
    x: int
    y: int
    order: int           # 나타나는 차례(0부터) — 패널 바탕은 -1
    count: Optional[Tuple[str, Callable[[str], Image.Image]]] = None    # 큰 숫자 올라가기: (최종 값, 값→그림)


def build_panel(c: Content, pal: dict, width: int, scale: float, framed: bool, trim: int = 0) -> Tuple[List[Piece], int]:
    """내용 조각과 전체 높이. framed=True면 반투명 바탕 위에(가로 미디어·글자만). trim: 본문 줄·항목 설명을 뒤에서부터 덜어 낸 수."""
    s = scale
    ip = int(40 * s) if framed else 0
    inner = width - 2 * ip
    pieces: List[Piece] = []
    y, order = (int(40 * s) if framed else 0), 0
    radius = pal["cap_radius"]
    soft_text = mix(pal["line"], "#FFFFFF", 0.35)
    tint = rgb(mix(pal["deep"], "#000000", 0.25))

    def add(img, x, dy_after, ordered=True):
        nonlocal y, order
        pieces.append(Piece(img, x, y, order if ordered else -1))
        y += img.height + dy_after
        order += 1 if ordered else 0

    if c.kind == "stat":
        val_font = display_font(int(170 * s), c.stat[0])
        while val_font.getlength(c.stat[0]) > inner and val_font.size > 60:
            val_font = display_font(val_font.size - 8, c.stat[0])

        def val_img(v, f=val_font):
            return _shadowed(v, f, pal["soft"], False)
        pieces.append(Piece(val_img(c.stat[0]), ip, y, order, (c.stat[0], val_img)))
        y += val_img(c.stat[0]).height + int(10 * s)
        order += 1
        if c.stat[1]:
            add(text_block(c.stat[1], korean_font(int(50 * s), "bold"), "#FFFFFF", inner, 2), ip, int(30 * s))
    if c.kind == "cta" and c.phone:
        tag = text_block("상담 문의", korean_font(int(36 * s), "bold"), pal["soft"], inner, 1)
        pf = display_font(int(96 * s), c.phone)
        while pf.getlength(c.phone) > inner - 60 and pf.size > 50:
            pf = display_font(pf.size - 6, c.phone)
        ph = text_block(c.phone, pf, "#FFFFFF", inner, 1, 1.1)
        addr = text_block(c.address, korean_font(int(40 * s), "medium"), soft_text, inner - 60, 2) if c.address else None
        box_h = 34 + tag.height + 8 + ph.height + (addr.height + 12 if addr else 0) + 30
        box = glass(inner, box_h, radius, 120, tint)
        bd = ImageDraw.Draw(box)
        bd.rounded_rectangle([0, 0, 12, box_h - 1], radius=6, fill=rgb(pal["accent"]) + (255,))
        box.alpha_composite(tag, (40, 34))
        box.alpha_composite(ph, (40, 34 + tag.height + 8))
        if addr:
            box.alpha_composite(addr, (40, 34 + tag.height + 8 + ph.height + 12))
        add(box, ip, int(30 * s))
    def takeaway(size):
        tf = display_font(int(size * s), c.sub)
        tk = text_block(c.sub, tf, "#FFFFFF", inner - 40, 2, 1.25)
        bar = Image.new("RGBA", (inner, tk.height), (0, 0, 0, 0))
        ImageDraw.Draw(bar).rounded_rectangle([0, 4, 9, min(tk.height - 4, int(size * 1.15 * s))], radius=4, fill=rgb(pal["accent"]) + (255,))
        bar.alpha_composite(tk, (36, 0))
        return bar

    if c.sub and c.kind != "list":
        add(takeaway(54), ip, int(30 * s))
    lines = list(c.lines)
    items = list(c.items)
    drop_desc = False
    if trim:
        if items:
            drop_desc = True
            items = items[:max(2, len(items) - max(0, trim - 1))]
        lines = lines[:max(1, len(lines) - trim)]
    if c.kind != "list":
        bf = korean_font(int(46 * s), "medium")
        for ln in lines:
            txt = text_block(ln, bf, mix(pal["line"], "#FFFFFF", 0.7), inner - 40, 3)
            row = Image.new("RGBA", (inner, txt.height), (0, 0, 0, 0))
            dot = int(10 * s)
            ImageDraw.Draw(row).ellipse([4, int(26 * s) - dot // 2, 4 + dot, int(26 * s) + dot // 2], fill=rgb(pal["soft"]) + (255,))
            row.alpha_composite(txt, (36, 0))
            add(row, ip, int(16 * s))
    else:
        hf = korean_font(int(48 * s), "bold")
        df = korean_font(int(40 * s), "medium")
        bsz = int(58 * s)
        for i, (head, desc) in enumerate(items):
            text_x = 40 + bsz + 30 if c.marker != "label" else 40
            if c.marker == "label":
                lab = text_block(head, korean_font(int(36 * s), "bold"), pal["soft"], inner - 80, 1)
                val = text_block(desc or head, hf, "#FFFFFF", inner - 80, 2) if desc else None
                parts = [lab] + ([val] if val else [])
            else:
                parts = [text_block(head, hf, "#FFFFFF", inner - text_x - 30, 2)]
                if desc and not drop_desc:
                    parts.append(text_block(desc, df, soft_text, inner - text_x - 30, 2))
            th = sum(p.height for p in parts) + 6 * (len(parts) - 1)
            rh = max(bsz + int(44 * s), th + int(44 * s))
            row = glass(inner, rh, radius, 165, tint)
            if c.marker != "label":
                row.alpha_composite(badge(str(i + 1), "number" if c.marker == "number" else "check",
                                          pal["accent"] if c.marker == "number" else pal["band"] if pal["band"] != pal["deep"] else pal["accent"], bsz),
                                    (34, (rh - bsz) // 2))
            yy = (rh - th) // 2
            for p in parts:
                row.alpha_composite(p, (text_x, yy))
                yy += p.height + 6
            add(row, ip, int(16 * s))
        if c.sub and trim < 3:
            y += int(14 * s)
            add(takeaway(46), ip, int(16 * s))
    y -= int(16 * s) if pieces else 0
    y += int(36 * s) if framed else 0
    if framed and pieces:
        bg = glass(width, y, radius, 70, tint)
        pieces.insert(0, Piece(bg, 0, 0, -1))
    return pieces, max(0, y)


# =============================================================================
# 미디어(프레임 공급)
# =============================================================================
class StillSource:
    """사진: 한 장을 cover로 맞추고 천천히 확대·이동(motion: none | zoom_in | zoom_out | pan)."""

    def __init__(self, path: str, size: Tuple[int, int], frames: int, motion: str = "zoom_in"):
        self.w, self.h = size
        self.frames = max(1, frames)
        z = {"none": (1.0, 1.0), "zoom_in": (1.0, 1.08), "zoom_out": (1.08, 1.0), "pan": (1.08, 1.08)}.get(motion, (1.0, 1.08))
        self.z0, self.z1, self.pan = z[0], z[1], motion == "pan"
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            big = self.big = max(self.z0, self.z1)
            self.base = ImageOps.fit(im, (int(self.w * big), int(self.h * big)), Image.LANCZOS)
        self.still = self.base.resize((self.w, self.h), Image.LANCZOS) if self.z0 == self.z1 == 1.0 else None

    def frame(self, i: int) -> Image.Image:
        if self.still is not None:
            return self.still
        p = i / max(1, self.frames - 1)
        p = p * p * (3 - 2 * p)
        z = self.z0 + (self.z1 - self.z0) * p
        bw, bh = self.base.size
        cw, ch = min(bw, self.w * self.big / z), min(bh, self.h * self.big / z)          # 보이는 영역(바탕 그림 좌표)
        cx = (bw - cw) * ((0.2 + 0.6 * p) if self.pan else 0.5)
        cy = (bh - ch) * 0.45
        cx, cy = max(0.0, cx), max(0.0, cy)
        return self.base.resize((self.w, self.h), Image.BILINEAR, box=(cx, cy, cx + cw, cy + ch))


class PairSource:
    """사진 두 장: 가운데에서 0.6초 동안 겹쳐 바뀜."""

    def __init__(self, paths: List[str], size, frames: int, motion: str):
        self.a = StillSource(paths[0], size, frames, motion)
        self.b = StillSource(paths[1], size, frames, "zoom_out" if motion == "zoom_in" else motion)
        self.mid, self.fade = frames / 2, 0.6 * FPS

    def frame(self, i: int) -> Image.Image:
        k = (i - (self.mid - self.fade / 2)) / self.fade
        if k <= 0:
            return self.a.frame(i)
        if k >= 1:
            return self.b.frame(i)
        return Image.blend(self.a.frame(i), self.b.frame(i), ease(k))


class VideoSource:
    """영상: FFmpeg가 크기·속도를 맞춰 RGB 프레임을 흘려 준다(짧으면 처음부터 반복, 원래 소리는 쓰지 않음)."""

    def __init__(self, path: str, size, frames: int, clip_start: float = 0.0, speed: float = 1.0):
        self.w, self.h = size
        spd = f"setpts=PTS/{speed:.4f}," if abs(speed - 1.0) > 0.001 else ""
        vf = f"{spd}fps={FPS},scale={self.w}:{self.h}:force_original_aspect_ratio=increase,crop={self.w}:{self.h},format=rgb24"
        cmd = [ffmpeg_tools.ffmpeg(), "-v", "error", "-stream_loop", "-1", "-ss", f"{max(0.0, clip_start):.3f}", "-i", path, "-an",
               "-vf", vf, "-frames:v", str(frames), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **ffmpeg_tools.no_window())
        self.n = self.w * self.h * 3
        self.last: Optional[Image.Image] = None

    def frame(self, i: int) -> Image.Image:
        buf = self.proc.stdout.read(self.n) if self.proc.stdout else b""
        if len(buf) == self.n:
            self.last = Image.frombytes("RGB", (self.w, self.h), buf)
        elif self.last is None:
            raise RuntimeError("동영상 프레임을 읽지 못했습니다")
        return self.last

    def close(self) -> None:
        try:
            if self.proc.stdout:
                self.proc.stdout.close()
            self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


def media_size(media) -> Tuple[int, int]:
    if media is None:
        return (0, 0)
    if media.kind == "video":
        return ffmpeg_tools.probe_size(media.paths[0])
    try:
        with Image.open(media.paths[0]) as im:
            im = ImageOps.exif_transpose(im)
            return im.size
    except OSError:
        return (0, 0)


def arrangement(media, size: Tuple[int, int]) -> str:
    """fill(세로 미디어 화면 가득) | window(가로 미디어 창) | none(미디어 없음)."""
    from cards import shorts_ed
    if media is None or not size[0] or not size[1]:
        return "none"
    return "window" if shorts_ed.is_landscape(size) else "fill"


def make_source(media, size: Tuple[int, int], frames: int, motion: str):
    if media.kind == "video":
        return VideoSource(media.paths[0], size, frames, media.clip_start, getattr(media, "speed", 1.0) or 1.0)
    if media.kind == "image_pair":
        return PairSource(media.paths[:2], size, frames, motion)
    return StillSource(media.paths[0], size, frames, motion)


# =============================================================================
# 장면
# =============================================================================
class TypoScene:
    def __init__(self, content: Content, pal: dict, arrange: str, msize: Tuple[int, int], series: str, page: str,
                 frames: int, last: bool, animated: bool, progress: Tuple[float, float]):
        self.c, self.pal, self.arr = content, pal, arrange
        self.frames, self.dur = frames, frames / FPS
        self.last, self.animated, self.progress = last, animated, progress
        pad = 64
        self.pad = pad
        cw = W - 2 * pad
        self.chip = chip(series, pal["accent"], radius=pal["cap_radius"]) if series else None
        self.page = _shadowed(page, display_font(28, page), "#FFFFFF", arrange == "fill") if page else None
        self.kicker = text_block(content.kicker, korean_font(38, "bold"), pal["soft"], cw, 1, shadow=arrange == "fill") if content.kicker else None
        head_h = SAFE_TOP + 60 + 22
        self.win: Optional[Tuple[int, int, int, int]] = None          # (x, y, w, h)
        shadow = arrange == "fill"
        for trim in range(0, 6):
            for s in SCALES:
                if arrange == "window":
                    ok = self._plan_window(s, trim, cw, head_h, msize)
                elif arrange == "fill":
                    ok = self._plan_fill(s, trim, cw, shadow)
                else:
                    ok = self._plan_none(s, trim, cw, head_h)
                if ok:
                    break
            if ok:
                break
        if not ok:          # 끝까지 안 들어가면 가장 작은 글자·가장 많이 덜어 낸 상태로 둔다(넘치는 부분은 아래 여백으로)
            {"window": lambda: self._plan_window(SCALES[-1], trim, cw, head_h, msize, True),
             "fill": lambda: self._plan_fill(SCALES[-1], trim, cw, shadow),
             "none": lambda: self._plan_none(SCALES[-1], trim, cw, head_h, True)}[arrange]()
        self.trimmed = trim
        self.static_layer: Optional[Image.Image] = None
        self.bg = self._background()
        self.anim_end = 0.0

    # --- 배치 ---------------------------------------------------------------
    def _kick_h(self) -> int:
        return (self.kicker.height + 14) if self.kicker else 0

    def _plan_window(self, s, trim, cw, head_h, msize, force: bool = False) -> bool:
        self.title = Title(self.c.title, cw, int(104 * s), int(64 * s), 3, self.pal["accent"])
        self.pieces, ph = build_panel(self.c, self.pal, cw, s, True, trim)
        self.panel_h = ph
        room = CONTENT_BOTTOM - head_h
        nat = int(cw * msize[1] / max(1, msize[0]))
        fixed = self._kick_h() + self.title.h + ph
        win_h = min(nat, room - fixed - 3 * 32)
        if win_h < MIN_WIN and not force:
            return False
        win_h = max(win_h, MIN_WIN)
        gap = max(16, (room - fixed - win_h) / 3)
        extra = 0.0
        if gap > GAP_MAX:
            extra, gap = (gap - GAP_MAX) * 3, GAP_MAX
        y = head_h + gap * 0.3 + extra * 0.45
        self.kick_y = y
        self.title_y = y + self._kick_h()
        self.win = (self.pad, int(self.title_y + self.title.h + gap * 1.2), cw, win_h)
        self.panel_y = int(self.win[1] + win_h + gap * 1.2)
        return True

    def _plan_fill(self, s, trim, cw, shadow) -> bool:
        self.title = Title(self.c.title, cw, int(104 * s), int(64 * s), 3, self.pal["accent"], shadow=True)
        self.pieces, ph = build_panel(self.c, self.pal, cw, s, False, trim)
        self.panel_h = ph
        self.panel_y = CONTENT_BOTTOM - ph
        self.title_y = self.panel_y - (int(40 * s) if ph else 0) - self.title.h
        self.kick_y = self.title_y - self._kick_h()
        return self.kick_y >= H * FILL_TOP_FRAC

    def _plan_none(self, s, trim, cw, head_h, force: bool = False) -> bool:
        self.title = Title(self.c.title, cw - 20, int(124 * s), int(72 * s), 4, self.pal["accent"])
        self.pieces, ph = build_panel(self.c, self.pal, cw, s, False, trim)
        self.panel_h = ph
        quote_h = int(200 * s) if self.c.quote else 0
        block = quote_h + self._kick_h() + self.title.h + (int(56 * s) if ph else 0) + ph
        room = CONTENT_BOTTOM - head_h - 30
        if block > room and not force:
            return False
        top = head_h + 30 + max(0, (room - block) / 2)
        self.quote_y = top
        self.kick_y = top + quote_h
        self.title_y = self.kick_y + self._kick_h()
        self.panel_y = int(self.title_y + self.title.h + (int(56 * s) if ph else 0))
        self.quote_size = int(260 * s)
        return True

    def _background(self) -> Image.Image:
        pal = self.pal
        if self.arr == "none":
            bg = vgrad(W, H, pal["band"], mix(pal["band"], pal["deep"], 0.7))
            over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(over)
            d.ellipse([W - 420, 260, W + 260, 940], fill=(255, 255, 255, 16))
            d.ellipse([-300, 1250, 380, 1930], fill=(255, 255, 255, 12))
            bg.alpha_composite(over)
            return bg
        if self.arr == "window":
            return vgrad(W, H, pal["band"], pal["deep"])
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))

    def media_box(self) -> Tuple[int, int]:
        if self.arr == "fill":
            return (W, H)
        if self.arr == "window" and self.win:
            return (self.win[2], self.win[3])
        return (0, 0)

    # --- 그리기 -------------------------------------------------------------
    def _text_layer(self, t: float) -> Image.Image:
        pal, a = self.pal, self.animated
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        e = 0.0 if (self.last or not a) else prog(t, self.dur - EXIT, EXIT)
        lift = -40 * ease(e)
        # 시리즈 칩·쪽 번호는 장면이 바뀌어도 제자리에 그대로(나타나거나 빠지지 않음) — 장면 사이에 글자 없는 화면이 생기지 않게
        if self.chip:
            paste(layer, self.chip, self.pad, SAFE_TOP)
        if self.page:
            paste(layer, self.page, W - self.pad - self.page.width, SAFE_TOP + 14)
        if self.arr == "none" and self.c.quote:
            q = _shadowed("“", display_font(self.quote_size, "“"), pal["accent"], False)
            qp = prog(t, 0, 0.5) if a else 1.0
            paste(layer, q, self.pad, self.quote_y - 30 * (1 - qp) + lift, qp * (1 - e))
        if self.kicker:
            paste(layer, self.kicker, self.pad, self.kick_y + lift, (prog(t, 0.0, 0.25) if a else 1.0) * (1 - e))
        end = self.title.draw(layer, self.pad + (10 if self.arr == "none" else 0), int(self.title_y), t, a, e,
                              stagger=0.1 if self.arr == "none" else 0.07)
        base = 0.4 if self.arr != "none" else 0.75
        last_k = 0
        for pc in self.pieces:
            k = max(0, pc.order)
            last_k = max(last_k, k)
            start = base + (0.2 if pc.order >= 0 else 0) + k * ROW_STEP
            p = prog(t, start if pc.order >= 0 else base, 0.4) if a else 1.0
            img = pc.img
            if pc.count and a:
                cp = prog(t, start, 0.9)
                if cp < 1:
                    img = pc.count[1](count_up(pc.count[0], cp))
            paste(layer, img, self.pad + pc.x, self.panel_y + pc.y + 24 * (1 - p) + lift, p * (1 - e))
        self.anim_end = max(end, base + 0.2 + last_k * ROW_STEP + 0.4, 1.0 if any(p.count for p in self.pieces) else 0.0)
        return layer

    def frame(self, i: int, media_frame: Optional[Image.Image]) -> Image.Image:
        t = i / FPS
        canvas = self.bg.copy() if self.arr != "fill" else Image.new("RGBA", (W, H), (0, 0, 0, 255))
        if media_frame is not None:
            m = media_frame.convert("RGBA")
            if self.arr == "fill":
                canvas = m
                if not hasattr(self, "_scrims"):
                    sc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    top_h = SAFE_TOP + 300
                    sc.alpha_composite(scrim(W, top_h, self.pal["deep"], 170, 0), (0, 0))
                    from_y = int(max(0, self.kick_y - 360))
                    sc.alpha_composite(scrim(W, H - from_y, self.pal["deep"], 0, 248), (0, from_y))
                    self._scrims = sc
                canvas.alpha_composite(self._scrims)
            elif self.win:
                x, y, w, h = self.win
                if not hasattr(self, "_mask"):
                    self._mask = Image.new("L", (w, h), 0)
                    ImageDraw.Draw(self._mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=self.pal["cap_radius"], fill=255)
                pw = prog(t, 0, 0.5) if self.animated else 1.0
                m.putalpha(self._mask.point(lambda v, pw=pw: int(v * pw)) if pw < 1 else self._mask)
                canvas.alpha_composite(m, (x, int(y + 30 * (1 - pw))))
        moving = self.animated and (self.static_layer is None or t < self.anim_end + 0.05 or
                                    (not self.last and t >= self.dur - EXIT - 0.02))
        if moving:
            layer = self._text_layer(t)
            if self.animated and t >= self.anim_end and not (not self.last and t >= self.dur - EXIT - 0.02):
                self.static_layer = layer
        else:
            if self.static_layer is None:
                self.static_layer = self._text_layer(max(self.anim_end, 10.0) if self.animated else 0.0)
            layer = self.static_layer
        canvas.alpha_composite(layer)
        g0, g1 = self.progress
        d = ImageDraw.Draw(canvas)
        frac = g0 + (g1 - g0) * min(1.0, t / max(0.01, self.dur))
        d.rounded_rectangle([self.pad, BAR_Y, W - self.pad, BAR_Y + BAR_H], radius=4, fill=(255, 255, 255, 70))
        if frac > 0:
            d.rounded_rectangle([self.pad, BAR_Y, self.pad + (W - 2 * self.pad) * frac, BAR_Y + BAR_H], radius=4, fill=rgb(self.pal["accent"]) + (255,))
        return canvas


def count_up(final: str, frac: float) -> str:
    """'97.14점' → 숫자 부분만 frac 비율로(자릿수·소수 자리 유지)."""
    m = _NUM_RE.search(final)
    if not m:
        return final
    raw = m.group(0)
    num = float(raw.replace(",", ""))
    dec = len(raw.split(".")[1]) if "." in raw else 0
    v = num * frac
    s = f"{v:,.{dec}f}" if "," in raw else f"{v:.{dec}f}"
    return final[:m.start()] + s + final[m.end():]


def render_segment(out: str, content: Content, pal: dict, media, frames: int, *, series: str = "", page: str = "",
                   last: bool = False, animated: bool = True, progress: Tuple[float, float] = (0.0, 1.0), motion: str = "zoom_in") -> dict:
    """장면 하나를 `frames`장짜리 H.264 조각으로. 반환: {'arrangement', 'trimmed'}. 영상을 읽지 못하면 RuntimeError."""
    size = media_size(media)
    arr = arrangement(media, size)
    scene = TypoScene(content, pal, arr, size, series, page, frames, last, animated, progress)
    source = make_source(media, scene.media_box(), frames, motion) if arr != "none" else None
    cmd = [ffmpeg_tools.ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-frames:v", str(frames), "-pix_fmt", "yuv420p", *ffmpeg_tools.h264_args("good", "veryfast"), "-r", str(FPS), out]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **ffmpeg_tools.no_window())
    try:
        for i in range(frames):
            mf = source.frame(i) if source is not None else None
            enc.stdin.write(scene.frame(i, mf).convert("RGB").tobytes())
        enc.stdin.close()
        err = enc.stderr.read().decode("utf-8", "replace") if enc.stderr else ""
        if enc.wait() != 0:
            raise RuntimeError(f"글자 중심 장면 인코딩 실패: {err[:300]}")
    except BaseException:
        try:
            enc.kill()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        if isinstance(source, VideoSource):
            source.close()
    return {"arrangement": arr, "trimmed": scene.trimmed}
