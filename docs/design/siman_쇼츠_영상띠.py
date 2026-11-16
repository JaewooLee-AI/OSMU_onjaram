"""쇼츠 '영상 띠 모양' 시안: 위 띠(시리즈 칩·제목) + 가운데 영상 창 + 아래 띠(자막 또는 내용 패널). 앱 코드와 연결 전의 그림."""
import os, sys
sys.path.insert(0, os.getcwd())
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from cards import shorts_ed
from cards.card_renderer import mix
from cards.design_templates import get
from cards.schema import CardSlide
from cards.fonts import display_font, korean_font
src = open("/tmp/mock/mock.py").read().split("out = sys.argv[1]")[0]; ns = {}; exec(src, ns)
scene = ns["scene"]
W, H = 1080, 1920
TOP_UI, BOT_UI, PAD = 120, 240, 56

def rgb(c): c = c.lstrip("#"); return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))

def frame(design, series, title, media, mode, cap=None, slide=None, items=None, vh=820, panel_cap=False, phone="", address=""):
    pal = shorts_ed.full_palette(get(design))
    band, deep = pal["band"], pal["deep"]
    img = Image.new("RGB", (W, H), band)
    d = ImageDraw.Draw(img)
    # 위·아래 띠: 위는 브랜드 색, 아래는 한 단계 어둡게(자막이 읽히도록)
    vy = 430
    d.rectangle([0, vy + vh, W, H], fill=deep)
    d.rectangle([0, 0, W, vy - 1], fill=band)
    d.rectangle([0, vy - 6, W, vy - 1], fill=rgb(pal["accent"]))                 # 위 띠 아래 가는 포인트 선
    # 영상 창
    r = int(pal["cap_radius"] * 0.6) if pal["cap_radius"] > 20 else 8
    if mode == "crop":                                    # 창에 꽉 차게 가운데를 잘라 쓴다
        win = ImageOps.fit(media, (W, vh), Image.LANCZOS, centering=(0.5, 0.5))
    else:                                                 # 전체가 보이게: 같은 영상을 흐리게 키운 배경 위에 폭/높이를 맞춰 둔다
        bg = ImageOps.fit(media, (W, vh), Image.LANCZOS).filter(ImageFilter.GaussianBlur(34))
        bg = Image.blend(bg, Image.new("RGB", (W, vh), rgb(deep)), 0.35)
        sc = min(W / media.width, vh / media.height)
        fg = media.resize((int(media.width * sc), int(media.height * sc)), Image.LANCZOS)
        m = Image.new("L", fg.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, fg.width - 1, fg.height - 1], radius=r, fill=255)
        bg.paste(fg, ((W - fg.width) // 2, (vh - fg.height) // 2), m); win = bg
    img.paste(win, (0, vy))
    # 위 띠 글자
    chip = Image.new("RGBA", (W, H), (0, 0, 0, 0)); cd = ImageDraw.Draw(chip)
    f = display_font(28, series); tw = int(f.getlength(series)) + 40; h = 52
    cd.rounded_rectangle([PAD, TOP_UI + 6, PAD + tw, TOP_UI + 6 + h], radius=h // 2, fill=rgb(pal["accent"]) + (255,))
    cd.text((PAD + tw / 2, TOP_UI + 6 + h / 2), series, font=f, fill="#FFFFFF", anchor="mm")
    cd.text((W - PAD, TOP_UI + 32), "01 / 05", font=korean_font(26, "bold"), fill="#FFFFFF", anchor="rm")
    tp, tx, ty = shorts_ed.full_title_png("/tmp/mock/_title.png", title, pal, W, TOP_UI - 12)
    chip.alpha_composite(Image.open(tp), (0, ty + 30))
    img = img.convert("RGBA"); img.alpha_composite(chip); out = img.convert("RGB")
    # 아래 띠: 자막 또는 내용 패널
    region_top, region_bot = vy + vh + 22, H - BOT_UI - 12
    colors = {"gold": pal["accent"], "solid": band, "cap_radius": pal["cap_radius"], "pad": PAD}
    if slide is not None:
        top_p = region_top
        if panel_cap:                                      # 자막도 함께: 아래 200px을 자막에 쓰고 패널은 위쪽에
            region_bot_p = region_bot - 214
        else:
            region_bot_p = region_bot
        for p, x, y in shorts_ed.panel_layers(slide, items or [], pal, W, region_bot_p, "/tmp/mock", f"{design}{slide.slide_type}{vh}{panel_cap}", phone, address, top=top_p):
            out.paste(Image.open(p), (x, y), Image.open(p))
        if panel_cap:
            cp = shorts_ed.caption_png(cap, "/tmp/mock/_cap.png", W, colors)
            ci = Image.open(cp)
            out.paste(ci.crop((0, 40, W, 230)), (0, region_bot - 190 + 16), ci.crop((0, 40, W, 230)))
    else:
        cp = shorts_ed.caption_png(cap, "/tmp/mock/_cap.png", W, colors); ci = Image.open(cp)
        cy = (region_top + region_bot) // 2 - ci.height // 2
        out.paste(ci, (0, cy), ci)
    dd = ImageDraw.Draw(out)
    dd.rectangle([PAD, H - BOT_UI - 6, PAD + int((W - 2 * PAD) * 0.4), H - BOT_UI + 2], fill=rgb(pal["accent"]))   # 진행 막대
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
    port, land = scene(1080, 1920, tone), scene(1920, 1080, tone)
    steps = CardSlide(slide_number=1, slide_type="steps", lead_headline="x", body_content="a", takeaway="x")
    cta = CardSlide(slide_number=1, slide_type="call_to_action", lead_headline="x", body_content="", takeaway="x")
    items = ["숨을 천천히 들이쉬기", "지금 느낌 이름 붙이기", "어깨 힘 빼기"]
    f = [
        frame(design, series, "요즘 마음이 자꾸 *무겁다면*", port, "crop", "한 해의 끝자락, 마음이 바빠지는 때입니다."),
        frame(design, series, "요즘 마음이 자꾸 *무겁다면*", port, "fit", "한 해의 끝자락, 마음이 바빠지는 때입니다."),
        frame(design, series, "쉬어가도 *괜찮아요*", land, "fit", "잠시 멈추는 것도 앞으로 가는 방법이에요."),
        frame(design, series, "마음을 가라앉히는 *3단계*", port, "crop", "숨을 길게 내쉬며 어깨의 힘을 빼 봅니다.", slide=steps, items=items),
        frame(design, series, "마음을 가라앉히는 *3단계*", port, "crop", "숨을 길게 내쉬며 어깨의 힘을 빼 봅니다.", slide=steps, items=items, vh=700, panel_cap=True),
        frame(design, series, "혼자 해결하기 *어려우시다면*", port, "crop", "편하게 문의해 주세요.", slide=cta, items=[], phone="055-255-1365", address="경남 창원시 성산구 반송로82번길 29, 1층"),
    ]
    labels = ["세로 영상 · 가운데를\n잘라 꽉 채움 (안 1)", "세로 영상 · 전체가 보이게\n+ 흐린 양옆 (안 2)", "가로 영상 · 전체가 보이게\n(두 안 모두 이렇게)", "정보 장면 · 아래 띠에\n패널만 (안 A)", "정보 장면 · 패널 + 자막\n(영상 창 작아짐, 안 B)", "상담 안내 · 큰 전화번호 패널"]
    sheet(f, labels, f"{out}/band_{design}.png")
print("ok")
