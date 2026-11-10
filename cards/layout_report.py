"""신뢰 리포트 레이아웃(layout="rp") — '전문·신뢰' 트랙(기관·학교·EAP 안내)용.

Stitch 시안(프로젝트 '온자람 전문·신뢰 카드·쇼츠', 디자인 시스템 'Academic Clinical Editorial')에서 가져온 것:
- 위 네이비 띠: 시리즈 라벨 칩 + 쪽 번호
- 왼쪽 정렬 네이비 제목, 아래 가는 선(hairline)
- 목록은 상자가 아니라 표처럼: 큰 네이비 번호(01·02·03) + 굵은 항목 + 옅은 설명, 1px 선으로 구분
- 체크 목록·요약 띠에는 동그란 '인장' 모양 체크 표시(세이지)
- 안내는 라벨 열(옅게) + 값(굵게) 메타데이터 표
- 오트(#F0ECE1) 칸·작은 모서리(8~10px)·그림자 없음, 코랄은 한 군데 강조에만
시안 속 문구(기관명·인증·전화·'1급 상담사' 등)는 지어낸 것이라 가져오지 않습니다 — 카드 글은 기획 결과와 브랜드 킷 값만 씁니다.

쇼츠 전용 화면(cards/shorts_ed.py)이 쓰도록 사진 칸·목록 칸 위치를 `ed_regions`에 남깁니다(에디토리얼과 같은 방식).
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from cards.fonts import display_font, korean_font, text_height, wrap_text_balanced, wrap_text_px
from cards.layout_editorial import KICKERS, LIST_TYPES, _LABEL_RE, _lines

_SPLIT = re.compile(r"\s+[—–-]\s+|\s*[:：]\s+")


class ReportLayoutMixin:
    """CardNewsRendererService에 섞어 쓰는 신뢰 리포트 레이아웃."""

    RP_PAD = 80
    RP_BAND = 112
    _rp_fs = 1.0

    # --- 색 ----------------------------------------------------------------
    def _rp_colors(self, ctx):
        from cards.card_renderer import luminance, mix
        c = ctx.c
        styled_dark = bool((ctx.slide.style or {}).get("bg")) and luminance(c.background) < 0.45   # 말로 고치기로 어두운 바탕을 고른 카드
        if ctx.design.variant == "dark" or styled_dark:
            bg = c.background if styled_dark else (getattr(ctx, "dark_bg", None) or "#1C2F47")
            return {"bg": bg, "band": mix(bg, "#FFFFFF", 0.07), "band_ink": "#FFFFFF", "chip": mix(bg, "#FFFFFF", 0.16),
                    "ink": "#FFFFFF", "text": "#E3E9F0", "muted": mix(bg, "#FFFFFF", 0.58), "line": mix(bg, "#FFFFFF", 0.2),
                    "rule": mix(bg, "#FFFFFF", 0.7), "panel": mix(bg, "#FFFFFF", 0.07), "num": mix(c.secondary, "#FFFFFF", 0.45),
                    "seal": mix(c.secondary, "#FFFFFF", 0.4), "accent": c.accent, "solid": c.secondary, "solid_ink": "#FFFFFF",
                    "dark": True}
        navy = c.primary
        return {"bg": c.background, "band": navy, "band_ink": "#FFFFFF", "chip": mix(navy, "#FFFFFF", 0.16),
                "ink": navy, "text": mix(navy, "#14202E", 0.5), "muted": mix(navy, c.background, 0.42),
                "line": mix(navy, c.background, 0.86), "rule": navy, "panel": mix(c.background, "#B8A57A", 0.18),
                "num": navy, "seal": c.secondary, "accent": c.accent, "solid": navy, "solid_ink": "#FFFFFF", "dark": False}

    # --- 조각 ----------------------------------------------------------------
    def _rp_band(self, draw, ctx, k, label: str) -> int:
        W, P = self.WIDTH, self.RP_PAD
        top = getattr(self, "safe_top", 0)
        h = self.RP_BAND
        draw.rectangle([0, top, W, top + h], fill=k["band"])
        cy = top + h // 2
        if label:
            f = display_font(28, label)
            cw = int(f.getlength(label)) + 64
            draw.rounded_rectangle([P, cy - 25, P + cw, cy + 25], radius=6, fill=k["chip"])
            draw.ellipse([P + 18, cy - 5, P + 28, cy + 5], fill=k["accent"])
            draw.text((P + 40, cy), label, font=f, fill=k["band_ink"], anchor="lm")
        page = f"{ctx.index + 1:02d} / {ctx.total:02d}"
        draw.text((W - P, cy), page, font=korean_font(28, "medium"), fill=k["band_ink"], anchor="rm")
        return top + h

    def _rp_kicker(self, draw, k, y: int, text: str) -> int:
        if not text:
            return y
        W, P = self.WIDTH, self.RP_PAD
        f = display_font(28, text)
        draw.text((P, y), text, font=f, fill=k["seal"])
        x = P + f.getlength(text) + 20
        mid = y + text_height(f) // 2 + 4
        draw.line([x, mid, W - P, mid], fill=k["line"], width=2)
        return y + int(text_height(f) * 1.9)

    def _rp_title(self, draw, ctx, k, y: int, start: int, max_h: int) -> int:
        W, P = self.WIDTH, self.RP_PAD
        size = int(start * ctx.title_scale)
        while True:
            end = self._emph_title(draw, ctx, y, size, 40, 3, x=P, width=W - 2 * P, color=k["ink"],
                                   emph_color=k["accent"], measure=True, line_gap=1.26)
            if end - y <= max_h or size <= 40:
                break
            size -= 3
        end = self._emph_title(draw, ctx, y, size, 40, 3, x=P, width=W - 2 * P, color=k["ink"],
                               emph_color=k["accent"], line_gap=1.26)
        draw.line([P, end + 30, W - P, end + 30], fill=k["line"], width=2)
        return end + 30

    def _rp_seal(self, draw, cx: float, cy: float, r: float, color: str, check: bool = True, fill: Optional[str] = None) -> None:
        """'인장' 모양: 겹친 원 테두리 + 체크."""
        if fill:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=max(2, int(r / 10)))
        ri = r * 0.78
        draw.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], outline=color, width=max(1, int(r / 22)))
        if check:
            s = r / 30
            draw.line([(cx - 11 * s, cy + 1 * s), (cx - 3 * s, cy + 9 * s), (cx + 12 * s, cy - 8 * s)], fill=color,
                      width=max(3, int(4 * s)), joint="curve")

    def _rp_paragraph(self, draw, text_lines: List[str], box, color: str, start: int, minimum: int = 28,
                      weight: str = "regular", measure: bool = False) -> int:
        x0, y0, x1, y1 = box
        size = start
        while True:
            font = korean_font(size, weight)
            lines: List[str] = []
            for t in text_lines:
                lines += wrap_text_balanced(t, font, x1 - x0)
            lh = int(text_height(font) * 1.6)
            if lh * len(lines) <= (y1 - y0) or size <= minimum:
                break
            size -= 2
        if measure:
            return lh * len(lines)
        y = y0
        for line in lines:
            if y + lh > y1 + lh * 0.3:
                break
            draw.text((x0, y), line, font=font, fill=color)
            y += lh
        return y

    def _rp_photo(self, img, photo, box, radius: int = 10) -> None:
        x0, y0, x1, y1 = box
        self._ed_note(photo={"box": tuple(int(v) for v in box), "radius": radius})
        fitted = self._cover_fit(photo, x1 - x0, y1 - y0)
        mask = Image.new("L", fitted.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fitted.width - 1, fitted.height - 1], radius=radius, fill=255)
        img.paste(fitted, (x0, y0), mask)

    def _rp_rows(self, draw, ctx, k, items: List[str], box, mode: str) -> None:
        """표처럼 줄로 나눈 목록. mode: number(큰 번호) | check(인장 체크)."""
        x0, y0, x1, y1 = box
        n = max(1, len(items))
        row_h = min(int(200 * self._rp_fs), (y1 - y0) // n)
        y = y0 + min(12, max(0, (y1 - y0) - row_h * n))   # 리포트처럼 제목 바로 아래부터(가운데 정렬 아님)
        col = int(150 * min(1.1, self._rp_fs))
        tw = (x1 - x0) - col
        parts = [(_SPLIT.split(it, maxsplit=1) + [""])[:2] for it in items]
        size = int(42 * ctx.body_scale * self._rp_fs)
        while True:   # 모든 줄이 같은 글자 크기: 가장 긴 항목에 맞춘다
            hf, df = display_font(size, " ".join(items)), korean_font(int(size * 0.74), "regular")
            hl, dl = int(text_height(hf) * 1.3), int(text_height(df) * 1.45)
            ok = all(len(wrap_text_px(h, hf, tw)) * hl + (len(wrap_text_px(d, df, tw)) * dl + 8 if d else 0) <= row_h - 30
                     for h, d in parts)
            if ok or size <= 26:
                break
            size -= 2
        draw.line([x0, y, x1, y], fill=k["rule"], width=3)
        for i, (head, desc) in enumerate(parts):
            self._ed_note(row=(int(x0), int(y + 3), int(x1), int(y + row_h)))
            cy = y + row_h // 2
            if mode == "check":
                self._rp_seal(draw, x0 + 38, cy, 34 * min(1.15, self._rp_fs), k["seal"])
            else:
                num = f"{i + 1:02d}"
                nf = display_font(int(60 * min(1.2, self._rp_fs)), num)
                draw.text((x0, cy), num, font=nf, fill=k["accent"] if i == 0 else k["num"], anchor="lm")
            hlines = wrap_text_px(head, hf, tw)[:3]
            dlines = wrap_text_px(desc, df, tw)[:3] if desc else []
            block = len(hlines) * hl + (len(dlines) * dl + 8 if dlines else 0)
            ty = cy - block // 2
            for line in hlines:
                draw.text((x0 + col, ty), line, font=hf, fill=k["ink"])
                ty += hl
            if dlines:
                ty += 8
                for line in dlines:
                    draw.text((x0 + col, ty), line, font=df, fill=k["muted"])
                    ty += dl
            y += row_h
            draw.line([x0, y, x1, y], fill=k["line"], width=2)

    def _rp_meta(self, draw, ctx, k, box) -> None:
        """라벨 열 + 값 메타데이터 표(안내·문의). 라벨 없는 줄은 위에 안내 문장으로."""
        x0, y0, x1, y1 = box
        rows: List[Tuple[str, str]] = []
        for line in _lines(ctx.slide.body_content, 7):
            m = re.match(r"^\s*([^:：]{1,8})\s*[:：]\s*(.+)$", line) or re.match(_LABEL_RE, line)
            rows.append((m.group(1).strip(), m.group(2).strip()) if m else ("", line))
        if not rows:
            return
        n = len(rows)
        row_h = min(int(150 * self._rp_fs), (y1 - y0) // n)
        y = y0 + min(12, max(0, (y1 - y0) - row_h * n))
        lab_w = 210
        draw.line([x0, y, x1, y], fill=k["rule"], width=3)
        for label, value in rows:
            self._ed_note(row=(int(x0), int(y + 3), int(x1), int(y + row_h)))
            cy = y + row_h // 2
            vx = x0 + (lab_w if label else 0)
            if label:
                draw.text((x0, cy), label, font=korean_font(30, "semibold"), fill=k["muted"], anchor="lm")
            weight = "semibold" if label else "regular"
            font, lines = self._fit_lines(value, x1 - vx, int(40 * ctx.body_scale * self._rp_fs), 28, 1, weight)
            if lines and lines[-1].endswith("…"):
                font, lines = self._fit_lines(value, x1 - vx, min(36, (row_h - 26) // 3), 22, 2, weight)
            lh = int(text_height(font) * 1.3)
            ly = cy - lh * (len(lines) - 1) / 2
            for line in lines:
                draw.text((vx, ly), line, font=font, fill=k["ink"] if label else k["text"], anchor="lm")
                ly += lh
            y += row_h
            draw.line([x0, y, x1, y], fill=k["line"], width=2)

    def _rp_banner(self, draw, ctx, k, box, solid: bool) -> None:
        text = (ctx.slide.takeaway or "").strip()
        if not text:
            return
        x0, y0, x1, y1 = box
        fill = k["solid"] if solid else k["panel"]
        ink = k["solid_ink"] if solid else k["ink"]
        seal = k["solid_ink"] if solid else k["seal"]
        draw.rounded_rectangle(box, radius=10, fill=fill, outline=None if solid else k["line"], width=0 if solid else 2)
        cy = (y0 + y1) // 2
        self._rp_seal(draw, x0 + 62, cy, 30, seal)
        tx = x0 + 120
        font, lines = self._fit_lines(text, x1 - tx - 32, int(38 * ctx.takeaway_scale), 30, 1, "bold")
        if lines and lines[-1].endswith("…"):
            font, lines = self._fit_lines(text, x1 - tx - 32, int(32 * ctx.takeaway_scale), 24, 2, "bold")
        lh = int(text_height(font) * 1.3)
        ty = cy - lh * len(lines) // 2
        for line in lines:
            draw.text((tx, ty), line, font=font, fill=ink)
            ty += lh

    def _rp_footer(self, draw, ctx, k) -> None:
        W, P = self.WIDTH, self.RP_PAD
        H = self.HEIGHT - getattr(self, "safe_bottom", 0)
        y = H - 96
        draw.line([P, y, W - P, y], fill=k["line"], width=2)
        ends = ctx.index == 0 or ctx.index >= ctx.total - 1
        left = ctx.kit.brand_name or ""
        f = korean_font(26, "medium")
        if left:
            draw.text((P, y + 48), left, font=korean_font(26, "semibold"), fill=k["muted"], anchor="lm")
        if ends and ctx.el.show_phone and ctx.kit.phone:
            draw.text((W - P, y + 48), f"상담 {ctx.kit.phone}", font=korean_font(28, "semibold"), fill=k["ink"], anchor="rm")
        elif not ends and not getattr(self, "ED_SHORTS", False):
            draw.text((W - P, y + 48), "다음 →", font=f, fill=k["muted"], anchor="rm")

    # --- 본체 ----------------------------------------------------------------
    def _layout_rp(self, ctx, photo: Optional[Image.Image]) -> Image.Image:
        from cards.card_renderer import mix, normalize_table

        W, H, P = self.WIDTH, self.HEIGHT, self.RP_PAD
        Hc = H - getattr(self, "safe_top", 0) - getattr(self, "safe_bottom", 0)
        self._rp_fs = max(1.0, min(1.25, Hc / 1350))
        k = self._rp_colors(ctx)
        self.ed_regions = {"photo": None, "rows": [], "bg": k["bg"], "ink": k["ink"], "solid": k["solid"],
                           "accent": k["accent"], "dark": k["dark"], "cap_radius": 8, "pad": P}
        img = Image.new("RGB", (W, H), k["bg"])
        draw = ImageDraw.Draw(img)
        t = ctx.slide.slide_type
        series = (getattr(ctx.el, "series_label", "") or "").strip()
        last = ctx.index >= ctx.total - 1
        y = self._rp_band(draw, ctx, k, (ctx.kit.brand_name or series) if t == "cover" else (series or ctx.kit.brand_name or ""))
        y += 56
        foot_top = H - getattr(self, "safe_bottom", 0) - 96 - 30
        has_take = bool((ctx.slide.takeaway or "").strip())
        banner_top = foot_top - (128 if has_take else 0)
        content_bottom = banner_top - (36 if has_take else 0)

        if t == "cover":
            if photo is not None:
                ph = int(Hc * 0.36)
                self._rp_photo(img, photo, (P, y, W - P, y + ph))
                y += ph + 48
            else:   # 사진 없는 표지: 인장 모양 장식(겹친 원 선)
                cx, cy = W - P - 170, y + 170
                for i in range(5):
                    r = 165 - i * 30
                    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=mix(k["line"], k["ink"], 0.25 + i * 0.12), width=2)
                draw.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=k["accent"])
                y += 300
            y = self._rp_kicker(draw, k, y, series)
            y = self._rp_title(draw, ctx, k, y, int(80 * self._rp_fs), int((content_bottom - y) * 0.55)) + 36
            body = _lines(ctx.slide.body_content, 4)
            if body and content_bottom - y > 60:
                self._rp_paragraph(draw, [" ".join(body)], (P, y, W - P, content_bottom), k["text"], int(36 * self._rp_fs), 26)
            self._rp_banner(draw, ctx, k, (P, banner_top, W - P, foot_top), False)
            self._rp_footer(draw, ctx, k)
            return img

        y = self._rp_kicker(draw, k, y, KICKERS.get(t, ""))
        y = self._rp_title(draw, ctx, k, y, int(62 * self._rp_fs), int(270 * self._rp_fs)) + 40
        box = (P, y, W - P, content_bottom)
        body = _lines(ctx.slide.body_content, 6)
        solid = last or t == "call_to_action"

        if box[3] - box[1] < 80:
            pass
        elif t in LIST_TYPES and body:
            self._rp_rows(draw, ctx, k, body, box, "check" if t == "checklist" else "number")
        elif t in ("call_to_action", "event_info"):
            self._rp_meta(draw, ctx, k, box)
        elif t == "big_number" and ctx.slide.stat_value:
            draw.rounded_rectangle(box, radius=10, fill=k["panel"], outline=k["line"], width=2)
            value = ctx.slide.stat_value
            size = 200
            while display_font(size, value).getlength(value) > (W - 2 * P) - 120 and size > 60:
                size -= 6
            cy = (box[1] + box[3]) // 2 - 36
            draw.text((P + 60, cy), value, font=display_font(size, value), fill=k["ink"], anchor="lm")
            draw.line([P + 60, cy + size // 2 + 16, P + 260, cy + size // 2 + 16], fill=k["accent"], width=6)
            if ctx.slide.stat_label:
                lf, lines = self._fit_lines(ctx.slide.stat_label, W - 2 * P - 120, 40, 26, 2, "semibold")
                ly = cy + size // 2 + 44
                for line in lines:
                    draw.text((P + 60, ly), line, font=lf, fill=k["text"])
                    ly += int(text_height(lf) * 1.3)
        elif t == "comparison_table" and all(normalize_table(ctx.slide.comparison_table)):
            header, rows = normalize_table(ctx.slide.comparison_table)
            draw.rounded_rectangle(box, radius=10, fill=k["panel"], outline=k["line"], width=2)
            self._draw_table(draw, header, rows, (box[0] + 20, box[1] + 20, box[2] - 20, box[3] - 20), ctx)
        elif photo is not None:
            need = self._rp_paragraph(draw, body or [""], (P, 0, W - P, 10_000), k["text"], int(36 * ctx.body_scale * self._rp_fs), 30, measure=True)
            ph = max(int((box[3] - box[1]) * 0.42), (box[3] - box[1]) - need - 40)
            ph = min(ph, int((box[3] - box[1]) * 0.62))
            self._rp_photo(img, photo, (P, box[1], W - P, box[1] + ph))
            self._rp_paragraph(draw, body, (P, box[1] + ph + 36, W - P, box[3]), k["text"], int(36 * ctx.body_scale * self._rp_fs), 26)
        elif body and box[3] - box[1] >= 140:
            # 글 카드: 오트 칸 + 왼쪽 네이비 세로 막대(리포트 인용 상자)
            draw.rounded_rectangle(box, radius=10, fill=k["panel"], outline=k["line"], width=2)
            draw.rectangle([box[0], box[1] + 28, box[0] + 8, box[3] - 28], fill=k["rule"])
            inner = (P + 64, box[1] + 52, W - P - 52, box[3] - 44)
            need = self._rp_paragraph(draw, body, inner, k["text"], int(46 * ctx.body_scale), 28, measure=True)
            top = inner[1] + max(0, (inner[3] - inner[1] - need) // 2)
            self._rp_paragraph(draw, body, (inner[0], top, inner[2], inner[3]), k["text"], int(46 * ctx.body_scale), 28)

        self._rp_banner(draw, ctx, k, (P, banner_top, W - P, foot_top), solid)
        self._rp_footer(draw, ctx, k)
        return img
