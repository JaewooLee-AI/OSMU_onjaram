"""온자람 전용 레이아웃(`oj`) — 브랜드 킷 문서(info/ 브랜드킷 분석)의 비주얼 규칙을 카드로 옮긴 모양입니다.

- 바탕은 웜 크림(60%), 주조색은 세이지 그린(공감·회복) 또는 딥 네이비(전문·신뢰)(30%), 코랄은 핵심어·예약 유도에만(10%).
- 모든 카드에 같은 고정 요소: 위 왼쪽 카테고리 태그, 위 오른쪽 쪽수, 아래 워터마크("마음성장파트너 (주)온자람")·연락처.
- 변형(`design.variant`): warm(공감·회복: 세리프 제목·둥근 모양) / trust(전문·신뢰: 굵은 고딕 제목·번호 칸·사회적기업 인증 배지).
- 마지막 안내(`call_to_action`) 카드는 전화번호를 크게 보여 주는 코랄 버튼, 네이버 예약 알약, 사용자가 올린 QR 이미지(선택),
  할인 배지(선택)를 한 장에 배치합니다. QR은 카드 다듬기에서 카드마다 올리고, 없으면 그리지 않습니다.
- 사실은 문서에 있는 것만 씁니다: 사회적기업 인증 제2025-139호, 네이버 예약 가능. 홈페이지·예약 주소는 비어 있으면 그리지 않습니다.
"""
from __future__ import annotations

import os
import re
from typing import List, Optional

from PIL import Image, ImageDraw

from cards.fonts import display_font, korean_font, text_height, wrap_text_px

CERT_BADGE = "사회적기업 인증 제2025-139호"      # 브랜드 킷 문서·팩트 목록에 있는 값
CATEGORY_COVER = "온자람 마음노트"                 # 브랜드 킷 문서의 카드뉴스 카테고리 태그
WATERMARK = "마음성장파트너 (주)온자람"             # 브랜드 킷 문서의 워터마크 문구
CHARCOAL = "#2B2D2F"                              # 본문 글자(순검정 대신)
MUTED = "#6E7378"                                 # 보조 글자
QR_SIDE = 300                                      # 마지막 안내 카드의 QR 한 변(px) — 카드 폭의 28%
TEXT_TYPES = ("cover", "body", "qa", "quote", "single")
GRID_TYPES = ("numbered", "steps")


def _items(body: str, limit: int = 6) -> List[str]:
    out = []
    for raw in (body or "").replace("\\n", "\n").split("\n"):
        line = re.sub(r"^\s*(?:[-•·*]|\d+[.)])\s*", "", raw).strip()
        if line:
            out.append(line)
    return out[:limit]


def load_qr_image(path: str) -> Optional[Image.Image]:
    """사용자가 올린 QR 이미지. 알파가 있으면 흰 바탕에 얹고, 읽을 수 없으면 None."""
    try:
        if not path or not os.path.exists(path):
            return None
        im = Image.open(path)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, "#FFFFFF")
            bg.paste(im, mask=im.split()[-1])
            return bg
        return im.convert("RGB")
    except Exception:  # noqa: BLE001 — 깨진 파일 하나가 카드를 막지 않게
        return None


class OnjaramLayoutMixin:
    """CardNewsRendererService에 섞어 쓰는 온자람 레이아웃."""

    # ------------------------------------------------------------------ 공통 틀
    def _oj_palette(self, ctx):
        from cards.card_renderer import mix, tint
        c = ctx.c
        return {
            "bg": c.background, "title": c.primary, "main": c.secondary, "accent": c.accent,
            "soft": tint(c.secondary, 0.88), "oat": mix(c.background, "#E8E2D0", 0.65), "line": tint(c.secondary, 0.7),
        }

    def _oj_frame(self, img, draw, ctx, pal) -> tuple:
        """위 태그·쪽수, 아래 워터마크·연락처를 그리고 본문이 들어갈 (위, 아래) y를 돌려준다."""
        W, H, M = self.WIDTH, self.HEIGHT, self.MARGIN
        trust = ctx.design.variant == "trust"
        t = ctx.slide.slide_type
        label = (getattr(ctx.el, "series_label", "") or CATEGORY_COVER) if t == "cover" else self.TYPE_NAMES.get(t, "핵심 포인트")
        font = korean_font(30, "bold")
        w = int(font.getlength(label)) + 44
        draw.rounded_rectangle([M, 52, M + w, 52 + 54], radius=27 if not trust else 12, fill=pal["main"])
        draw.text((M + w / 2, 52 + 27), label, font=font, fill="#FFFFFF", anchor="mm")
        page = f"{ctx.index + 1} / {ctx.total}"
        draw.text((W - M, 52 + 27), page, font=korean_font(30, "medium"), fill=MUTED, anchor="rm")
        # 아래: 가는 선 + 워터마크 + 연락처
        fy = H - 74
        draw.line([(M, fy - 40), (W - M, fy - 40)], fill=pal["line"], width=2)
        name = WATERMARK if "온자람" in (ctx.kit.brand_name or "") else (ctx.kit.brand_name or "")
        if name:
            draw.text((M, fy), name, font=korean_font(30, "semibold"), fill=pal["title"], anchor="lm")
        if ctx.el.show_phone and ctx.kit.phone:
            draw.text((W - M, fy), f"상담 {ctx.kit.phone}", font=korean_font(32, "bold"), fill=pal["title"], anchor="rm")
        return 150, fy - 60

    def _oj_round_photo(self, img, photo: Image.Image, box, radius: int) -> None:
        x0, y0, x1, y1 = box
        fitted = self._cover_fit(photo, x1 - x0, y1 - y0).convert("RGB")
        mask = Image.new("L", fitted.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fitted.width - 1, fitted.height - 1], radius=radius, fill=255)
        img.paste(fitted, (x0, y0), mask)

    def _oj_title(self, draw, ctx, pal, y: int, start: int, minimum: int, max_lines: int, color: Optional[str] = None) -> int:
        """제목(강조어는 코랄 글씨). 그린 뒤의 y를 돌려준다."""
        M, W = self.MARGIN, self.WIDTH
        return self._emph_title(draw, ctx, y, int(start * ctx.title_scale), minimum, max_lines, x=M, width=W - 2 * M,
                                color=color or pal["title"], emph_color=pal["accent"])

    def _oj_takeaway(self, draw, ctx, pal, y_bottom: int) -> None:
        """아래 한 줄 요약 띠(주조색 바탕 + 흰 글씨). y_bottom 바로 위에 붙인다."""
        text = (ctx.slide.takeaway or "").strip()
        if not text:
            return
        M, W = self.MARGIN, self.WIDTH
        font, lines = self._fit_lines(text, W - 2 * M - 72, int(46 * ctx.takeaway_scale), 28, 2, "bold")
        lh = int(text_height(font) * 1.25)
        h = lh * len(lines) + 44
        y0 = y_bottom - h
        draw.rounded_rectangle([M, y0, W - M, y_bottom], radius=22 if ctx.design.variant == "warm" else 10, fill=pal["main"])
        ty = y0 + 22
        for line in lines:
            draw.text((W / 2, ty), line, font=font, fill="#FFFFFF", anchor="ma")
            ty += lh

    def _oj_cert(self, draw, ctx, pal, y: int) -> None:
        """사회적기업 인증 배지(전문·신뢰형 표지·마지막 카드)."""
        font = korean_font(28, "semibold")
        w = int(font.getlength(CERT_BADGE)) + 70
        x = self.MARGIN
        draw.rounded_rectangle([x, y, x + w, y + 52], radius=26, outline=pal["main"], width=3)
        draw.ellipse([x + 16, y + 14, x + 40, y + 38], fill=pal["main"])
        draw.text((x + 28, y + 26), "✓", font=korean_font(20, "bold"), fill="#FFFFFF", anchor="mm")
        draw.text((x + 52, y + 26), CERT_BADGE, font=font, fill=pal["main"], anchor="lm")

    # ------------------------------------------------------------------ 진입점
    def _layout_oj(self, ctx, photo: Optional[Image.Image]) -> Image.Image:
        W, H = self.WIDTH, self.HEIGHT
        pal = self._oj_palette(ctx)
        img = Image.new("RGB", (W, H), pal["bg"])
        draw = ImageDraw.Draw(img)
        top, bottom = self._oj_frame(img, draw, ctx, pal)
        t = ctx.slide.slide_type
        if t == "cover":
            self._oj_cover(img, draw, ctx, pal, photo, top, bottom)
        elif t == "call_to_action":
            self._oj_cta(img, draw, ctx, pal, top, bottom)
        elif t in GRID_TYPES:
            self._oj_steps(img, draw, ctx, pal, top, bottom)
        elif t == "checklist":
            self._oj_checklist(img, draw, ctx, pal, top, bottom)
        elif t in ("big_number", "event_info", "comparison_table"):
            self._oj_panel_card(img, draw, ctx, pal, top, bottom)
        else:
            self._oj_text_card(img, draw, ctx, pal, photo, top, bottom)
        return img

    # ------------------------------------------------------------------ 종류별
    def _oj_cover(self, img, draw, ctx, pal, photo, top, bottom) -> None:
        W, M = self.WIDTH, self.MARGIN
        trust = ctx.design.variant == "trust"
        if photo is None:   # 사진이 없으면 연한 원 두 개로 분위기만 낸다
            draw.ellipse([W - 420, top + 40, W + 120, top + 580], fill=pal["soft"])
            draw.ellipse([W - 260, top + 380, W + 60, top + 700], fill=mix_hex(pal["soft"], pal["accent"], 0.18))
        y = top + 40
        y = self._oj_title(draw, ctx, pal, y, 104 if not trust else 92, 54, 4)
        take = (ctx.slide.takeaway or "").strip()
        if take:
            y += 24
            draw.rounded_rectangle([M - 30, y + 6, M - 20, y + 62], radius=5, fill=pal["accent"])
            font, lines = self._fit_lines(take, W - 2 * M - 40, int(44 * ctx.takeaway_scale), 28, 2, "semibold")
            lh = int(text_height(font) * 1.3)
            ty = y
            for line in lines:
                draw.text((M + 30, ty), line, font=font, fill=pal["main"])
                ty += lh
            y = ty
        if photo is not None:
            py0 = max(y + 36, bottom - 520)
            if bottom - py0 >= 220:
                self._oj_round_photo(img, photo, (M, py0, W - M, bottom - 10), 36 if not trust else 14)
        elif trust:
            self._oj_cert(draw, ctx, pal, bottom - 62)

    def _oj_text_card(self, img, draw, ctx, pal, photo, top, bottom) -> None:
        W, M = self.WIDTH, self.MARGIN
        trust = ctx.design.variant == "trust"
        y = top + 10
        draw.rounded_rectangle([M - 30, y + 8, M - 20, y + 78], radius=5, fill=pal["accent"])
        y = self._oj_title(draw, ctx, pal, y, 68, 44, 3) + 18
        take_h = 150 if (ctx.slide.takeaway or "").strip() else 0
        area_bottom = bottom - take_h
        if photo is not None and area_bottom - y > 420:
            ph = min(380, (area_bottom - y) // 2 + 40)
            self._oj_round_photo(img, photo, (M, y, W - M, y + ph), 32 if not trust else 12)
            y += ph + 24
        items = _items(ctx.slide.body_content, 5) or ([ctx.slide.body_content] if (ctx.slide.body_content or "").strip() else [])
        if items and area_bottom - y > 120:
            box = (M, y, W - M, area_bottom - 10)
            draw.rounded_rectangle(box, radius=30 if not trust else 12, fill=pal["oat"])
            pad = 40
            width = (box[2] - box[0]) - 2 * pad - 36
            size = int(46 * ctx.body_scale)
            while True:
                font = korean_font(size, "medium")
                lines: List[tuple] = []
                for it in items:
                    wrapped = wrap_text_px(it, font, width) or [""]
                    lines += [(n == 0, ln) for n, ln in enumerate(wrapped)] + [(False, "")]
                lines = lines[:-1]
                lh = int(text_height(font) * 1.35)
                if lh * len(lines) <= (box[3] - box[1]) - 2 * pad or size <= 26:
                    break
                size -= 2
            ty = box[1] + max(pad, ((box[3] - box[1]) - lh * len(lines)) // 2)
            multi = len(items) > 1
            for first, line in lines:
                if line:
                    if first and multi:
                        draw.ellipse([box[0] + pad, ty + lh // 2 - 8, box[0] + pad + 16, ty + lh // 2 + 8], fill=pal["accent"])
                    draw.text((box[0] + pad + (36 if multi else 0), ty), line, font=font, fill=CHARCOAL)
                ty += lh
        self._oj_takeaway(draw, ctx, pal, bottom)

    def _oj_steps(self, img, draw, ctx, pal, top, bottom) -> None:
        """번호 단계: 2~4개는 2열 칸(번호 원 + 문구), 그 이상은 세로 줄."""
        W, M = self.WIDTH, self.MARGIN
        trust = ctx.design.variant == "trust"
        y = self._oj_title(draw, ctx, pal, top + 10, 64, 42, 2) + 22
        take_h = 150 if (ctx.slide.takeaway or "").strip() else 0
        items = _items(ctx.slide.body_content, 6)
        area = (M, y, W - M, bottom - take_h - 6)
        if items:
            if len(items) in (2, 4):
                rows = -(-len(items) // 2)
                gap = 26
                cw, ch = ((area[2] - area[0]) - gap) // 2, ((area[3] - area[1]) - gap * (rows - 1)) // rows
                for i, item in enumerate(items):
                    x0 = area[0] + (i % 2) * (cw + gap)
                    y0 = area[1] + (i // 2) * (ch + gap)
                    draw.rounded_rectangle([x0, y0, x0 + cw, y0 + ch], radius=28 if not trust else 12, fill=pal["oat"])
                    d = min(96, ch // 3)
                    draw.ellipse([x0 + 28, y0 + 26, x0 + 28 + d, y0 + 26 + d], fill=pal["main"])
                    draw.text((x0 + 28 + d / 2, y0 + 26 + d / 2), str(i + 1), font=display_font(int(d * 0.56), str(i + 1)), fill="#FFFFFF", anchor="mm")
                    font, lines = self._fit_lines(item, cw - 56, int(44 * ctx.body_scale), 26, 4, "medium")
                    lh = int(text_height(font) * 1.28)
                    ty = y0 + 26 + d + 18
                    for line in lines:
                        draw.text((x0 + 28, ty), line, font=font, fill=CHARCOAL)
                        ty += lh
            else:
                draw.rounded_rectangle(area, radius=30 if not trust else 12, fill=pal["oat"])
                self._oj_rows(draw, ctx, pal, items, (area[0] + 20, area[1] + 10, area[2] - 20, area[3] - 10), check=False)
        self._oj_takeaway(draw, ctx, pal, bottom)

    def _oj_checklist(self, img, draw, ctx, pal, top, bottom) -> None:
        y = self._oj_title(draw, ctx, pal, top + 10, 64, 42, 2) + 22
        take_h = 150 if (ctx.slide.takeaway or "").strip() else 0
        area = (self.MARGIN, y, self.WIDTH - self.MARGIN, bottom - take_h - 6)
        box_fill = pal["oat"]
        draw.rounded_rectangle(area, radius=30 if ctx.design.variant == "warm" else 12, fill=box_fill)
        self._oj_rows(draw, ctx, pal, _items(ctx.slide.body_content, 6), (area[0] + 20, area[1] + 10, area[2] - 20, area[3] - 10), check=True)
        self._oj_takeaway(draw, ctx, pal, bottom)

    def _oj_rows(self, draw, ctx, pal, items: List[str], area, check: bool) -> None:
        if not items:
            return
        x0, y0, x1, y1 = area
        row_h = (y1 - y0) // len(items)
        d = min(76, row_h - 18)
        for i, item in enumerate(items):
            mid = y0 + i * row_h + row_h // 2
            draw.ellipse([x0 + 20, mid - d // 2, x0 + 20 + d, mid + d // 2], fill=pal["accent"] if check else pal["main"])
            label = "✓" if check else str(i + 1)
            draw.text((x0 + 20 + d / 2, mid), label, font=display_font(int(d * 0.56), label), fill="#FFFFFF", anchor="mm")
            font, lines = self._fit_lines(item, (x1 - x0) - d - 80, int(46 * ctx.body_scale), 26, 2, "medium")
            lh = int(text_height(font) * 1.22)
            ty = mid - lh * len(lines) // 2
            for line in lines:
                draw.text((x0 + d + 48, ty), line, font=font, fill=CHARCOAL)
                ty += lh

    def _oj_panel_card(self, img, draw, ctx, pal, top, bottom) -> None:
        """큰 숫자·행사 안내·비교표: 3단 레이아웃의 그리기 함수를 같은 틀 안에서 재사용."""
        from cards.card_renderer import normalize_table
        W, M = self.WIDTH, self.MARGIN
        y = self._oj_title(draw, ctx, pal, top + 10, 64, 42, 2) + 22
        take_h = 150 if (ctx.slide.takeaway or "").strip() else 0
        panel = (M, y, W - M, bottom - take_h - 6)
        draw.rounded_rectangle(panel, radius=30 if ctx.design.variant == "warm" else 12, fill=pal["oat"])
        t = ctx.slide.slide_type
        if t == "big_number" and ctx.slide.stat_value:
            self._tri_big_number(draw, ctx, panel, False)
        elif t == "event_info":
            self._tri_event(draw, ctx, panel, False)
        elif t == "comparison_table" and all(normalize_table(ctx.slide.comparison_table)):
            header, rows = normalize_table(ctx.slide.comparison_table)
            self._draw_table(draw, header, rows, (panel[0] + 20, panel[1] + 20, panel[2] - 20, panel[3] - 20), ctx)
        else:
            self._tri_text_panel(draw, ctx, panel, False)
        self._oj_takeaway(draw, ctx, pal, bottom)

    # ------------------------------------------------------------------ 마지막 안내(CTA)
    def _oj_cta(self, img, draw, ctx, pal, top, bottom) -> None:
        """전화번호를 크게(코랄 버튼), 네이버 예약 알약, QR(선택), 할인 배지(선택), 슬로건."""
        W, M = self.WIDTH, self.MARGIN
        trust = ctx.design.variant == "trust"
        slide = ctx.slide
        qr = load_qr_image(getattr(slide, "qr_image", "") or "")
        badge = (getattr(slide, "promo_badge", "") or "").strip()
        title_w = W - 2 * M - (230 if badge else 0)
        font, lines = self._fit_lines_emph_safe(slide.lead_headline, title_w, int(70 * ctx.title_scale), 40, 3)
        y = top + 10
        lh = int(text_height(font) * 1.22)
        for line in lines:
            draw.text((M, y), line, font=font, fill=pal["title"])
            y += lh
        body = " ".join(_items(slide.body_content, 3))
        if body:
            bf, blines = self._fit_lines(body, title_w, int(38 * ctx.body_scale), 26, 2, "medium")
            by = y + 8
            for line in blines:
                draw.text((M, by), line, font=bf, fill=CHARCOAL)
                by += int(text_height(bf) * 1.3)
            y = by
        if badge:   # 할인·혜택 배지: 코랄 원 + 흰 글씨(카드 다듬기에서 입력한 문구 그대로)
            d = 210
            bx, by0 = W - M - d, top + 6
            draw.ellipse([bx, by0, bx + d, by0 + d], fill=pal["accent"])
            btext = badge.replace("\\n", "\n").replace("\n", " ")
            bsize = 40
            while True:    # 원 안(안쪽 사각형 약 140px)에 들어갈 때까지 글자를 줄인다
                bfont, blines2 = self._fit_lines(btext, d - 60, bsize, 20, 3, "bold")
                blh = int(text_height(bfont) * 1.15)
                if blh * len(blines2) <= d - 70 or bsize <= 20:
                    break
                bsize -= 2
            ty = by0 + d // 2 - blh * len(blines2) // 2
            for line in blines2:
                draw.text((bx + d / 2, ty), line, font=bfont, fill="#FFFFFF", anchor="ma")
                ty += blh
        y = max(y + 28, top + 210)
        # 전화 버튼
        has_phone = ctx.el.show_phone and bool(ctx.kit.phone)
        qr_mode = qr is not None and (bottom - y - 216) >= QR_SIDE + 40
        btn_h = 190 if qr_mode else 250
        if has_phone:
            draw.rounded_rectangle([M, y, W - M, y + btn_h], radius=34 if not trust else 14, fill=pal["accent"])
            draw.text((W / 2, y + btn_h * 0.25), "전화 문의", font=korean_font(34, "bold"), fill="#FFFFFF", anchor="mm")
            phone = ctx.kit.phone
            size = 104 if not qr_mode else 96
            while display_font(size, phone).getlength(phone) > W - 2 * M - 60 and size > 48:
                size -= 4
            draw.text((W / 2, y + btn_h * 0.64), phone, font=display_font(size, phone), fill="#FFFFFF", anchor="mm")
            y += btn_h + 26
        avail = bottom - y
        pill_font = korean_font(32, "bold")
        if qr is not None and avail >= QR_SIDE + 40:
            side = min(QR_SIDE, avail - 10)
            y += 22
            qbox = (M, y, M + side, y + side)
            draw.rounded_rectangle([qbox[0] - 16, qbox[1] - 16, qbox[2] + 16, qbox[3] + 16], radius=22, fill="#FFFFFF", outline=pal["line"], width=2)
            img.paste(qr.resize((side, side), Image.NEAREST), (qbox[0], qbox[1]))
            tx = qbox[2] + 48
            caption = (getattr(slide, "qr_caption", "") or "").strip() or "QR을 스캔하면\n바로 연결돼요"
            cap_font, cap_lines = self._fit_lines(caption.replace("\\n", "\n").replace("\n", " "), W - M - tx, 44, 28, 3, "bold")
            cy = y + 10
            for line in cap_lines:
                draw.text((tx, cy), line, font=cap_font, fill=pal["title"])
                cy += int(text_height(cap_font) * 1.25)
            cy += 14
            cy += self._oj_info_pills(draw, ctx, pal, tx, cy, W - M, pill_font)
        else:
            self._oj_info_pills(draw, ctx, pal, M, y, W - M, pill_font, center=True)
            slogan = (ctx.kit.tagline or "").strip()
            bot = bottom - (70 if (trust or "공신력" in (ctx.kit.footer_text or "")) else 0)
            if slogan and bot - (y + 90) > 130:
                sf, sl = self._fit_lines(slogan, W - 2 * M - 80, 46, 28, 3, "bold")
                lh2 = int(text_height(sf) * 1.3)
                top_box = y + 100
                box_h = min(bot - top_box, 330)
                top_box = bot - box_h
                draw.rounded_rectangle([M, top_box, W - M, bot], radius=30 if not trust else 12, fill=pal["oat"])
                sy = top_box + (box_h - lh2 * len(sl)) // 2
                for line in sl:
                    draw.text((W / 2, sy), line, font=sf, fill=pal["main"], anchor="ma")
                    sy += lh2
        if trust or "공신력" in (ctx.kit.footer_text or ""):
            self._oj_cert(draw, ctx, pal, bottom - 52)

    def _oj_info_pills(self, draw, ctx, pal, x: int, y: int, x_max: int, font, center: bool = False) -> int:
        """네이버 예약 알약과 (있으면) 홈페이지 알약. 쓴 높이를 돌려준다."""
        pills = ["네이버 예약 가능"]
        if ctx.el.show_homepage and ctx.kit.homepage_short:
            pills.append(ctx.kit.homepage_short)
        widths = [int(font.getlength(p)) + 56 for p in pills]
        total = sum(widths) + 14 * (len(pills) - 1)
        if center:
            x = (self.WIDTH - total) // 2
        used_y = y
        cx = x
        for p, w in zip(pills, widths):
            if cx + w > x_max and cx > x:    # 넘치면 다음 줄
                cx, used_y = x, used_y + 70
            draw.rounded_rectangle([cx, used_y, cx + w, used_y + 58], radius=29, outline=pal["main"], width=3, fill=pal["bg"])
            draw.text((cx + w / 2, used_y + 29), p, font=font, fill=pal["main"], anchor="mm")
            cx += w + 14
        return used_y + 58 - y

    def _fit_lines_emph_safe(self, text: str, width: int, start: int, minimum: int, max_lines: int):
        """제목 한 덩어리(강조 표시는 지우고) 줄바꿈 — 마지막 안내 카드는 코랄 버튼이 주인공이라 제목은 단색."""
        clean = re.sub(r"\*([^*]+)\*", r"\1", text or "")
        size = start
        while True:
            font = display_font(size, clean)
            lines = wrap_text_px(clean, font, width)
            if len(lines) <= max_lines or size <= minimum:
                return font, lines[:max_lines]
            size -= 2


def mix_hex(a: str, b: str, t: float) -> str:
    from cards.card_renderer import mix
    return mix(a, b, t)
