"""카드뉴스 '내용 맞춤 배치' 시안 (앱 코드와 연결 전).

쇼츠 글자 중심 모양에서 쓴 원칙을 카드(4:5, 1080x1350)에 옮겨 봅니다.
  1. 내용 맞춤 배치 — 블록(머리말·제목·사진·본문·요약)을 위에서부터 쌓고, 남는 높이는 글자를 키우는 데 먼저 쓰고
     (0.85~1.35배) 나머지를 블록 사이에 고르게 나눈다. 칸 크기를 미리 정하지 않는다.
  2. 사진 모양별 배치 — 세로 사진은 본문 옆 세로 칸(사진 전체가 보임), 가로 사진은 폭 가득(사진 비율 그대로),
     사진이 없으면 큰 글자 중심.
  3. 강조어(*…*)는 글자색 대신 형광펜.
'지금' 칸은 실제 앱 렌더러(온자람 에디토리얼)로 같은 문구·같은 사진을 그린 것(저장된 PNG는 2026-11-18 적용 전 렌더러 — 지금 다시 실행하면 적용 후 모양이 나옴), '제안' 칸은 이 스크립트가 그린 것입니다.
사진은 사람 없는 합성 풍경(실제 사진 아님), 문구는 보편 심리교육 예시(사실·수치 없음). 연락처는 브랜드 킷 시드 값.

실행: python docs/design/siman_카드_맞춤.py   → docs/design/siman_카드_맞춤_사진모양.png, siman_카드_맞춤_빈공간.png
"""
import asyncio
import os
import random
import sys
import tempfile

sys.path.insert(0, os.getcwd())
os.environ.setdefault("OSMU_DATA_DIR", os.path.join(tempfile.gettempdir(), "osmu_siman_card"))

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

W, H = 1080, 1350
PAD = 64
FONT_DIR = os.path.join(os.getcwd(), "cards", "fonts")
SAGE, SAGE_DEEP, CORAL, OAT, CREAM = "#4A7C59", "#35593F", "#E07A5F", "#F0ECE1", "#FAF8F5"
TEXT, MUTED, LINE = "#2B2D2F", "#6E7378", "#E4DED2"
MARK = (224, 122, 95, 90)            # 형광펜(코랄 반투명)
SERIES = "온자람 마음노트"
PHONE, ADDRESS, EMAIL = "055-255-1365", "경남 창원시 성산구 반송로82번길 29, 1층", "onjaram@naver.com"
OUT = os.path.join(os.getcwd(), "docs", "design")


def font(size, kind="body"):
    name = {"display": "GmarketSansBold.otf", "medium": "GmarketSansMedium.otf", "body": "Pretendard-SemiBold.otf",
            "regular": "Pretendard-Medium.otf", "bold": "Pretendard-Bold.otf"}[kind]
    return ImageFont.truetype(os.path.join(FONT_DIR, name), int(size))


def rgb(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    a, b = rgb(a), rgb(b)
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---------------------------------------------------------------- 합성 사진(사람 없음)
def scene(w, h, seed=3, tree=False):
    random.seed(seed)
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=mix("#F3E3CF", "#CFE0D6", y / h))
    d = ImageDraw.Draw(img, "RGBA")
    r = int(min(w, h) * 0.10)
    sx, sy = (0.30, 0.16) if tree else (0.70, 0.24)
    d.ellipse([w * sx - r, h * sy - r, w * sx + r, h * sy + r], fill=(255, 250, 238, 235))
    for i, (c, base, amp) in enumerate([("#9DB9A4", 0.62, 0.06), ("#7FA38B", 0.72, 0.07), ("#5E8870", 0.83, 0.07)]):
        pts = [(0, h)] + [(x, h * base + amp * h * (0.5 - abs(((x / w * 3 + i * 0.37) % 1) - 0.5) * 2)) for x in range(0, w + 40, 40)] + [(w, h)]
        d.polygon(pts, fill=c)
    if tree:   # 세로 사진: 위쪽에 나무 머리(잘리면 바로 보이는 부분)
        cx = w * 0.62
        d.rectangle([cx - w * 0.03, h * 0.40, cx + w * 0.03, h * 0.86], fill="#5B4636")
        for (ox, oy, rr) in [(0, 0.22, 0.20), (-0.13, 0.30, 0.15), (0.13, 0.30, 0.15), (0, 0.36, 0.17)]:
            d.ellipse([cx + ox * w - rr * w, h * oy - rr * w, cx + ox * w + rr * w, h * oy + rr * w], fill=(62, 110, 78, 245))
        d.ellipse([cx - w * 0.05, h * 0.12, cx + w * 0.05, h * 0.12 + w * 0.10], fill=(240, 200, 120, 255))   # 나무 위 열매(맨 위 표시)
    return img.filter(ImageFilter.GaussianBlur(1.2))


# ---------------------------------------------------------------- 글자 도구
def wrap(text, f, width):
    """낱말 단위 줄바꿈(낱말이 너무 길면 글자 단위)."""
    out = []
    for para in text.split("\n"):
        cur = ""
        for wd in para.split():
            t = (cur + " " + wd).strip()
            if f.getlength(t.replace("*", "")) <= width:
                cur = t
            else:
                if cur:
                    out.append(cur)
                cur = wd
        out.append(cur)
    return out


def text_h(lines, f, lh):
    asc, desc = f.getmetrics()
    return int(len(lines) * (asc + desc) * lh)


def draw_marked(img, xy, line, f, color, em_color=None):
    """'*강조*'를 형광펜으로 칠하며 한 줄을 그린다."""
    x, y = xy
    d = ImageDraw.Draw(img, "RGBA")
    asc, desc = f.getmetrics()
    em = False
    for seg in line.split("*"):
        if seg:
            w = f.getlength(seg)
            if em:
                d.rounded_rectangle([x - 4, y + asc * 0.52, x + w + 4, y + asc + desc * 0.55], radius=6, fill=MARK)
            d.text((x, y), seg, font=f, fill=(em_color or color) if em else color)
            x += w
        em = not em


def paragraph(img, x, y, lines, f, color, lh):
    asc, desc = f.getmetrics()
    for i, ln in enumerate(lines):
        draw_marked(img, (x, y + int(i * (asc + desc) * lh)), ln, f, color)
    return y + text_h(lines, f, lh)


def rounded_paste(img, photo, box, radius=28):
    x0, y0, x1, y1 = [int(v) for v in box]
    ph = photo.resize((x1 - x0, y1 - y0), Image.LANCZOS)
    m = Image.new("L", ph.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, ph.width - 1, ph.height - 1], radius=radius, fill=255)
    img.paste(ph, (x0, y0), m)


# ---------------------------------------------------------------- 공통 머리줄·바닥글
def frame(kicker, page):
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    x = PAD
    if kicker:
        f = font(26, "bold")
        w = f.getlength(kicker)
        d.rounded_rectangle([x, 58, x + w + 32, 100], radius=21, fill=CORAL)
        d.text((x + 16, 64), kicker, font=f, fill="white")
        x += w + 48
    d.text((x, 64), SERIES, font=font(26, "bold"), fill=SAGE)
    f = font(26, "bold")
    d.text((W - PAD - f.getlength(page), 64), page, font=f, fill=MUTED)
    d.line([(PAD, 124), (W - PAD, 124)], fill=LINE, width=2)
    d.line([(PAD, H - 92), (W - PAD, H - 92)], fill=LINE, width=2)
    d.text((PAD, H - 70), "♥ 주식회사 온자람", font=font(24, "regular"), fill=MUTED)
    f = font(24, "regular")
    if page.startswith("08"):
        t, fb = f"상담 {PHONE}", font(24, "bold")
        w = fb.getlength(t)
        d.rounded_rectangle([W - PAD - w - 24, H - 74, W - PAD, H - 38], radius=8, fill=SAGE_DEEP)
        d.text((W - PAD - w - 12, H - 70), t, font=fb, fill="white")
    else:
        d.text((W - PAD - f.getlength("넘겨 보기 →"), H - 70), "넘겨 보기 →", font=f, fill=MUTED)
    return img


TOP, BOTTOM = 160, H - 128       # 내용 영역


def take_band(img, y, text, s):
    f = font(36 * s, "bold")
    h = int(96 * s)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([PAD, y, W - PAD, y + h], radius=24, fill=SAGE_DEEP)
    d.text((PAD + 36, y + (h - 36 * s * 1.2) / 2), "✓  " + text, font=f, fill="white")
    return h


def stack(img, blocks, scales=(1.35, 1.3, 1.25, 1.2, 1.15, 1.1, 1.05, 1.0, 0.95, 0.9, 0.85)):
    """blocks: [(height_fn(s), draw_fn(y, s))]. 가장 큰 배율로 쌓고 남는 높이는 블록 사이에 고르게."""
    avail = BOTTOM - TOP
    for s in scales:
        hs = [hf(s) for hf, _ in blocks]
        gap_min = int(36 * s)
        if sum(hs) + gap_min * (len(blocks) - 1) <= avail:
            break
    left = avail - sum(hs)
    gap = min(left / max(1, len(blocks) - 1), 110)
    y = TOP + (left - gap * (len(blocks) - 1)) / 2          # 다 쓰고도 남으면 위아래 가운데
    for (hf, dfn), h in zip(blocks, hs):
        dfn(int(y), s)
        y += h + gap
    return s


def title_block(img, text, base=74, width=W - 2 * PAD, color=SAGE_DEEP, x=PAD):
    def lines(s):
        return wrap(text, font(base * s, "display"), width)

    def hf(s):
        return text_h(lines(s), font(base * s, "display"), 1.28)

    def dfn(y, s):
        paragraph(img, x, y, lines(s), font(base * s, "display"), color, 1.28)
    return hf, dfn


def body_block(img, text, base=40, width=W - 2 * PAD, x=PAD, color=TEXT):
    def lines(s):
        return wrap(text, font(base * s, "regular"), width)

    def hf(s):
        return text_h(lines(s), font(base * s, "regular"), 1.6)

    def dfn(y, s):
        paragraph(img, x, y, lines(s), font(base * s, "regular"), color, 1.6)
    return hf, dfn


def take_block(img, text):
    return (lambda s: int(96 * s)), (lambda y, s: take_band(img, y, text, s))


# ---------------------------------------------------------------- 제안 카드
BODY_T = "지친 마음에도 *이유*가 있어요"
BODY_B = "해야 할 일이 쌓이면 누구나 마음이 지칩니다.\n지친 마음은 게으름이 아니라 쉬어 가라는 신호예요.\n잠깐 멈추고 오늘 나에게 필요한 것을 물어보세요."
BODY_K = "당신 잘못이 아니에요"


def new_body_portrait(photo):
    """세로 사진: 제목은 폭 전체, 그 아래 [본문 | 사진 전체가 보이는 세로 칸]."""
    img = frame("", "02 / 08")
    pw = 400

    def row_h(s):
        bh = body_block(img, BODY_B, 38, W - 2 * PAD - pw - 40)[0](s)
        return max(bh, int(pw * photo.height / photo.width))

    def row_draw(y, s):
        ph = int(pw * photo.height / photo.width)
        bh = body_block(img, BODY_B, 38, W - 2 * PAD - pw - 40)[0](s)
        body_block(img, BODY_B, 38, W - 2 * PAD - pw - 40)[1](y + max(0, (ph - bh) // 2), s)
        rounded_paste(img, photo, (W - PAD - pw, y, W - PAD, y + ph))
    stack(img, [title_block(img, BODY_T), (row_h, row_draw), take_block(img, BODY_K)])
    return img


def new_body_landscape(photo):
    """가로 사진: 폭 가득, 사진 비율 그대로(잘리지 않음)."""
    img = frame("", "02 / 08")
    full_w = W - 2 * PAD
    cap = int((BOTTOM - TOP) * 0.42)

    def ph_h(s):
        return min(cap, int(full_w * photo.height / photo.width))

    def ph_draw(y, s):
        h = ph_h(s)
        w = int(h * photo.width / photo.height)
        x = PAD + (full_w - w) // 2
        rounded_paste(img, photo, (x, y, x + w, y + h))
    stack(img, [title_block(img, BODY_T), (ph_h, ph_draw), body_block(img, BODY_B, 40), take_block(img, BODY_K)])
    return img


def new_body_text():
    """사진 없음: 큰 글자 중심(형광펜 강조 + 큰 따옴표 장식)."""
    img = frame("", "02 / 08")
    d = ImageDraw.Draw(img)

    def rule(s):
        return int(8 * s)

    def rule_draw(y, s):
        d.rounded_rectangle([PAD, y, PAD + 120, y + 8], radius=4, fill=CORAL)
    stack(img, [title_block(img, BODY_T, 84), (rule, rule_draw), body_block(img, BODY_B, 46), take_block(img, BODY_K)])
    return img


QA_T = "상담은 꼭 힘들어야 받나요?"
QA_A = "아니요. 마음을 미리 돌보는 것도 좋은 이유가 됩니다.\n특별한 일이 없어도 요즘 내 마음이 어떤지 이야기 나눌 수 있어요."


def new_qa():
    img = frame("묻고 답하기", "05 / 08")
    d = ImageDraw.Draw(img)

    def mark(y, s, letter, fill):
        r = 40
        d.ellipse([PAD, y, PAD + 2 * r, y + 2 * r], fill=fill)
        f = font(42, "display")
        d.text((PAD + r - f.getlength(letter) / 2, y + r - 24), letter, font=f, fill="white")
        return 2 * r

    tw = W - 2 * PAD - 110
    q_hf, q_df = title_block(img, QA_T, 70, tw, x=PAD + 110)
    a_hf, a_df = body_block(img, QA_A, 44, tw, x=PAD + 110)

    def q_draw(y, s):
        mark(y, s, "Q", CORAL)
        q_df(y + 6, s)

    def line_h(s):
        return 2

    def line_draw(y, s):
        d.line([(PAD, y), (W - PAD, y)], fill=LINE, width=2)

    def a_draw(y, s):
        mark(y, s, "A", SAGE)
        a_df(y + 10, s)
    stack(img, [(lambda s: max(q_hf(s) + 6, int(88 * s)), q_draw),
                (line_h, line_draw), (lambda s: max(a_hf(s) + 10, int(88 * s)), a_draw), take_block(img, "편하게 문의하세요")])
    return img


def new_big_number():
    img = frame("숫자로 보기", "07 / 08")
    d = ImageDraw.Draw(img)
    items = ["숨을 천천히 고르기", "마음을 적어 보기", "어깨 힘 빼기"]

    def num_h(s):
        return int(300 * s)

    def num_draw(y, s):
        f = font(300 * s, "display")
        d.text((PAD - 8, y - 30 * s), "3", font=f, fill=CORAL)
        x = PAD + f.getlength("3") + 24
        d.text((x, y + 70 * s), "가지", font=font(96 * s, "display"), fill=CORAL)
        d.text((x, y + 190 * s), "오늘의 작은 실천", font=font(42 * s, "bold"), fill=TEXT)

    def chips_h(s):
        return len(items) * int(96 * s) + (len(items) - 1) * int(18 * s)

    def chips_draw(y, s):
        for i, it in enumerate(items):
            yy = y + i * (int(96 * s) + int(18 * s))
            d.rounded_rectangle([PAD, yy, W - PAD, yy + int(96 * s)], radius=22, fill=OAT)
            d.text((PAD + 32, yy + 24 * s), f"{i + 1:02d}", font=font(40 * s, "display"), fill=SAGE)
            d.text((PAD + 120 * s, yy + 24 * s), it, font=font(42 * s, "bold"), fill=TEXT)
    stack(img, [title_block(img, "숫자로 보는 *마음 돌봄*", 70), (num_h, num_draw), (chips_h, chips_draw), take_block(img, "하나만 해도 충분해요")])
    return img


EVENT_ROWS = [("일시", "예시 일정"), ("장소", "예시 장소"), ("대상", "누구나"), ("신청", "전화 · 이메일")]


def new_event():
    img = frame("안내", "06 / 08")
    d = ImageDraw.Draw(img)

    def rows_h(s):
        return len(EVENT_ROWS) * int(118 * s)

    def rows_draw(y, s):
        rh = int(118 * s)
        for i, (k, v) in enumerate(EVENT_ROWS):
            yy = y + i * rh
            d.rounded_rectangle([PAD, yy + 10, PAD + int(150 * s), yy + rh - 10], radius=18, fill=SAGE)
            f = font(38 * s, "bold")
            d.text((PAD + int(75 * s) - f.getlength(k) / 2, yy + rh / 2 - 24 * s), k, font=f, fill="white")
            d.text((PAD + int(190 * s), yy + rh / 2 - 28 * s), v, font=font(48 * s, "bold"), fill=TEXT)
            if i < len(EVENT_ROWS) - 1:
                d.line([(PAD, yy + rh), (W - PAD, yy + rh)], fill=LINE, width=2)
    stack(img, [title_block(img, "마음 돌봄 *프로그램* 안내", 74), body_block(img, "누구나 편하게 참여할 수 있는 마음 돌봄 시간입니다.", 40),
                (rows_h, rows_draw), take_block(img, "자세한 내용은 문의 주세요")])
    return img


def new_cta():
    img = frame("함께 걸어요", "08 / 08")
    d = ImageDraw.Draw(img)

    def card_h(s):
        return int(400 * s)

    def card_draw(y, s):
        h = card_h(s)
        d.rounded_rectangle([PAD, y, W - PAD, y + h], radius=32, fill=SAGE_DEEP)
        d.text((PAD + 48, y + 40 * s), "상담 문의", font=font(34 * s, "bold"), fill="#B9D1BF")
        size = 118 * s
        while font(size, "display").getlength(PHONE) > W - 2 * PAD - 96:
            size -= 2
        d.text((PAD + 44, y + 92 * s), PHONE, font=font(size, "display"), fill="white")
        d.text((PAD + 48, y + 250 * s), ADDRESS, font=font(32 * s, "regular"), fill="#EFEBE4")
        d.text((PAD + 48, y + 300 * s), EMAIL, font=font(32 * s, "regular"), fill="#EFEBE4")
    stack(img, [title_block(img, "혼자 해결하기 *어려우시다면*", 78), body_block(img, "편하게 문의해 주세요.", 44), (card_h, card_draw)])
    return img


# ---------------------------------------------------------------- '지금' 칸: 실제 렌더러
def current_cards(photos):
    from cards import preview
    from cards.card_renderer import CardNewsRendererService
    from cards.schema import MediaAsset
    from core.brand_seed import seed_if_empty
    seed_if_empty()
    tmp = tempfile.mkdtemp()
    out = {}

    def render(key, arche, h, b, t, photo=None, **extra):
        asset = MediaAsset(id="A1", kind="image", source="user", path="")
        if photo is not None:
            p = os.path.join(tmp, f"{key}.png")
            photo.save(p)
            asset = MediaAsset(id="A1", kind="image", source="user", path=p)
        sb = preview._storyboard([(arche, "")], "editorial", asset)
        sl = sb.card_slides[0]
        sl.lead_headline, sl.body_content, sl.takeaway = h, b, t
        sl.asset_id = "A1" if photo is not None else None
        for k, v in extra.items():
            setattr(sl, k, v)
        if photo is None:
            sb.assets = []
        r = CardNewsRendererService(export_dir=os.path.join(tmp, key))
        path = asyncio.run(r.render_all_slides(sb))[0]
        out[key] = Image.open(path).convert("RGB")

    render("portrait", "body", BODY_T, BODY_B, BODY_K, photos["portrait"])
    render("landscape", "body", BODY_T, BODY_B, BODY_K, photos["landscape"])
    render("text", "body", BODY_T, BODY_B, BODY_K, None)
    render("qa", "qa", QA_T, QA_A, "편하게 문의하세요")
    render("big", "big_number", "숫자로 보는 *마음 돌봄*", "1. 숨을 천천히 고르기\n2. 마음을 적어 보기\n3. 어깨 힘 빼기", "하나만 해도 충분해요",
           stat_value="3가지", stat_label="오늘의 작은 실천")
    render("event", "event_info", "마음 돌봄 *프로그램* 안내",
           "누구나 편하게 참여할 수 있는 마음 돌봄 시간입니다.\n" + "\n".join(f"{k}: {v}" for k, v in EVENT_ROWS), "자세한 내용은 문의 주세요")
    render("cta", "call_to_action", "혼자 해결하기 *어려우시다면*", "편하게 문의해 주세요.", "상담 문의")
    return out


# ---------------------------------------------------------------- 모음 그림
def sheet(columns, path, title):
    cw, ch, gap, top, side = 432, 540, 28, 150, 110
    sw = side + len(columns) * (cw + gap) + gap
    sh = top + 2 * (ch + 60) + 30
    img = Image.new("RGB", (sw, sh), "#E9E6E0")
    d = ImageDraw.Draw(img)
    d.text((gap, 30), title, font=font(40, "bold"), fill=TEXT)
    for r, label in enumerate(["지금", "제안"]):
        y = top + r * (ch + 60) + 40
        d.text((gap, y + ch / 2 - 24), label, font=font(40, "display"), fill=CORAL if r else MUTED)
    for i, (head, before, after) in enumerate(columns):
        x = side + gap + i * (cw + gap)
        d.text((x, top - 10), head, font=font(30, "bold"), fill=TEXT)
        for r, card in enumerate([before, after]):
            y = top + r * (ch + 60) + 40
            img.paste(card.resize((cw, ch), Image.LANCZOS), (x, y))
    img.save(path, optimize=True)
    print("saved", path)


def main():
    photos = {"portrait": scene(900, 1200, seed=5, tree=True), "landscape": scene(1600, 900, seed=3)}
    cur = current_cards(photos)
    sheet([("세로 사진", cur["portrait"], new_body_portrait(photos["portrait"])),
           ("가로 사진", cur["landscape"], new_body_landscape(photos["landscape"])),
           ("사진 없음", cur["text"], new_body_text())],
          os.path.join(OUT, "siman_카드_맞춤_사진모양.png"), "본문 카드 — 사진 모양에 따라 배치 (같은 문구·같은 사진)")
    sheet([("묻고 답하기", cur["qa"], new_qa()), ("큰 숫자", cur["big"], new_big_number()),
           ("행사 안내", cur["event"], new_event()), ("상담 안내", cur["cta"], new_cta())],
          os.path.join(OUT, "siman_카드_맞춤_빈공간.png"), "빈 공간이 컸던 카드 — 내용 맞춤 배치 (같은 문구)")


if __name__ == "__main__":
    main()
