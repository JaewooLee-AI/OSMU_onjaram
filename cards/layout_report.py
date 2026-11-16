"""신뢰 리포트 레이아웃(layout="rp") — 온자람 '전문·신뢰' 트랙(기관·학교·EAP 안내)용.

- 위 진한 띠(작은 칩 + 시리즈 이름 + 쪽 번호)와 가는 포인트 선
- 표지는 전용 화면(띠 아래로 사진을 가득 깔고 큰 제목), 상담 안내는 전용 화면(큰 전화번호 칸)
- 목록은 상자 없이 줄로 나눈 표(큰 번호 01·02·03 또는 인장 체크 + 제목/설명), 항목이 적으면 줄과 글자를 키움
- 안내는 라벨 열이 있는 표, 아래 요약 한 줄은 카드 종류에 따라 진한 띠 / 가는 줄
- 쇼츠(cards/shorts_ed.py)가 쓰는 사진 칸·목록 칸 좌표 `ed_regions`를 남김

모서리는 8~10px로 각지게 둡니다(공감 트랙의 둥근 에디토리얼과 구분).
"""
from __future__ import annotations

from typing import List, Optional

from PIL import Image, ImageDraw

from cards import tokens as T
from cards.fonts import display_font, korean_font, text_height, wrap_text_balanced, wrap_text_px
from cards.layout_editorial import (
    KICKERS,
    LIST_TYPES,
    _draw_check_mark,
    _draw_footer_row,
    _lines,
    body_start_size,
    on_color,
    draw_take_line,
    take_mode,
    word_fit_size,
    parse_info_rows,
    split_item_head_desc,
)


class ReportLayoutMixin:
    """CardNewsRendererService에 섞어 쓰는 프레스티지 리포트 레이아웃."""

    RP_PAD = T.SPACE["pad_report"]
    RP_BAND = T.SPACE["band_report"]
    _rp_fs = 1.0

    # --- 색 ----------------------------------------------------------------
    def _rp_colors(self, ctx):
        from cards.card_renderer import luminance, mix
        c = ctx.c
        styled_dark = bool((ctx.slide.style or {}).get("bg")) and luminance(c.background) < 0.45
        if ctx.design.variant == "dark" or styled_dark:
            bg = c.background if styled_dark else (getattr(ctx, "dark_bg", None) or T.NAVY)
            gold = c.secondary if luminance(c.secondary) >= 0.5 else T.GOLD_LIGHT   # 어두운 바탕에서 읽히는 밝기만
            first = c.accent if luminance(c.accent) >= 0.5 else gold
            return {
                "bg": bg, "band": mix(bg, T.BLACK, 0.28), "band_ink": T.IVORY, "chip": mix(bg, T.IVORY, 0.14),
                "ink": T.IVORY, "text": T.IVORY_TEXT, "muted": mix(bg, T.IVORY, 0.58), "line": mix(bg, T.IVORY, 0.20),
                "rule": mix(bg, gold, 0.72), "panel": mix(bg, T.IVORY, 0.08), "num": gold,
                "seal": gold, "accent": first, "gold": gold, "first": first, "navy": mix(bg, T.BLACK, 0.30),
                "deep": mix(bg, T.BLACK, 0.45), "solid": mix(bg, T.BLACK, 0.30), "solid_ink": T.IVORY, "dark": True,
            }
        navy = c.primary
        gold = c.accent if c.accent.upper() == T.GOLD else c.secondary
        sand = mix(c.background, T.SAND_MIX, 0.26) if luminance(c.background) > 0.7 else mix(c.background, T.WHITE, 0.08)
        return {
            "bg": c.background, "band": navy, "band_ink": T.IVORY, "chip": mix(navy, T.IVORY, 0.14),
            "ink": navy, "text": mix(navy, T.CHARCOAL, 0.55), "muted": mix(navy, c.background, 0.46),
            "line": mix(navy, c.background, 0.84), "rule": navy, "panel": sand,
            "num": navy, "seal": gold, "accent": c.accent, "gold": gold, "first": c.accent, "navy": navy,
            "deep": mix(navy, T.BLACK, 0.45),
            "solid": navy, "solid_ink": T.IVORY, "dark": False,
        }

    # --- 조각 ----------------------------------------------------------------
    def _rp_band(self, draw, ctx, k, label: str) -> int:
        W, P = self.WIDTH, self.RP_PAD
        top = getattr(self, "safe_top", 0)
        h = self.RP_BAND
        draw.rectangle([0, top, W, top + h], fill=k["band"])
        draw.rectangle([0, top + h - 4, W, top + h], fill=k.get("gold", T.GOLD))
        cy = top + h // 2
        gold = k.get("gold", T.GOLD)

        # 좌측 골드 ASSET BRIEFING 칩 + 브랜드/시리즈 라벨
        tag = T.COPY["band_tag_shorts" if getattr(self, "ED_SHORTS", False) else "band_tag"]
        tf = display_font(20, tag)
        tw = int(tf.getlength(tag)) + 24
        if tag:
            draw.rounded_rectangle([P, cy - 18, P + tw, cy + 18], radius=4, fill=gold)
        else:
            tw = -18
        draw.text((P + tw / 2, cy), tag, font=tf, fill=on_color(gold), anchor="mm")

        page = f"{ctx.index + 1:02d} / {ctx.total:02d}"
        pf = korean_font(26, "bold")
        pw = int(pf.getlength(page)) + 16
        draw.text((W - P, cy), page, font=pf, fill=k["band_ink"], anchor="rm")

        if label:
            max_lw = max(80, (W - P - pw - 20) - (P + tw + 18))
            lf = korean_font(25, "semibold")
            lbl = label
            while lf.getlength(lbl) > max_lw and len(lbl) > 4:
                lbl = lbl[:-2] + "…"
            draw.text((P + tw + 18, cy), lbl, font=lf, fill=k["band_ink"], anchor="lm")
        return top + h

    def _rp_kicker(self, draw, k, y: int, text: str) -> int:
        if not text:
            return y
        W, P = self.WIDTH, self.RP_PAD
        f = display_font(26, text)
        draw.text((P, y), text, font=f, fill=k["seal"])
        x = P + f.getlength(text) + 18
        mid = y + text_height(f) // 2 + 3
        draw.line([x, mid, W - P, mid], fill=k["line"], width=2)
        return y + int(text_height(f) * 1.7)

    def _rp_title(self, draw, ctx, k, y: int, start: int, max_h: int) -> int:
        W, P = self.WIDTH, self.RP_PAD
        size = word_fit_size(ctx.slide.lead_headline, int(start * ctx.title_scale), W - 2 * P, 38)
        while True:
            end = self._emph_title(draw, ctx, y, size, 38, 3, x=P, width=W - 2 * P, color=k["ink"],
                                   emph_color=k["accent"], measure=True, line_gap=1.24)
            if end - y <= max_h or size <= 38:
                break
            size -= 3
        end = self._emph_title(draw, ctx, y, size, 38, 3, x=P, width=W - 2 * P, color=k["ink"],
                               emph_color=k["accent"], line_gap=1.24)
        draw.line([P, end + 22, W - P, end + 22], fill=k["line"], width=2)
        draw.line([P, end + 22, P + 140, end + 22], fill=k.get("gold", T.GOLD), width=3)
        self._ed_note(title=(int(P), int(y), int(W - P), int(end + 26)))
        return end + 24

    def _rp_seal(self, draw, cx: float, cy: float, r: float, color: str, check: bool = True, fill: Optional[str] = None) -> None:
        """프리미엄 인장(금색 테두리 + 체크)."""
        if fill:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=max(2, int(r / 9)))
        ri = r * 0.78
        draw.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], outline=color, width=max(1, int(r / 20)))
        if check:
            _draw_check_mark(draw, cx, cy, r * 0.9, color)

    def _rp_paragraph(self, draw, text_lines: List[str], box, color: str, start: int, minimum: int = 26,
                      weight: str = "regular", measure: bool = False) -> int:
        x0, y0, x1, y1 = box
        size = start
        while True:
            font = korean_font(size, weight)
            lines: List[str] = []
            for t in text_lines:
                lines += wrap_text_balanced(t, font, x1 - x0)
            lh = int(text_height(font) * 1.5)
            if lh * len(lines) <= (y1 - y0) or size <= minimum:
                break
            size -= 2
        if measure:
            return lh * len(lines)
        y = y0
        cut = False
        for line in lines:
            if y + lh > y1 + lh * 0.3:
                cut = True
                break
            draw.text((x0, y), line, font=font, fill=color)
            y += lh
        self._clip(" ".join(text_lines), cut)
        return y

    def _rp_photo(self, img, photo, box, radius: int = 10, tag: str = "", border_color: Optional[str] = None) -> None:
        x0, y0, x1, y1 = box
        self._ed_note(photo={"box": tuple(int(v) for v in box), "radius": radius})
        fitted = self._cover_fit(photo, max(1, x1 - x0), max(1, y1 - y0))
        mask = Image.new("L", fitted.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fitted.width - 1, fitted.height - 1], radius=radius, fill=255)
        img.paste(fitted, (x0, y0), mask)
        d = ImageDraw.Draw(img)
        if border_color:
            d.rounded_rectangle([x0, y0, x1 - 1, y1 - 1], radius=radius, outline=border_color, width=2)
        if tag and not getattr(self, "ED_SHORTS", False):
            tf = display_font(20, tag)
            tw = int(tf.getlength(tag)) + 26
            d.rounded_rectangle([x0 + 16, y0 + 16, x0 + 16 + tw, y0 + 50], radius=5, fill=T.NAVY, outline=T.GOLD, width=1)
            d.text((x0 + 16 + tw / 2, y0 + 33), tag, font=tf, fill=T.GOLD_LIGHT, anchor="mm")

    def _rp_rows(self, draw, ctx, k, items: List[str], box, mode: str) -> None:
        """표처럼 줄로 나눈 리포트 목록(중복 번호 제거). mode: number | check."""
        x0, y0, x1, y1 = box
        n = max(1, len(items))
        roomy = n <= 3                      # 항목이 적으면 줄과 글자를 키워 빈 곳을 채운다
        row_h = min(int(((300 if getattr(self, "ED_SHORTS", False) else 256) if roomy else 196) * self._rp_fs), (y1 - y0) // n)
        y = y0 + min(10, max(0, (y1 - y0) - row_h * n))
        col = int((168 if roomy else 144) * min(1.1, self._rp_fs))
        tw = (x1 - x0) - col
        parts = [split_item_head_desc(it) for it in items]
        size = min(54 if roomy else 40, int((50 if roomy else 38) * ctx.body_scale * self._rp_fs))
        while True:
            hf, df = display_font(size, " ".join(items)), korean_font(max(20, int(size * 0.74)), "regular")
            hl, dl = int(text_height(hf) * 1.28), int(text_height(df) * 1.38)
            ok = all(
                len(wrap_text_px(h, hf, tw)) * hl + (len(wrap_text_px(d, df, tw)) * dl + 6 if d else 0) <= row_h - 24
                and len(wrap_text_px(h, hf, tw)) <= 3 and (not d or len(wrap_text_px(d, df, tw)) <= 3)
                for h, d in parts
            )
            if ok or size <= 24:
                break
            size -= 2

        gold = k.get("gold", T.GOLD)
        draw.line([x0, y, x1, y], fill=k["rule"], width=3)
        for i, (head, desc) in enumerate(parts):
            self._ed_note(row=(int(x0), int(y + 3), int(x1), int(y + row_h)))
            cy = y + row_h // 2
            if mode == "check":
                self._rp_seal(draw, x0 + 38, cy, 32 * min(1.12, self._rp_fs), k.get("first", gold) if i == 0 else k["seal"])
            else:
                num = f"{i + 1:02d}"
                nf = display_font(int((72 if roomy else 56) * min(1.15, self._rp_fs)), num)
                draw.text((x0 + 6, cy), num, font=nf, fill=k.get("first", gold) if i == 0 else k["num"], anchor="lm")
            h_all = wrap_text_px(head, hf, tw)
            d_all = wrap_text_px(desc, df, tw) if desc else []
            hlines, dlines = h_all[:3], d_all[:3]
            self._clip(items[i], len(h_all) > 3 or len(d_all) > 3)
            block = len(hlines) * hl + (len(dlines) * dl + 6 if dlines else 0)
            ty = cy - block // 2
            for line in hlines:
                draw.text((x0 + col, ty), line, font=hf, fill=k["ink"])
                ty += hl
            if dlines:
                ty += 6
                for line in dlines:
                    draw.text((x0 + col, ty), line, font=df, fill=k["muted"])
                    ty += dl
            y += row_h
            draw.line([x0, y, x1, y], fill=k["line"], width=2)

    def _rp_meta(self, img, draw, ctx, k, box) -> None:
        """라벨 열 + 값 메타데이터 표(안내·문의)."""
        x0, y0, x1, y1 = self._draw_cta_extras(img, draw, ctx, k, box)
        rows = parse_info_rows(ctx.slide.body_content, 7)
        if not rows:
            return
        n = len(rows)
        roomy = n <= 3
        row_h = min(int((196 if roomy else 148) * self._rp_fs), (y1 - y0) // n)
        y = y0 + min(10, max(0, (y1 - y0) - row_h * n))
        lab_w = 200
        gold = k.get("gold", T.GOLD)
        draw.line([x0, y, x1, y], fill=k["rule"], width=3)
        for label, value in rows:
            self._ed_note(row=(int(x0), int(y + 3), int(x1), int(y + row_h)))
            cy = y + row_h // 2
            vx = x0 + (lab_w if label else 0)
            if label:
                draw.text((x0, cy), label, font=korean_font(28, "bold"), fill=gold if k["dark"] else k["ink"], anchor="lm")
            weight = "bold" if label else "medium"
            font, lines = self._fit_lines(value, x1 - vx, int((46 if roomy else 38) * ctx.body_scale * self._rp_fs), 26, 1, weight)
            if lines and lines[-1].endswith("…"):
                font, lines = self._fit_lines(value, x1 - vx, min(34, max(22, (row_h - 24) // 3)), 22, 2, weight)
            lh = int(text_height(font) * 1.3)
            ly = cy - lh * (len(lines) - 1) / 2
            for line in lines:
                draw.text((vx, ly), line, font=font, fill=k["ink"] if label else k["text"], anchor="lm")
                ly += lh
            y += row_h
            draw.line([x0, y, x1, y], fill=k["line"], width=2)

    def _rp_banner(self, draw, ctx, k, box, solid: bool) -> None:
        text = (ctx.slide.takeaway or "").strip()
        mode = take_mode(ctx.slide)
        if not text or getattr(self, "ED_SHORTS", False) or mode == "none":   # 쇼츠: 요약은 내레이션·자막이 맡는다
            return
        if mode == "line":
            draw_take_line(self, draw, ctx, k, box)
            return
        x0, y0, x1, y1 = box
        gold = k.get("gold", T.GOLD)
        fill = k["solid"] if solid else k["navy"]
        draw.rounded_rectangle(box, radius=8, fill=fill, outline=gold if k["dark"] else None, width=1 if k["dark"] else 0)
        draw.rectangle([x0, y0 + 12, x0 + 8, y1 - 12], fill=gold)
        cy = (y0 + y1) // 2
        self._rp_seal(draw, x0 + 54, cy, 26, gold)
        tx = x0 + 104
        font, lines = self._fit_lines(text, x1 - tx - 28, int(36 * ctx.takeaway_scale), 28, 1, "bold")
        if lines and lines[-1].endswith("…"):
            font, lines = self._fit_lines(text, x1 - tx - 28, int(30 * ctx.takeaway_scale), 22, 2, "bold")
        lh = int(text_height(font) * 1.28)
        ty = cy - lh * len(lines) // 2
        for line in lines:
            draw.text((tx, ty), line, font=font, fill=T.IVORY)
            ty += lh

    def _rp_footer(self, draw, ctx, k) -> None:
        if getattr(self, "ED_SHORTS", False):               # 쇼츠: 바닥글 없음(아래는 자막 자리)
            return
        W, P = self.WIDTH, self.RP_PAD
        H = self.HEIGHT - getattr(self, "safe_bottom", 0)
        y = H - 92
        draw.line([P, y, W - P, y], fill=k["line"], width=2)
        ends = ctx.index == 0 or ctx.index >= ctx.total - 1
        left = ctx.kit.brand_name or ""
        right, r_weight, r_fill, r_size = "", "medium", k["muted"], 26
        if ends and ctx.el.show_phone and ctx.kit.phone and not getattr(ctx, "cta_hero", False):
            right, r_weight, r_fill, r_size = f"{T.COPY['phone_prefix_report']} {ctx.kit.phone}", "bold", k["ink"], 27
        elif not ends and not getattr(self, "ED_SHORTS", False):
            right = T.COPY["next"]
        _draw_footer_row(draw, P, W, y + 46, left, right, k["muted"], r_fill,
                         left_weight="semibold", right_weight=r_weight, right_size=r_size)

    # --- 본체 ----------------------------------------------------------------
    def _layout_rp(self, ctx, photo: Optional[Image.Image]) -> Image.Image:
        from cards.card_renderer import normalize_table

        W, H, P = self.WIDTH, self.HEIGHT, self.RP_PAD
        Hc = H - getattr(self, "safe_top", 0) - getattr(self, "safe_bottom", 0)
        self._rp_fs = max(1.0, min(1.22, Hc / 1350))
        self._ed_round = 1.0
        k = self._rp_colors(ctx)
        self.ed_regions = {
            "photo": None, "rows": [], "title": None, "stat": None, "bg": k["bg"], "ink": k["ink"], "solid": k["solid"],
            "accent": k["accent"], "gold": k.get("gold", T.GOLD), "dark": k["dark"],
            "cap_radius": 14, "pad": P,
        }
        img = Image.new("RGB", (W, H), k["bg"])
        draw = ImageDraw.Draw(img)
        t = ctx.slide.slide_type
        series = (getattr(ctx.el, "series_label", "") or "").strip()
        last = ctx.index >= ctx.total - 1
        # 브랜드 이름은 바닥글에 있으므로 위 띠에는 시리즈 이름만(없으면 비움)
        y = self._rp_band(draw, ctx, k, series)
        is_shorts = getattr(self, "ED_SHORTS", False)
        if t == "cover" and (not is_shorts or photo is None):
            # 표지 전용 화면: 네이비 띠 아래로 사진을 가득 깔고 큰 제목(쇼츠는 사진이 없을 때만)
            self._hero_cover(img, ctx, k, photo, y, P, 10, label=series or T.COPY["cover_label"], page_tag=False)
            return img
        y += 38
        # 쇼츠는 요약 띠·바닥글을 그리지 않고(자막이 그 자리를 맡는다) 내용 칸을 자막 바로 위까지 쓴다
        foot_top = H - getattr(self, "safe_bottom", 0) - (20 if is_shorts else 92 + 26)
        mode = "none" if is_shorts else take_mode(ctx.slide)
        has_take = mode != "none"
        docked = mode == "bar"              # 진한 띠만 사진 아래에 맞닿게 붙인다
        banner_top = foot_top - {"bar": 120, "line": 92}.get(mode, 0)
        content_bottom = banner_top - (30 if has_take else 0)

        # --- 1) 쇼츠 표지(사진 있음): 네이비 띠 바로 아래 큰 사진·영상 칸 → 그 아래 큰 제목·리드
        if t == "cover":
            body = _lines(ctx.slide.body_content, 4)
            ph = int(Hc * 0.50)
            self._rp_photo(img, photo, (P, y, W - P, y + ph), radius=10, border_color=k.get("gold", k["line"]))
            y = y + ph + 32
            y = self._rp_kicker(draw, k, y, series or T.COPY["cover_label"])
            y = self._rp_title(draw, ctx, k, y, int(T.TYPE["shorts_cover_title"] * self._rp_fs), int((content_bottom - y) * 0.62)) + 20
            if body and content_bottom - y > 56:
                self._rp_paragraph(draw, [" ".join(body)], (P, y, W - P, content_bottom),
                                   k["text"], int(40 * self._rp_fs), 26, weight="medium")
            return img

        # --- 2) 일반 슬라이드
        y = self._rp_kicker(draw, k, y, KICKERS.get(t, ""))
        title_max_h = int(190 * self._rp_fs) if (is_shorts and t in LIST_TYPES and photo is not None) else int((290 if is_shorts else 240) * self._rp_fs)
        y = self._rp_title(draw, ctx, k, y, int(T.TYPE["title_report_shorts" if is_shorts else "title_report"] * self._rp_fs), title_max_h) + 28
        box = (P, y, W - P, content_bottom)
        body = _lines(ctx.slide.body_content, 6)
        solid = last or t == "call_to_action"

        if box[3] - box[1] < 80:
            pass
        elif t in LIST_TYPES and body:
            if is_shorts and photo is not None and (box[3] - box[1]) > 540:
                ph = min(380, int((box[3] - box[1]) * 0.42))
                self._rp_photo(img, photo, (P, box[1], W - P, box[1] + ph), radius=10, border_color=k.get("gold", k["line"]))
                row_box = (P, box[1] + ph + 20, W - P, box[3])
            else:
                row_box = box
            self._rp_rows(draw, ctx, k, body, row_box, "check" if t == "checklist" else "number")
        elif t == "call_to_action":
            self._ed_fs = self._rp_fs
            if not self._cta_hero(img, draw, ctx, k, box, radius=10):
                self._rp_meta(img, draw, ctx, k, box)
        elif t == "event_info":
            self._rp_meta(img, draw, ctx, k, box)
        elif t == "big_number" and ctx.slide.stat_value:
            draw.rounded_rectangle(box, radius=10, fill=k["panel"], outline=k["line"], width=2)
            self._ed_note(stat=tuple(int(v) for v in box))
            value = ctx.slide.stat_value
            size = 196
            while display_font(size, value).getlength(value) > (W - 2 * P) - 120 and size > 60:
                size -= 6
            cy = (box[1] + box[3]) // 2 - 36
            draw.text((P + 60, cy), value, font=display_font(size, value), fill=k["ink"], anchor="lm")
            draw.line([P + 60, cy + size // 2 + 16, P + 260, cy + size // 2 + 16], fill=k.get("gold", k["accent"]), width=6)
            if ctx.slide.stat_label:
                lf, lines = self._fit_lines(ctx.slide.stat_label, W - 2 * P - 120, 38, 24, 2, "semibold")
                ly = cy + size // 2 + 42
                for line in lines:
                    draw.text((P + 60, ly), line, font=lf, fill=k["text"])
                    ly += int(text_height(lf) * 1.3)
        elif t == "comparison_table" and all(normalize_table(ctx.slide.comparison_table)):
            header, rows = normalize_table(ctx.slide.comparison_table)
            draw.rounded_rectangle(box, radius=10, fill=k["panel"], outline=k["line"], width=2)
            self._draw_table(draw, header, rows, (box[0] + 20, box[1] + 20, box[2] - 20, box[3] - 20), ctx,
                             start=46, stretch=True, pal=self._table_palette(ctx, k))
        elif photo is not None:
            p_limit_bottom = foot_top if docked else content_bottom
            text_max = min(int((p_limit_bottom - box[1]) * 0.40), 250)
            para_y = box[1]
            if body:
                para_h = self._rp_paragraph(draw, body, (P, box[1], W - P, box[1] + text_max),
                                            k["text"], int(34 * ctx.body_scale * self._rp_fs), 24, measure=True)
                self._rp_paragraph(draw, body, (P, box[1], W - P, box[1] + text_max),
                                   k["text"], int(34 * ctx.body_scale * self._rp_fs), 24)
                para_y = box[1] + min(text_max, para_h) + 24

            if docked:
                p_bot = max(para_y + 180, foot_top)
                self._rp_photo(img, photo, (P, para_y, W - P, p_bot), radius=10, border_color=k["line"])
                self._rp_banner(draw, ctx, k, (P, foot_top - 116, W - P, foot_top), True)
                self._rp_footer(draw, ctx, k)
                return img
            else:
                p_bot = max(para_y + 180, content_bottom)
                self._rp_photo(img, photo, (P, para_y, W - P, p_bot), radius=10, border_color=k.get("gold", k["line"]))
        elif body and box[3] - box[1] >= 140:
            draw.rounded_rectangle(box, radius=10, fill=k["panel"], outline=k["line"], width=2)
            draw.rectangle([box[0], box[1] + 28, box[0] + 8, box[3] - 28], fill=k.get("gold", k["rule"]))
            inner = (P + 56, box[1] + 48, W - P - 44, box[3] - 40)
            start = int(body_start_size(body) * ctx.body_scale)
            need = self._rp_paragraph(draw, body, inner, k["text"], start, 26, measure=True)
            top = inner[1] + max(0, (inner[3] - inner[1] - need) // 2)
            self._rp_paragraph(draw, body, (inner[0], top, inner[2], inner[3]), k["text"], start, 26)

        self._rp_banner(draw, ctx, k, (P, banner_top, W - P, foot_top), solid)
        self._rp_footer(draw, ctx, k)
        return img
