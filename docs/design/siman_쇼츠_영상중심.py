"""쇼츠 영상 중심 모양 시안(그림만 — 앱 코드와 연결 전). 사람·실제 사진 없이 합성한 풍경을 영상 한 장면으로 가정."""
import os, sys, random
sys.path.insert(0, os.getcwd())
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from cards.fonts import display_font, korean_font, text_height, wrap_text_px
from cards.card_renderer import mix

W, H = 1080, 1920
SAFE_TOP, SAFE_BOTTOM, CAP_H = 120, 240, 250
TRACKS = {
    "empathy": dict(name="공감·회복", series="온자람 마음노트", deep="#1B2A20", band="#35593F", accent="#E8836A", line="#B9D1BF", radius=26),
    "trust":   dict(name="전문·신뢰", series="온자람 소식", deep="#13233A", band="#2C4A6F", accent="#E8836A", line="#9DB4D0", radius=10),
}

def scene(w, h, tone=0):
    """차분한 합성 풍경(창가의 빛·언덕·식물). 사람 없음."""
    random.seed(7 + tone)
    sky = [("#F3E3CF", "#CFE0D6"), ("#E7ECF3", "#BFD0E3")][tone]
    img = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(img)
    for y in range(h):
        px.line([(0, y), (w, y)], fill=mix(sky[0], sky[1], y / h))
    d = ImageDraw.Draw(img, "RGBA")
    r = int(min(w, h) * 0.13)
    d.ellipse([w * 0.66 - r, h * 0.20 - r, w * 0.66 + r, h * 0.20 + r], fill=(255, 250, 238, 235))
    for i, (c, base, amp) in enumerate([("#9DB9A4", 0.58, 0.07), ("#7FA38B", 0.68, 0.08), ("#5E8870", 0.80, 0.09)]):
        pts = [(0, h)]
        for x in range(0, w + 40, 40):
            pts.append((x, h * base + amp * h * (0.5 - abs(((x / w * 2 + i * 0.37) % 1) - 0.5) * 2)))
        pts.append((w, h))
        d.polygon(pts, fill=c)
    for k in range(9):          # 식물 잎
        x = w * (0.1 + 0.1 * k); y = h * 0.93
        d.ellipse([x - w * 0.05, y - h * 0.09, x + w * 0.05, y + h * 0.02], fill=(48, 86, 62, 190))
    return img.filter(ImageFilter.GaussianBlur(2.2))

def fill_cover(src, w, h):
    return ImageOps.fit(src, (w, h), Image.LANCZOS, centering=(0.5, 0.5))

def grad(w, h, rgb, a0, a1):
    """위→아래로 투명도가 a0→a1로 변하는 색 띠."""
    ramp = Image.linear_gradient("L").resize((w, h))
    alpha = ramp.point(lambda v: int(a0 + (a1 - a0) * v / 255))
    layer = Image.new("RGBA", (w, h), rgb + (255,)); layer.putalpha(alpha)
    return layer

def hexrgb(c): c = c.lstrip("#"); return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))

def title_lines(draw, text, x, y, width, size, color, accent):
    """제목(*강조어* 표시) 최대 2줄. 낱말 단위 줄바꿈, 강조 경계에서는 공백을 넣지 않는다."""
    toks, emph = [], False
    for seg in text.split("*"):
        parts = seg.split(" ")
        for i, p in enumerate(parts):
            if p == "":
                if toks and i > 0: toks[-1][2] = True
                continue
            toks.append([p, emph, i < len(parts) - 1])     # [글자, 강조, 뒤에 공백]
        emph = not emph
    font = display_font(size, text.replace("*", ""))
    lines, cur, cw = [], [], 0
    for t in toks:
        ww = font.getlength(t[0] + (" " if t[2] else ""))
        if cur and cw + ww > width and cur[-1][2]:
            lines.append(cur); cur, cw = [], 0
        cur.append(t); cw += ww
    lines.append(cur)
    lh = int(text_height(font) * 1.22)
    for line in lines[:2]:
        xx = x
        for wd, em, sp in line:
            draw.text((xx, y), wd, font=font, fill=accent if em else color)
            xx += font.getlength(wd + (" " if sp else ""))
        y += lh
    return y

def pill(draw, x, y, text, fill, ink, size=28):
    f = korean_font(size, "bold"); tw = int(f.getlength(text)) + 40; h = size + 24
    draw.rounded_rectangle([x, y, x + tw, y + h], radius=h // 2, fill=fill)
    draw.text((x + tw / 2, y + h / 2), text, font=f, fill=ink, anchor="mm")
    return h

def caption(img, tk, text, idx, total):
    """아래 큰 자막 띠(UI 가림 영역 바로 위) + 진행 막대."""
    d = ImageDraw.Draw(img, "RGBA")
    y1 = H - SAFE_BOTTOM; y0 = y1 - CAP_H; pad = 56
    d.rounded_rectangle([pad, y0 + 20, W - pad, y1 - 20], radius=tk["radius"], fill=hexrgb(tk["band"]) + (238,), outline=hexrgb(tk["line"]) + (200,), width=2)
    f = display_font(56, text)
    lines = wrap_text_px(text, f, W - 2 * pad - 80)[:2]
    lh = int(text_height(f) * 1.28); ty = (y0 + y1) // 2 - lh * len(lines) // 2
    for ln in lines:
        d.text((W // 2, ty + lh // 2), ln, font=f, fill="#FFFFFF", anchor="mm"); ty += lh
    d.rectangle([pad, y1 + 4, pad + int((W - 2 * pad) * (idx + 1) / total), y1 + 12], fill=tk["accent"])

def video_scene(tk, frame, title, cap, idx, total, landscape=False):
    base = fill_cover(frame, W, H)
    if landscape:
        bg = base.filter(ImageFilter.GaussianBlur(38))
        bg = Image.blend(bg, Image.new("RGB", (W, H), hexrgb(tk["deep"])), 0.42)
        fw, fh = W, int(W * frame.height / frame.width)
        fg = frame.resize((fw, fh), Image.LANCZOS)
        mask = Image.new("L", (fw, fh), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw - 1, fh - 1], radius=tk["radius"], fill=255)
        cy = (SAFE_TOP + 330 + (H - SAFE_BOTTOM - CAP_H - 40)) // 2
        bg.paste(fg, (0, cy - fh // 2), mask)
        img = bg.convert("RGBA")
    else:
        img = base.convert("RGBA")
    img.alpha_composite(grad(W, 640, hexrgb(tk["deep"]), 235, 0), (0, 0))                        # 위 그라데이션
    img.alpha_composite(grad(W, 760, hexrgb(tk["deep"]), 0, 235), (0, H - 760))                  # 아래 그라데이션
    d = ImageDraw.Draw(img, "RGBA")
    pill(d, 56, SAFE_TOP, tk["series"], hexrgb(tk["accent"]) + (255,), "#FFFFFF")
    pg = f"{idx + 1:02d} / {total:02d}"; pf = korean_font(26, "bold")
    d.text((W - 56, SAFE_TOP + 26), pg, font=pf, fill="#FFFFFF", anchor="rm")
    title_lines(d, title, 56, SAFE_TOP + 84, W - 112, 76, "#FFFFFF", "#FFC2B2")
    out = img.convert("RGB"); caption(out, tk, cap, idx, total)
    return out

def info_scene(tk, kind, idx, total):
    """정보 장면(지금의 카드 모양 유지, 남는 자리만큼 칸을 키움): 단계 목록 / 상담 안내."""
    img = Image.new("RGB", (W, H), hexrgb("#FAF8F5")); d = ImageDraw.Draw(img, "RGBA")
    deep = hexrgb(tk["band"]); top = SAFE_TOP + 70
    d.rectangle([0, SAFE_TOP - 20, W, SAFE_TOP + 70], fill=deep)
    d.text((56, SAFE_TOP + 25), tk["series"], font=korean_font(28, "bold"), fill="#FFFFFF", anchor="lm")
    d.text((W - 56, SAFE_TOP + 25), f"{idx + 1:02d} / {total:02d}", font=korean_font(26, "bold"), fill="#FFFFFF", anchor="rm")
    bottom = H - SAFE_BOTTOM - CAP_H - 40
    if kind == "steps":
        y = title_lines(d, "마음을 가라앉히는 *3단계*", 56, top + 50, W - 112, 78, deep, hexrgb(tk["accent"])) + 30
        n, gap = 3, 28; rh = (bottom - y - gap * (n - 1)) // n
        for i, t in enumerate(["숨을 천천히 들이쉬기", "지금 느낌 이름 붙이기", "어깨 힘 빼기"]):
            d.rounded_rectangle([56, y, W - 56, y + rh], radius=tk["radius"], fill="#F0ECE1")
            d.rectangle([56, y + 24, 64, y + rh - 24], fill=hexrgb(tk["accent"]) if i == 0 else deep)
            d.rounded_rectangle([96, y + rh // 2 - 48, 192, y + rh // 2 + 48], radius=18, fill=deep)
            d.text((144, y + rh // 2), f"{i + 1:02d}", font=display_font(46, "01"), fill="#FFFFFF", anchor="mm")
            d.text((232, y + rh // 2), t, font=display_font(60, t), fill=deep, anchor="lm")
            y += rh + gap
        cap = "숨을 길게 내쉬며 어깨의 힘을 빼 봅니다."
    else:
        y = title_lines(d, "혼자 해결하기 *어려우시다면*", 56, top + 50, W - 112, 78, deep, hexrgb(tk["accent"])) + 40
        d.text((56, y + 30), "편하게 문의해 주세요.", font=korean_font(52, "medium"), fill="#3B4650", anchor="lm")
        y += 100; bh = bottom - y
        d.rounded_rectangle([56, y, W - 56, bottom], radius=tk["radius"], fill=deep)
        d.rectangle([56, y + 30, 66, bottom - 30], fill=hexrgb(tk["accent"]))
        d.text((110, y + bh * 0.22), "상담 문의", font=korean_font(38, "bold"), fill="#DCE8DF", anchor="lm")
        ph = "055-255-1365"; size = 140
        while display_font(size, ph).getlength(ph) > W - 110 - 90 and size > 60: size -= 4
        d.text((110, y + bh * 0.50), ph, font=display_font(size, ph), fill="#FFFFFF", anchor="lm")
        d.text((110, y + bh * 0.80), "경남 창원시 성산구 반송로82번길 29, 1층", font=korean_font(34, "medium"), fill="#DCE8DF", anchor="lm")
        cap = "혼자 해결하기 어려우시다면, 편하게 문의해 주세요."
    caption(img, tk, cap, idx, total)
    return img

def sheet(frames, labels, path, cw=360):
    ch = int(cw * H / W); gap = 14; lab = 46
    s = Image.new("RGB", (len(frames) * cw + (len(frames) + 1) * gap, ch + lab + 2 * gap), "#E9E6DF")
    d = ImageDraw.Draw(s)
    for i, (f, l) in enumerate(zip(frames, labels)):
        x = gap + i * (cw + gap)
        s.paste(f.resize((cw, ch), Image.LANCZOS), (x, gap))
        d.text((x + cw // 2, gap + ch + lab // 2), l, font=korean_font(21, "bold"), fill="#2B2D2F", anchor="mm")
    s.save(path); return s

out = sys.argv[1]
port, land = scene(W, H, 0), scene(1920, 1080, 0)
rows = []
for key in ("empathy", "trust"):
    tk = TRACKS[key]
    tone = 0 if key == "empathy" else 1
    p = scene(W, H, tone)
    frames = [
        video_scene(tk, p, "요즘 마음이 자꾸 *무겁다면*", "한 해의 끝자락, 마음이 바빠지는 때입니다.", 0, 5),
        video_scene(tk, p, "긴장은 *애쓰고 있다*는 신호", "긴장은 애쓰고 있다는 신호입니다.", 1, 5),
        info_scene(tk, "steps", 2, 5),
        video_scene(tk, scene(1920, 1080, tone), "쉬어가도 *괜찮아요*", "잠시 멈추는 것도 앞으로 가는 방법이에요.", 3, 5, landscape=True),
        info_scene(tk, "cta", 4, 5),
    ]
    labels = ["① 표지 · 세로 영상 꽉 채움", "② 본문 · 세로 영상", "③ 정보 장면(카드 모양 유지)", "④ 가로 영상 · 흐린 배경", "⑤ 상담 안내(큰 전화번호)"]
    sheet(frames, labels, f"{out}/mock_{key}.png")
    for i, f in enumerate(frames): f.save(f"{out}/{key}_{i}.png")
print("ok")
