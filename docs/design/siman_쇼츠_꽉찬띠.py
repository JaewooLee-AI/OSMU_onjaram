"""쇼츠 '꽉 찬 띠 모양' 시안: 고정 높이 없이 내용에 맞춰 배치 + 카드의 머리말·요약 한 줄을 되살림. (그림만, 앱 연결 전)"""
import os, sys
sys.path.insert(0, os.getcwd())
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from cards import shorts_ed
from cards.design_templates import get
from cards.schema import CardSlide
from cards.fonts import display_font, korean_font, text_height, wrap_text_px
src = open("/tmp/mock/mock.py").read().split("out = sys.argv[1]")[0]; ns = {}; exec(src, ns)
scene = ns["scene"]
W, H, PAD, TOP, BOT = 1080, 1920, 56, 120, 150

def rgb(c): c = c.lstrip("#"); return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))

def title_block(text, pal, size):
    """제목 그림(*강조*), 최대 3줄. 반환: RGBA."""
    toks, em = [], False
    for seg in text.split("*"):
        parts = seg.split(" ")
        for i, p in enumerate(parts):
            if p == "":
                if toks and i > 0: toks[-1][2] = True
                continue
            toks.append([p, em, i < len(parts) - 1])
        em = not em
    f = display_font(size, text.replace("*", "")); lines, cur, cw = [], [], 0
    for t in toks:
        ww = f.getlength(t[0] + (" " if t[2] else ""))
        if cur and cw + ww > W - 2 * PAD and cur[-1][2]: lines.append(cur); cur, cw = [], 0
        cur.append(t); cw += ww
    lines.append(cur); lh = int(text_height(f) * 1.2)
    if max(sum(f.getlength(w_ + (' ' if sp else '')) for w_, e, sp in ln) for ln in lines) > W - 2 * PAD: return Image.new('RGBA', (W, 10)), 99      # 폭을 넘으면 이 크기는 못 쓴다
    img = Image.new("RGBA", (W, lh * len(lines) + 8), (0, 0, 0, 0)); d = ImageDraw.Draw(img); y = 0
    for ln in lines:
        x = PAD
        for w_, e, sp in ln:
            d.text((x, y), w_, font=f, fill=pal["soft"] if e else "#FFFFFF"); x += f.getlength(w_ + (" " if sp else ""))
        y += lh
    return img, len(lines)

def big_caption(text, pal, size, hot=None):
    """방안 3: 큰 자막(핵심 낱말 강조색)."""
    f = display_font(size, text); lines = wrap_text_px(text, f, W - 2 * PAD - 80)[:3]; lh = int(text_height(f) * 1.25)
    h = lh * len(lines) + 70
    img = Image.new("RGBA", (W, h), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    d.rounded_rectangle([PAD, 0, W - PAD, h - 1], radius=pal["cap_radius"], fill=rgb(pal["band"]) + (255,), outline=rgb(pal["line"]) + (160,), width=2)
    y = 35
    for ln in lines:
        x = (W - f.getlength(ln)) / 2
        for wd in ln.split(" "):
            d.text((x, y), wd, font=f, fill=pal["soft"] if hot and hot in wd else "#FFFFFF"); x += f.getlength(wd + " ")
        y += lh
    return img

def frame(design, series, kicker, title, media, takeaway=None, cap=None, slide=None, items=None, phone="", address="", fixed=False, bigcap=False, hot=None):
    pal = shorts_ed.full_palette(get(design))
    img = Image.new("RGB", (W, H)); px = ImageDraw.Draw(img)
    from cards.card_renderer import mix
    for y in range(H): px.line([(0, y), (W, y)], fill=mix(pal["band"], pal["deep"], min(1, y / H * 1.15)))      # 하나로 이어진 바탕
    img = img.convert("RGBA")
    avail_top, avail_bot = TOP, H - BOT - 22
    blocks = []                                             # (그림, 고정 여부)
    head = Image.new("RGBA", (W, 56), (0, 0, 0, 0)); hd = ImageDraw.Draw(head)
    f = display_font(28, series); tw = int(f.getlength(series)) + 40
    hd.rounded_rectangle([PAD, 2, PAD + tw, 54], radius=26, fill=rgb(pal["accent"]) + (255,)); hd.text((PAD + tw / 2, 28), series, font=f, fill="#FFFFFF", anchor="mm")
    hd.text((W - PAD, 28), "03 / 06", font=korean_font(26, "bold"), fill="#FFFFFF", anchor="rm")
    # 아래 블록 먼저(높이를 알아야 영상·제목 크기를 정한다)
    lower = []
    if slide is not None:
        n = shorts_ed.panel_count(slide, items or [])
        ph = min(640, max(260, n * 132 + (n - 1) * 14)) if slide.slide_type != "call_to_action" else 400
        pimg = Image.new("RGBA", (W, ph), (0, 0, 0, 0))
        for p, x, y in shorts_ed.panel_layers(slide, items or [], pal, W, ph + 1000, "/tmp/mock", f"m3{design}{slide.slide_type}", phone, address, top=1000):
            pimg.alpha_composite(Image.open(p), (x, y - 1000))
        lower.append(pimg)
    if takeaway:
        tf = display_font(50, takeaway); tl = wrap_text_px(takeaway, tf, W - 2 * PAD - 40)[:2]; lh = int(text_height(tf) * 1.25)
        t = Image.new("RGBA", (W, lh * len(tl) + 10), (0, 0, 0, 0)); td = ImageDraw.Draw(t)
        td.rounded_rectangle([PAD, 4, PAD + 9, lh * len(tl)], radius=4, fill=rgb(pal["accent"]) + (255,))
        for i, ln in enumerate(tl): td.text((PAD + 34, i * lh), ln, font=tf, fill="#FFFFFF")
        lower.append(t)
    if cap:
        if bigcap: lower.append(big_caption(cap, pal, 78, hot))
        else:
            cp = shorts_ed.caption_png(cap, "/tmp/mock/_c3.png", W, {"gold": pal["accent"], "solid": pal["band"], "cap_radius": pal["cap_radius"], "pad": PAD})
            lower.append(Image.open(cp).crop((0, 6, W, 246)))
    kick = None
    if kicker:
        kick = Image.new("RGBA", (W, 46), (0, 0, 0, 0)); kd = ImageDraw.Draw(kick)
        kd.text((PAD, 0), kicker, font=display_font(34, kicker), fill=rgb(pal["soft"]) + (255,))
    # 영상 높이: 비율 그대로(가로) / 남는 높이 안에서 전체 보이게(세로)
    gap = 30
    fixed_h = 56 + (46 if kick else 0) + sum(b.height for b in lower) + gap * (3 + len(lower) + (1 if kick else 0))
    timg, _ = title_block(title, pal, 84)
    room = (avail_bot - avail_top) - fixed_h - timg.height
    nat = int(W * media.height / media.width)
    if fixed: vh = 886
    elif nat <= room: vh = nat
    else: vh = max(480, room)
    if nat <= vh + 2 and not fixed:
        win = media.resize((W, vh), Image.LANCZOS)
    else:
        bg = ImageOps.fit(media, (W, vh), Image.LANCZOS).filter(ImageFilter.GaussianBlur(34)); bg = Image.blend(bg, Image.new("RGB", (W, vh), rgb(pal["deep"])), 0.35)
        sc = min(W / media.width, vh / media.height); fg = media.resize((int(media.width * sc), int(media.height * sc)), Image.LANCZOS)
        bg.paste(fg, ((W - fg.width) // 2, (vh - fg.height) // 2)); win = bg
    # 남는 높이로 제목을 키운다(최대 108px, 3줄)
    size = 84
    if not fixed:
        while size < 108:
            t2, n2 = title_block(title, pal, size + 4)
            if n2 > 3 or fixed_h + t2.height + vh > (avail_bot - avail_top) - 40: break
            size += 4; timg = t2
    seq = [head] + ([kick] if kick else []) + [timg, win.convert("RGBA")] + lower
    total = sum(b.height for b in seq)
    spare = (avail_bot - avail_top) - total
    if fixed:   # 예전: 위에서부터 고정 위치
        y = avail_top
        img.alpha_composite(head, (0, y)); img.alpha_composite(timg, (0, y + 84))
        img.alpha_composite(win.convert("RGBA"), (0, 430))
        cy = (430 + 886 + 22 + avail_bot) // 2 - lower[-1].height // 2
        img.alpha_composite(lower[-1], (0, cy))
    else:
        g = max(18, spare // (len(seq) - 1)); g_small = min(g, 26); y = avail_top
        extra = spare - (g_small * (2 if kick else 1)) ; rest = len(seq) - 1 - (2 if kick else 1)
        for i, b in enumerate(seq):
            img.alpha_composite(b, (0, y))
            tight = (i == 0) or (kick is not None and i == 1)       # 칩-머리말-제목은 붙여 둔다
            y += b.height + (g_small if tight else max(18, extra // max(1, rest)))
    out = img.convert("RGB"); d = ImageDraw.Draw(out)
    d.rectangle([PAD, H - BOT - 8, PAD + int((W - 2 * PAD) * 0.5), H - BOT], fill=rgb(pal["accent"]))
    return out

def sheet(frames, labels, path, cw=330):
    ch = int(cw * H / W); gap = 12; lab = 70
    s = Image.new("RGB", (len(frames) * cw + (len(frames) + 1) * gap, ch + lab + 2 * gap), "#E9E6DF"); d = ImageDraw.Draw(s)
    for i, (f, l) in enumerate(zip(frames, labels)):
        x = gap + i * (cw + gap); s.paste(f.resize((cw, ch), Image.LANCZOS), (x, gap))
        for k, line in enumerate(l.split("\n")): d.text((x + cw // 2, gap + ch + 20 + k * 24), line, font=korean_font(19, "bold"), fill="#2B2D2F", anchor="mm")
    s.save(path)

out = sys.argv[1]
for design, series, tone in (("editorial", "온자람 마음노트", 0), ("report", "온자람 소식", 1)):
    land, port = scene(1920, 1080, tone), scene(1080, 1920, tone)
    chk = CardSlide(slide_number=1, slide_type="checklist", lead_headline="x", body_content="a", takeaway="x")
    cta = CardSlide(slide_number=1, slide_type="call_to_action", lead_headline="x", body_content="", takeaway="x")
    items = ["이유 없이 가슴이 두근거리고 긴장되는 날", "몸과 마음의 에너지가 바닥난 것처럼 지칠 때", "사소한 일에도 짜증이 나고 잠들기 어려울 때", "지나간 아쉬움과 다가올 일이 걱정되어 불안해질 때"]
    T1, C1, K1 = "긴장은 *애쓰고 있다*는 신호입니다", "중요한 일을 앞두고 몸이 긴장하는 것은 자연스러운 반응입니다.", "잘 해내고 싶은 마음이 클수록 부담도 커져요"
    f = [
        frame(design, series, None, T1, land, cap=C1, fixed=True),
        frame(design, series, "마음 이야기", T1, land, takeaway=K1, cap=C1),
        frame(design, series, "마음 이야기", T1, port, takeaway=K1, cap=C1),
        frame(design, series, "마음 체크", "요즘 이런 *마음의 신호*가 있나요?", land, slide=chk, items=items),
        frame(design, series, "함께 걸어요", "혼자 안지 마세요, *온자람이 함께해요*", land, slide=cta, items=[], phone="055-255-1365", address="경남 창원시 성산구 반송로82번길 29, 1층", cap="당신의 마음이 쉬어가는 곳, 주식회사 온자람입니다."),
        frame(design, series, "마음 이야기", T1, land, cap=C1, bigcap=True, hot="긴장"),
    ]
    labels = ["지금 (가로 영상)\n고정 높이·자막만", "권장안 · 가로 영상\n머리말+요약 한 줄+자막", "권장안 · 세로 영상\n(전체 보이게)", "권장안 · 체크 목록\n(패널이 아래를 채움)", "권장안 · 상담 안내\n전화번호+자막", "방안 3 · 큰 자막\n(핵심 낱말 강조)"]
    sheet(f, labels, f"{out}/fill_{design}.png")
print("ok")
