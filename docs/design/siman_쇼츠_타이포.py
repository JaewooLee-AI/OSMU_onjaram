"""쇼츠 '카드 내용 + 글자 움직임' 시안 영상(앱 코드와 연결 전).

장면 4개 — ① 사진(화면 가득, 천천히 확대) ② 가로 영상(제목 아래 창 + 카드 내용 패널)
③ 세로 영상(화면 가득 + 아래 내용 칸) ④ 미디어 없음(글자만).
원칙: 장면 시작 약 1초 동안만 움직이고 그 뒤는 멈춰서 읽게 한다(음성 시각과 맞추지 않음).
사진·영상은 사람 없는 합성 풍경(실제 사진 아님), 문구는 보편 심리교육 예시(사실·수치 없음), 소리 없음.

실행: python docs/design/siman_쇼츠_타이포.py [출력.mp4]
"""
import math
import os
import random
import subprocess
import sys

sys.path.insert(0, os.getcwd())
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from cards import ffmpeg_tools

W, H, FPS = 1080, 1920, 30
PAD, SAFE_TOP, SAFE_BOT = 64, 120, 150
FONT_DIR = os.path.join(os.getcwd(), "cards", "fonts")
SAGE, SAGE_DEEP, SAGE_DARK = "#4A7C59", "#35593F", "#1B2A20"
CORAL, OAT, CREAM, SOFT = "#E07A5F", "#F0ECE1", "#FAF8F5", "#B9D1BF"
SERIES = "온자람 마음노트"


def font(size, kind="display"):
    name = {"display": "GmarketSansBold.otf", "medium": "GmarketSansMedium.otf",
            "body": "Pretendard-SemiBold.otf", "bold": "Pretendard-Bold.otf"}[kind]
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


def rgb(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    a, b = rgb(a), rgb(b)
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def prog(t, start, dur):
    return ease((t - start) / dur)


# ---------------------------------------------------------------- 합성 미디어(사람 없음)
def landscape(w, h, tone=0, seed=7):
    random.seed(seed)
    sky = [("#F3E3CF", "#CFE0D6"), ("#E9E4F0", "#C9DCCF"), ("#F6E7D6", "#D7E5DA")][tone]
    img = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(img)
    for y in range(h):
        px.line([(0, y), (w, y)], fill=mix(sky[0], sky[1], y / h))
    d = ImageDraw.Draw(img, "RGBA")
    r = int(min(w, h) * 0.12)
    d.ellipse([w * 0.68 - r, h * 0.22 - r, w * 0.68 + r, h * 0.22 + r], fill=(255, 250, 238, 235))
    for i, (c, base, amp) in enumerate([("#9DB9A4", 0.56, 0.07), ("#7FA38B", 0.67, 0.08), ("#5E8870", 0.79, 0.09)]):
        pts = [(0, h)]
        for x in range(0, w + 40, 40):
            pts.append((x, h * base + amp * h * (0.5 - abs(((x / w * 3 + i * 0.37) % 1) - 0.5) * 2)))
        pts.append((w, h))
        d.polygon(pts, fill=c)
    for k in range(int(w / 110)):
        x = 60 + 110 * k + random.randint(-20, 20)
        y = h * 0.94
        d.ellipse([x - 50, y - h * 0.08, x + 50, y + h * 0.02], fill=(48, 86, 62, 190))
    return img.filter(ImageFilter.GaussianBlur(2.0))


class Footage:
    """'영상' 대용: 넓은 합성 풍경을 천천히 이동 + 떠다니는 빛 알갱이."""

    def __init__(self, w, h, tone, seed, dx=0.0, dy=0.0):
        self.w, self.h, self.dx, self.dy = w, h, dx, dy
        self.big = landscape(int(w * 1.25), int(h * 1.25), tone, seed)
        random.seed(seed + 1)
        self.dots = [(random.random(), random.random(), random.uniform(6, 16), random.uniform(0.3, 1.0)) for _ in range(26)]

    def frame(self, t):
        bw, bh = self.big.size
        ox = int((bw - self.w) * (0.5 + self.dx * math.sin(t * 0.35)))
        oy = int((bh - self.h) * (0.5 + self.dy * math.sin(t * 0.3)))
        img = self.big.crop((ox, oy, ox + self.w, oy + self.h)).convert("RGBA")
        over = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        for x, y, r, sp in self.dots:
            yy = (y - t * 0.03 * sp) % 1.0
            xx = x + 0.02 * math.sin(t * sp + y * 9)
            a = int(110 + 80 * math.sin(t * 1.5 * sp + x * 7))
            d.ellipse([xx * self.w - r, yy * self.h - r, xx * self.w + r, yy * self.h + r], fill=(255, 252, 240, max(0, a)))
        img.alpha_composite(over.filter(ImageFilter.GaussianBlur(1.5)))
        return img


# ---------------------------------------------------------------- 글자 조각
def words_of(text):
    """'*강조*' 표시를 낱말 [(글자, 강조)]로."""
    out, em = [], False
    for seg in text.split("*"):
        for wd in seg.split():
            out.append((wd, em))
        em = not em
    return out


class Title:
    """낱말 차례로 떠오르기 + 강조어 형광펜 칠하기."""

    def __init__(self, text, size, width, x, y, color="#FFFFFF", em_color="#FFFFFF", marker=CORAL, align="left", lh=1.22):
        self.f = font(size)
        sp = self.f.getlength(" ")
        lines, cur, cw = [], [], 0
        for wd, em in words_of(text):
            ww = self.f.getlength(wd)
            if cur and cw + sp + ww > width:
                lines.append(cur)
                cur, cw = [], 0
            cur.append((wd, em, ww))
            cw += ww + (sp if len(cur) > 1 else 0)
        lines.append(cur)
        asc, desc = self.f.getmetrics()
        self.lh = int((asc + desc) * lh)
        self.words, self.marks = [], []
        for li, ln in enumerate(lines):
            lw = sum(w for _, _, w in ln) + sp * (len(ln) - 1)
            cx = x if align == "left" else x + (width - lw) / 2
            cy = y + li * self.lh
            span = None
            for wd, em, ww in ln:
                img = Image.new("RGBA", (int(ww) + 8, asc + desc + 8), (0, 0, 0, 0))
                ImageDraw.Draw(img).text((2, 2), wd, font=self.f, fill=em_color if em else color)
                self.words.append((img, int(cx), int(cy)))
                if em:
                    span = [cx, cx + ww] if span is None else [span[0], cx + ww]
                elif span:
                    self.marks.append((span, cy))
                    span = None
                cx += ww + sp
            if span:
                self.marks.append((span, cy))
        self.asc, self.marker, self.h = asc, marker, self.lh * len(lines)

    def draw(self, canvas, t, start=0.0, stagger=0.07, rise=28, dur=0.4, exit_p=0.0):
        mark_start = start + stagger * len(self.words) + 0.15
        for span, cy in self.marks:              # 형광펜은 글자 뒤에
            p = prog(t, mark_start, 0.45)
            if p <= 0:
                continue
            x0, x1 = span
            top = cy + self.asc * 0.52
            bot = cy + self.asc * 1.08
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).rounded_rectangle([x0 - 10, top, x0 - 10 + (x1 - x0 + 20) * p, bot], radius=8,
                                                    fill=rgb(self.marker) + (int(235 * (1 - exit_p)),))
            canvas.alpha_composite(layer)
        for i, (img, x, y) in enumerate(self.words):
            p = prog(t, start + i * stagger, dur)
            if p <= 0:
                continue
            a = p * (1 - exit_p)
            paste(canvas, img, x, int(y + rise * (1 - p) - 40 * ease(exit_p)), a)


def paste(canvas, img, x, y, alpha=1.0):
    if alpha <= 0:
        return
    if alpha < 1:
        img = img.copy()
        img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
    canvas.alpha_composite(img, (int(x), int(y)))


def text_img(text, f, color, width=None):
    lines = [text] if width is None else wrap(text, f, width)
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * 1.32)
    w = int(max(f.getlength(l) for l in lines)) + 8
    img = Image.new("RGBA", (w, lh * len(lines) + 6), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        d.text((2, i * lh), l, font=f, fill=color)
    return img


def wrap(text, f, width):
    lines, cur = [], ""
    for wd in text.split():
        trial = (cur + " " + wd).strip()
        if cur and f.getlength(trial) > width:
            lines.append(cur)
            cur = wd
        else:
            cur = trial
    return lines + ([cur] if cur else [])


def chip(text, color=CORAL, fg="#FFFFFF"):
    f = font(30)
    w = int(f.getlength(text)) + 48
    img = Image.new("RGBA", (w, 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, 59], radius=30, fill=rgb(color) + (255,))
    d.text((w / 2, 31), text, font=f, fill=fg, anchor="mm")
    return img


def page_no(text, color="#FFFFFF"):
    return text_img(text, font(30, "bold"), color)


def scrim(h, color, a0, a1):
    ramp = Image.linear_gradient("L").resize((W, h))
    alpha = ramp.point(lambda v: int(a0 + (a1 - a0) * (v / 255) ** 1.2))
    layer = Image.new("RGBA", (W, h), rgb(color) + (255,))
    layer.putalpha(alpha)
    return layer


def vgrad(c0, c1):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=mix(c0, c1, y / H))
    return img.convert("RGBA")


def rounded_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    return m


def progress(canvas, t, total_t, total):
    d = ImageDraw.Draw(canvas, "RGBA")
    y = H - SAFE_BOT + 24
    d.rounded_rectangle([PAD, y, W - PAD, y + 8], radius=4, fill=(255, 255, 255, 70))
    d.rounded_rectangle([PAD, y, PAD + (W - 2 * PAD) * min(1, total_t / total), y + 8], radius=4, fill=rgb(CORAL) + (255,))


# ---------------------------------------------------------------- 장면
class Scene:
    dur = 5.0
    EXIT = 0.3

    def exit_p(self, t):
        return prog(t, self.dur - self.EXIT, self.EXIT)


def glass_row(w, h, radius=28, alpha=150):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=(20, 34, 26, alpha), outline=(255, 255, 255, 64), width=2)
    return img


def num_badge(n, color=CORAL, size=56, fg="#FFFFFF"):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, size - 1, size - 1], fill=rgb(color) + (255,))
    d.text((size / 2, size / 2 + 2), str(n), font=font(int(size * 0.5)), fill=fg, anchor="mm")
    return img


class PhotoCover(Scene):
    """① 사진: 화면 가득 + 천천히 확대, 아래 그라데이션 위 제목·소개·'오늘 함께 볼 것' 목차."""
    dur = 6.5

    def __init__(self):
        self.photo = landscape(W, H, 2, 11).convert("RGBA")
        self.scrim = scrim(1350, SAGE_DARK, 0, 250)
        self.top = scrim(360, SAGE_DARK, 150, 0)
        self.chip, self.page = chip(SERIES), page_no("01 / 04")
        self.sub = text_img("지친 마음도 몸처럼 돌봄이 필요합니다. 오늘은 내 마음이 보내는 신호를 함께 살펴봐요.", font(48, "body"), CREAM, W - 2 * PAD)
        self.toc_head = text_img("오늘 함께 볼 것", font(36, "medium"), SOFT)
        f = font(44, "body")
        self.toc = [(num_badge(i + 1, size=52), text_img(x, f, "#FFFFFF")) for i, x in
                    enumerate(["쉬어도 피곤한 이유", "놓치기 쉬운 마음의 신호", "혼자 버티지 않는 방법"])]
        self.row_h = 78
        self.box_h = 36 + self.toc_head.height + 18 + self.row_h * len(self.toc) + 24
        self.box_y = H - SAFE_BOT - 50 - self.box_h
        tmp = Title("요즘 *마음이 지친* 당신에게", 112, W - 2 * PAD, PAD, 0)
        self.sub_y = self.box_y - 56 - self.sub.height
        self.ty = self.sub_y - 40 - tmp.h
        self.title = Title("요즘 *마음이 지친* 당신에게", 112, W - 2 * PAD, PAD, self.ty)

    def render(self, t):
        z = 1.0 + 0.08 * (t / self.dur)
        pw, ph = int(W * z), int(H * z)
        img = self.photo.resize((pw, ph), Image.BILINEAR).crop(((pw - W) // 2, (ph - H) // 3, (pw - W) // 2 + W, (ph - H) // 3 + H))
        c = img.copy()
        c.alpha_composite(self.scrim, (0, H - 1350))
        c.alpha_composite(self.top, (0, 0))
        e = self.exit_p(t)
        out = -40 * ease(e)
        paste(c, self.chip, PAD, SAFE_TOP + 10, prog(t, 0, 0.3) * (1 - e))
        paste(c, self.page, W - PAD - self.page.width, SAFE_TOP + 20, prog(t, 0, 0.3) * (1 - e))
        self.title.draw(c, t, start=0.15, exit_p=e)
        p = prog(t, 0.95, 0.45)
        paste(c, self.sub, PAD, self.sub_y + 24 * (1 - p) + out, p * (1 - e))
        bp = prog(t, 1.25, 0.4)
        paste(c, glass_row(W - 2 * PAD, self.box_h, 32, 120), PAD, self.box_y + 30 * (1 - bp) + out, bp * (1 - e))
        paste(c, self.toc_head, PAD + 40, self.box_y + 36 + out, bp * (1 - e))
        y = self.box_y + 36 + self.toc_head.height + 18
        for i, (badge, tx) in enumerate(self.toc):
            rp = prog(t, 1.45 + i * 0.18, 0.35)
            paste(c, badge, PAD + 40 - 30 * (1 - rp), y + (self.row_h - 52) / 2 + out, rp * (1 - e))
            paste(c, tx, PAD + 118 - 30 * (1 - rp), y + (self.row_h - tx.height) / 2 + 4 + out, rp * (1 - e))
            y += self.row_h
        return c


class LandscapeBody(Scene):
    """② 가로 영상: 제목 바로 아래 폭 가득 창, 그 아래 카드 내용 패널(줄 단위로 빠르게)."""
    dur = 7.0

    def __init__(self):
        self.bg = vgrad(SAGE_DEEP, SAGE_DARK)
        self.vw, self.vh = W - 2 * PAD, int((W - 2 * PAD) * 9 / 16)
        self.chip, self.page = chip(SERIES), page_no("02 / 04")
        self.kicker = text_img("마음 이야기", font(38, "medium"), CORAL)
        lines = ["몸은 쉬고 있어도 생각은 계속 일하고 있을 수 있어요.",
                 "걱정이 많을수록 뇌는 '쉬는 중'이라고 느끼기 어렵습니다.",
                 "잠들기 전 걱정을 종이에 적어 두면 생각을 내려놓는 데 도움이 됩니다.",
                 "짧은 산책이나 천천히 숨 쉬기로 생각의 속도를 늦춰 보세요."]
        f = font(44, "body")
        self.lines = [text_img("•  " + l, f, CREAM, W - 2 * PAD - 80) for l in lines]
        self.take = text_img("생각에도 쉬는 시간이 필요해요", font(54), "#FFFFFF")
        self.panel_h = 44 + self.take.height + 30 + sum(l.height + 14 for l in self.lines) + 20
        tmp = Title("쉬어도 *피곤한* 이유", 104, W - 2 * PAD, PAD, 0)
        head = 96 + self.kicker.height + 14
        room = H - SAFE_BOT - 50 - SAFE_TOP
        self.vh = max(420, min(self.vh, room - head - tmp.h - self.panel_h - 3 * 30))      # 자리가 모자라면 영상 창을 줄인다(가운데를 잘라 맞춤)
        self.foot = Footage(self.vw, self.vh, 0, 3, dx=0.35)
        self.mask = rounded_mask(self.vw, self.vh, 36)
        used = head + tmp.h + self.vh + self.panel_h
        gap = max(30, (room - used) / 3)
        ty = SAFE_TOP + head
        self.title = Title("쉬어도 *피곤한* 이유", 104, W - 2 * PAD, PAD, int(ty + gap * 0.4))
        self.win_y = int(ty + gap * 0.4 + tmp.h + gap * 1.1)
        self.panel_y = int(self.win_y + self.vh + gap * 1.1)

    def render(self, t):
        c = self.bg.copy()
        e = self.exit_p(t)
        win = self.foot.frame(t)
        pw = prog(t, 0.0, 0.5)
        win.putalpha(self.mask.point(lambda v: int(v * pw)))
        c.alpha_composite(win, (PAD, int(self.win_y + 30 * (1 - pw))))
        paste(c, self.chip, PAD, SAFE_TOP + 10, prog(t, 0, 0.3) * (1 - e))
        paste(c, self.page, W - PAD - self.page.width, SAFE_TOP + 20, prog(t, 0, 0.3) * (1 - e))
        paste(c, self.kicker, PAD, SAFE_TOP + 96, prog(t, 0.05, 0.3) * (1 - e))
        self.title.draw(c, t, start=0.1, exit_p=e)
        pp = prog(t, 0.55, 0.4)
        if pp > 0:
            layer = Image.new("RGBA", (W, self.panel_h), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            d.rounded_rectangle([PAD, 0, W - PAD, self.panel_h - 1], radius=36, fill=(255, 255, 255, 26), outline=(255, 255, 255, 60), width=2)
            y = 44
            take_y = y
            d.rounded_rectangle([PAD + 36, take_y + 4, PAD + 45, take_y + 62], radius=4, fill=rgb(CORAL) + (255,))
            paste(c, layer, 0, self.panel_y + 40 * (1 - pp) - 40 * ease(e), pp * (1 - e))
            tp = prog(t, 0.75, 0.35)
            paste(c, self.take, PAD + 72, self.panel_y + take_y + 18 * (1 - tp) - 40 * ease(e), tp * (1 - e))
            y = take_y + self.take.height + 30
            for i, li in enumerate(self.lines):
                lp = prog(t, 0.95 + i * 0.18, 0.35)
                paste(c, li, PAD + 44, self.panel_y + y + 18 * (1 - lp) - 40 * ease(e), lp * (1 - e))
                y += li.height + 14
        return c


class PortraitList(Scene):
    """③ 세로 영상: 화면 가득, 아래 반투명 칸에 체크 항목(제목+설명)이 빠르게 펼쳐짐."""
    dur = 7.0

    def __init__(self):
        self.foot = Footage(W, H, 1, 5, dy=0.4)
        self.scrim = scrim(1450, SAGE_DARK, 0, 252)
        self.top = scrim(380, SAGE_DARK, 160, 0)
        self.chip, self.page = chip(SERIES), page_no("03 / 04")
        items = [("잠이 자주 깨요", "자고 일어나도 개운하지 않아요"),
                 ("작은 일에도 짜증이 나요", "평소라면 넘길 일이 크게 느껴져요"),
                 ("좋아하던 일이 귀찮아요", "즐거움이 줄고 자꾸 미루게 돼요"),
                 ("사람을 만나기 싫어요", "혼자 있고 싶은 마음이 커져요")]
        self.row_h, self.gap = 148, 16
        self.rows = [(text_img(a, font(46), "#FFFFFF"), text_img(b, font(40, "body"), SOFT)) for a, b in items]
        self.note = text_img("이런 신호가 오래 이어진다면, 혼자 버티지 말고 이야기를 나눠 보세요.", font(40, "body"), CREAM, W - 2 * PAD - 20)
        self.note_y = H - SAFE_BOT - 50 - self.note.height
        self.list_y = self.note_y - 36 - (self.row_h + self.gap) * len(self.rows) + self.gap
        tmp = Title("이런 *마음의 신호* 있나요?", 100, W - 2 * PAD, PAD, 0)
        self.title = Title("이런 *마음의 신호* 있나요?", 100, W - 2 * PAD, PAD, self.list_y - tmp.h - 44)

    def row(self):
        img = glass_row(W - 2 * PAD, self.row_h, 32, 165)
        d = ImageDraw.Draw(img)
        cx, cy = 66, self.row_h // 2
        d.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], fill=rgb(SAGE) + (255,))
        d.line([(cx - 13, cy + 1), (cx - 3, cy + 12), (cx + 15, cy - 11)], fill="#FFFFFF", width=7, joint="curve")
        return img

    def render(self, t):
        c = self.foot.frame(t)
        c.alpha_composite(self.scrim, (0, H - 1450))
        c.alpha_composite(self.top, (0, 0))
        e = self.exit_p(t)
        out = -40 * ease(e)
        paste(c, self.chip, PAD, SAFE_TOP + 10, prog(t, 0, 0.3) * (1 - e))
        paste(c, self.page, W - PAD - self.page.width, SAFE_TOP + 20, prog(t, 0, 0.3) * (1 - e))
        self.title.draw(c, t, start=0.1, exit_p=e)
        base = self.row()
        for i, (ttl, desc) in enumerate(self.rows):
            p = prog(t, 0.7 + i * 0.22, 0.4)
            if p <= 0:
                continue
            y = self.list_y + i * (self.row_h + self.gap) + out
            dx = -60 * (1 - p)
            paste(c, base, PAD + dx, y, p * (1 - e))
            paste(c, ttl, PAD + 126 + dx, y + 22, p * (1 - e))
            paste(c, desc, PAD + 128 + dx, y + 22 + ttl.height + 2, p * (1 - e))
        np_ = prog(t, 1.7, 0.45)
        paste(c, self.note, PAD + 10, self.note_y + 20 * (1 - np_) + out, np_ * (1 - e))
        return c


class TypeOnly(Scene):
    """④ 미디어 없음: 브랜드 색 바탕에 큰 글자 + 작은 실천 3가지."""
    dur = 7.0

    def __init__(self):
        self.bg = vgrad(SAGE, SAGE_DEEP)
        over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        d.ellipse([W - 420, 260, W + 260, 940], fill=(255, 255, 255, 16))
        d.ellipse([-300, 1250, 380, 1930], fill=(255, 255, 255, 12))
        self.bg.alpha_composite(over)
        self.chip, self.page = chip(SERIES), page_no("04 / 04")
        self.sub = text_img("마음을 이야기하는 것에서 회복이 시작됩니다.", font(52, "body"), OAT, W - 2 * PAD - 40)
        f = font(44, "body")
        self.tips = [(num_badge(i + 1, CREAM, 56, SAGE_DEEP), text_img(x, f, "#FFFFFF")) for i, x in
                     enumerate(["가까운 사람에게 지금 기분을 말해 보기", "하루 중 잠깐, 나를 위한 시간 만들기", "도움이 필요할 땐 상담에 문의하기"])]
        self.tip_h, self.tip_gap = 118, 16
        tips_h = (self.tip_h + self.tip_gap) * 3 - self.tip_gap
        tmp = Title("*혼자* 버티지 않아도 괜찮아요", 120, W - 2 * PAD - 40, PAD + 20, 0, lh=1.18)
        block = 200 + tmp.h + 50 + self.sub.height + 70 + tips_h
        self.ty = SAFE_TOP + 90 + int((H - SAFE_BOT - 150 - SAFE_TOP - 90 - block) / 2) + 200
        self.title = Title("*혼자* 버티지 않아도 괜찮아요", 120, W - 2 * PAD - 40, PAD + 20, self.ty, align="left", lh=1.18)
        self.tips_y = self.ty + tmp.h + 50 + self.sub.height + 70
        self.end = chip("온자람", color=CREAM, fg=SAGE_DEEP)

    def render(self, t):
        c = self.bg.copy()
        e = self.exit_p(t) if False else 0.0          # 마지막 장면은 사라지지 않음
        paste(c, self.chip, PAD, SAFE_TOP + 10, prog(t, 0, 0.3))
        paste(c, self.page, W - PAD - self.page.width, SAFE_TOP + 20, prog(t, 0, 0.3))
        q = font(260)
        qp = prog(t, 0.0, 0.5)
        paste(c, text_img("“", q, CORAL), PAD + 4, self.ty - 230 - 30 * (1 - qp), qp)
        self.title.draw(c, t, start=0.2, stagger=0.12, rise=46, dur=0.5, exit_p=e)
        p = prog(t, 1.5, 0.5)
        y = self.ty + self.title.h + 50
        d = ImageDraw.Draw(c)
        lw = (W - 2 * PAD - 40) * prog(t, 1.3, 0.5)
        d.rectangle([PAD + 20, y - 24, PAD + 20 + lw * 0.25, y - 18], fill=OAT)
        paste(c, self.sub, PAD + 20, y + 20 * (1 - p), p)
        row = glass_row(W - 2 * PAD - 40, self.tip_h, 30, 70)
        for i, (badge, tx) in enumerate(self.tips):
            rp = prog(t, 1.9 + i * 0.22, 0.4)
            ry = self.tips_y + i * (self.tip_h + self.tip_gap)
            paste(c, row, PAD + 20, ry + 24 * (1 - rp), rp)
            paste(c, badge, PAD + 50, ry + (self.tip_h - 56) / 2 + 24 * (1 - rp), rp)
            paste(c, tx, PAD + 134, ry + (self.tip_h - tx.height) / 2 + 4 + 24 * (1 - rp), rp)
        ep = prog(t, 2.8, 0.5)
        paste(c, self.end, PAD + 20, H - SAFE_BOT - 140 + 20 * (1 - ep), ep)
        return c


def main(out):
    scenes = [PhotoCover(), LandscapeBody(), PortraitList(), TypeOnly()]
    total = sum(s.dur for s in scenes)
    cmd = [ffmpeg_tools.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", *ffmpeg_tools.h264_args("good", "medium"), "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    shots_dir = os.path.splitext(out)[0] + "_frames"
    os.makedirs(shots_dir, exist_ok=True)
    keep = {}
    elapsed = 0.0
    for si, s in enumerate(scenes):
        n = int(round(s.dur * FPS))
        for k in range(n):
            t = k / FPS
            frame = s.render(t)
            progress(frame, t, elapsed + t, total)
            proc.stdin.write(frame.convert("RGB").tobytes())
            for mark in (0.35, 0.8, 2.5):
                if abs(t - mark) < 0.5 / FPS:
                    keep[(si, mark)] = frame.convert("RGB")
        elapsed += s.dur
    proc.stdin.close()
    proc.wait()
    # 장면마다 움직임 중(0.35·0.8초)과 멈춘 뒤(2.5초) 그림을 한 장으로
    th_w, th_h = 270, 480
    sheet = Image.new("RGB", (th_w * 3 + 40, (th_h + 10) * len(scenes) + 10), "#FFFFFF")
    for (si, mark), im in keep.items():
        col = (0.35, 0.8, 2.5).index(mark)
        sheet.paste(im.resize((th_w, th_h), Image.LANCZOS), (10 + col * (th_w + 10), 10 + si * (th_h + 10)))
    sheet.save(os.path.splitext(out)[0] + "_장면.png")
    for (si, mark), im in keep.items():
        if mark == 2.5:
            im.save(os.path.join(shots_dir, f"scene{si + 1}.png"))
    return out


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else "docs/design/siman_쇼츠_타이포.mp4"))
