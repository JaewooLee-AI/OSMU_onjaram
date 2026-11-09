"""에디토리얼 레이아웃 — Stitch 시안 1안(docs/design/stitch_시안1_카드뉴스.jpg)을 옮긴 모양.

시안에서 가져온 것(문구는 가져오지 않음 — 카드 글은 기획 결과와 브랜드 킷 값만 씁니다):
- 머리줄: 왼쪽 점 + 시리즈 라벨, 오른쪽 쪽 번호 알약(02 / 06)
- 작은 머리말(코랄): 카드 종류에 따라 '마음 체크'·'오늘의 실천' 등
- 왼쪽 정렬 제목, 강조어는 코랄 글씨
- 사진은 카드 폭을 꽉 채우지 않고 둥근 모서리로 안쪽에
- 목록은 흰 둥근 칸에 한 줄씩(체크 표시 / 번호 원 — 코랄·초록 번갈아)
- 요약 한 줄은 색 띠 안에(코랄 연한 띠 · 진초록 띠 · 세이지 연한 띠)
- 아래 얇은 선 + 작은 바닥 글(브랜드 이름 · 연락처는 표지·마지막 카드만)
- 색은 세이지·코랄·크림만

캔버스 크기는 렌더러의 WIDTH·HEIGHT(카드 비율)를 따르고, 글이 넘치면 글자 크기를 줄여 맞춥니다.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from cards.fonts import display_font, korean_font, text_height, wrap_text_balanced, wrap_text_px

KICKERS = {
    "checklist": "마음 체크", "steps": "오늘의 실천", "numbered": "핵심 정리", "howto": "이렇게 해 보세요",
    "qa": "묻고 답하기", "big_number": "숫자로 보기", "event_info": "안내", "comparison_table": "한눈에 비교",
    "call_to_action": "함께 걸어요", "quote": "마음에 남는 말",
}
LIST_TYPES = ("steps", "numbered", "checklist")
_LABEL_RE = r"^\s*(전화|이메일|메일|주소|홈페이지|예약|카카오톡|카톡|문의|위치|시간|운영|일시|장소|대상|신청|비용|일정)\s*[:：]?\s+(.+)$"


def _lines(body: str, limit: int = 6) -> List[str]:
    out = []
    for raw in (body or "").replace("\\n", "\n").split("\n"):
        line = re.sub(r"^\s*(?:[-•·*✓]|\d+[.)])\s*", "", raw).strip()
        if line:
            out.append(line)
    return out[:limit]


class EditorialLayoutMixin:
    """CardNewsRendererService에 섞어 쓰는 에디토리얼 레이아웃(layout="ed")."""

    ED_PAD = 72
    _ed_fs = 1.0        # 세로 길이에 따른 크기 배율(_layout_ed가 정함)
    ED_SHORTS = False   # 쇼츠 프레임으로 그릴 때(넘겨 보기 문구 없음). safe_top·safe_bottom은 렌더러 값(쇼츠 UI 가림 영역)

    # --- 색 ----------------------------------------------------------------
    def _ed_colors(self, ctx):
        from cards.card_renderer import mix, tint
        c = ctx.c
        if ctx.design.variant == "dark":   # 어두운 배경: 진초록 바탕, 흰 글자, 칸은 바탕보다 조금 밝게
            bg = getattr(ctx, "dark_bg", None) or "#26372C"
            return {
                "bg": bg, "ink": "#FFFFFF", "text": "#E6ECE7", "muted": mix(bg, "#FFFFFF", 0.55),
                "line": mix(bg, "#FFFFFF", 0.18), "panel": mix(bg, "#FFFFFF", 0.07), "accent": c.accent,
                "accent_tint": mix(bg, c.accent, 0.22), "accent_ink": tint(c.accent, 0.55),
                "sage_tint": mix(bg, c.secondary, 0.45), "sage_mid": mix(bg, c.secondary, 0.7), "green": tint(c.secondary, 0.35),
                "solid": c.secondary, "dark": True,
            }
        return {
            "bg": c.background, "ink": c.primary, "text": mix(c.primary, "#1F2420", 0.55), "muted": mix(c.primary, c.background, 0.45),
            "line": mix(c.primary, c.background, 0.86), "panel": "#FFFFFF", "accent": c.accent,
            "accent_tint": tint(c.accent, 0.86), "accent_ink": mix(c.accent, "#000000", 0.38),
            "sage_tint": tint(c.secondary, 0.86), "sage_mid": tint(c.secondary, 0.72), "green": c.secondary,
            "solid": c.primary, "dark": False,
        }

    # --- 공통 조각 ------------------------------------------------------------
    def _ed_header(self, draw, ctx, k) -> int:
        """머리줄. 반환: 다음 요소를 놓을 y."""
        W, P = self.WIDTH, self.ED_PAD
        y = 64 + getattr(self, "safe_top", 0)
        label = (getattr(ctx.el, "series_label", "") or "").strip() or ctx.kit.brand_name or ""
        last = ctx.index >= ctx.total - 1
        draw.ellipse([P, y + 8, P + 18, y + 26], fill=k["accent"] if last else k["ink"])
        if label:
            draw.text((P + 34, y + 17), label, font=display_font(30, label), fill=k["text"], anchor="lm")
        page = f"{ctx.index + 1:02d} / {ctx.total:02d}"
        pf = korean_font(26, "semibold")
        pw = int(pf.getlength(page)) + 40
        draw.rounded_rectangle([W - P - pw, y - 4, W - P, y + 38], radius=21, outline=k["line"], width=2, fill=k["bg"])
        draw.text((W - P - pw / 2, y + 17), page, font=pf, fill=k["muted"], anchor="mm")
        return y + 76

    def _ed_kicker(self, draw, ctx, k, y: int) -> int:
        kick = KICKERS.get(ctx.slide.slide_type, "")
        if not kick:
            return y
        f = display_font(30, kick)
        draw.text((self.ED_PAD, y), kick, font=f, fill=k["accent"])
        x = self.ED_PAD + f.getlength(kick) + 16
        draw.ellipse([x, y + 14, x + 10, y + 24], fill=k["accent"])
        return y + int(text_height(f) * 1.5)

    def _ed_title(self, draw, ctx, k, y: int, start: int, max_h: int) -> int:
        W, P = self.WIDTH, self.ED_PAD
        size = int(start * ctx.title_scale)
        while True:
            end = self._emph_title(draw, ctx, y, size, 40, 3, x=P, width=W - 2 * P, color=k["ink"],
                                   emph_color=k["accent"], measure=True, line_gap=1.28)
            if end - y <= max_h or size <= 40:
                break
            size -= 3
        return self._emph_title(draw, ctx, y, size, 40, 3, x=P, width=W - 2 * P, color=k["ink"],
                                emph_color=k["accent"], line_gap=1.28)

    def _ed_paragraph(self, draw, text_lines: List[str], box, color: str, start: int, minimum: int = 28,
                      weight: str = "regular", measure: bool = False) -> int:
        x0, y0, x1, y1 = box
        size = start
        while True:
            font = korean_font(size, weight)
            lines: List[str] = []
            for t in text_lines:   # 균형 줄바꿈: 마지막 줄에 한 낱말만 남지 않게
                lines += wrap_text_balanced(t, font, x1 - x0)
            lh = int(text_height(font) * 1.5)
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

    def _ed_photo(self, img: Image.Image, photo: Image.Image, box, radius: int = 32) -> None:
        x0, y0, x1, y1 = box
        fitted = self._cover_fit(photo, x1 - x0, y1 - y0)
        mask = Image.new("L", fitted.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fitted.width - 1, fitted.height - 1], radius=radius, fill=255)
        img.paste(fitted, (x0, y0), mask)

    def _ed_banner(self, draw, ctx, k, box, style: str) -> None:
        """요약 한 줄 띠. style: coral(연한 코랄) | solid(진초록) | sage(연한 세이지)."""
        text = (ctx.slide.takeaway or "").strip()
        if not text:
            return
        x0, y0, x1, y1 = box
        fill, color, outline = {"coral": (k["accent_tint"], k["accent_ink"], k["accent"]),
                                "solid": (k["solid"], "#FFFFFF", None),
                                "sage": (k["sage_tint"], k["ink"], k["line"])}[style]
        draw.rounded_rectangle(box, radius=24, fill=fill, outline=outline, width=2 if outline else 0)
        icon = 44
        ix = x0 + 32
        cy = (y0 + y1) // 2
        draw.ellipse([ix, cy - icon // 2, ix + icon, cy + icon // 2], fill=k["accent"] if style != "solid" else "#FFFFFF")
        self._ed_heart(draw, ix + icon / 2, cy + 1, 13, "#FFFFFF" if style != "solid" else k["solid"])
        tx = ix + icon + 24
        # 한 줄에 들어가면(32px까지 줄여서) 한 줄로, 아니면 두 줄로 — 두 줄일 때도 띠 높이 안에 들어가게 작게
        font, lines = self._fit_lines(text, x1 - tx - 30, int(40 * ctx.takeaway_scale), 32, 1, "bold")
        if lines and lines[-1].endswith("…"):
            font, lines = self._fit_lines(text, x1 - tx - 30, int(34 * ctx.takeaway_scale), 24, 2, "bold")
        lh = int(text_height(font) * 1.3)
        ty = cy - lh * len(lines) // 2
        for line in lines:
            draw.text((tx, ty), line, font=font, fill=color)
            ty += lh

    @staticmethod
    def _ed_heart(draw, cx: float, cy: float, r: float, fill: str) -> None:
        """작은 하트(글꼴에 기대지 않고 도형으로)."""
        q = r * 0.55
        draw.ellipse([cx - r, cy - r * 0.75, cx - r + 2 * q * 0.95, cy - r * 0.75 + 2 * q * 0.95], fill=fill)
        draw.ellipse([cx + r - 2 * q * 0.95, cy - r * 0.75, cx + r, cy - r * 0.75 + 2 * q * 0.95], fill=fill)
        draw.polygon([(cx - r + 0.5, cy - r * 0.2), (cx + r - 0.5, cy - r * 0.2), (cx, cy + r * 0.95)], fill=fill)

    def _ed_footer(self, draw, ctx, k) -> None:
        W, H, P = self.WIDTH, self.HEIGHT - getattr(self, "safe_bottom", 0), self.ED_PAD
        y = H - 92
        draw.line([P, y, W - P, y], fill=k["line"], width=2)
        ends = ctx.index == 0 or ctx.index >= ctx.total - 1
        left = ctx.kit.brand_name or ""
        kick = KICKERS.get(ctx.slide.slide_type, "")
        if kick and not ends:
            left = f"{left} · {kick}" if left else kick
        f = korean_font(26, "medium")
        if left:
            draw.text((P, y + 46), left, font=f, fill=k["muted"], anchor="lm")
        if ends and ctx.el.show_phone and ctx.kit.phone:
            right = f"상담 {ctx.kit.phone}"
            draw.text((W - P, y + 46), right, font=korean_font(26, "semibold"), fill=k["ink"], anchor="rm")
        elif not ends and not self.ED_SHORTS:
            draw.text((W - P, y + 46), "넘겨 보기 →", font=f, fill=k["muted"], anchor="rm")

    def _ed_rows(self, img, draw, ctx, k, items: List[str], box, mode: str) -> None:
        """흰 둥근 칸 목록. mode: check | number."""
        x0, y0, x1, y1 = box
        n = max(1, len(items))
        gap = 18
        row_h = min(int(170 * self._ed_fs), ((y1 - y0) - gap * (n - 1)) // n)
        total = row_h * n + gap * (n - 1)
        y = y0 + max(0, ((y1 - y0) - total) // 2)
        circle = min(64, row_h - 30)
        size = int(44 * ctx.body_scale * self._ed_fs)
        while True:   # 모든 칸이 같은 글자 크기가 되게 가장 긴 항목에 맞춘다
            font = korean_font(size, "semibold")
            tw = (x1 - x0) - circle - 84
            if all(len(wrap_text_px(it, font, tw)) * int(text_height(font) * 1.3) <= row_h - 24 for it in items) or size <= 26:
                break
            size -= 2
        lh = int(text_height(font) * 1.3)
        for i, it in enumerate(items):
            draw.rounded_rectangle([x0, y, x1, y + row_h], radius=22, fill=k["panel"], outline=k["line"], width=2)
            cx, cy = x0 + 28, y + row_h // 2
            if mode == "check":
                draw.ellipse([cx, cy - circle // 2, cx + circle, cy + circle // 2], outline=k["green"], width=3, fill=k["sage_tint"])
                s = circle / 64
                draw.line([(cx + 18 * s, cy + 1 * s), (cx + 28 * s, cy + 11 * s), (cx + 46 * s, cy - 9 * s)], fill=k["green"], width=max(3, int(5 * s)))
            else:
                fill = k["accent"] if i % 2 == 0 else k["green"]
                draw.ellipse([cx, cy - circle // 2, cx + circle, cy + circle // 2], fill=fill)
                num = f"{i + 1:02d}"
                draw.text((cx + circle / 2, cy), num, font=display_font(int(circle * 0.42), num), fill="#FFFFFF", anchor="mm")
            lines = wrap_text_px(it, font, tw)
            ty = cy - lh * len(lines) // 2
            for line in lines:
                draw.text((cx + circle + 28, ty), line, font=font, fill=k["text"])
                ty += lh
            y += row_h + gap

    def _ed_info_rows(self, draw, ctx, k, box) -> None:
        """'라벨 값' 줄(안내·문의): 흰 칸에 라벨 알약 + 값. 라벨 없는 줄은 안내 문장으로 위에."""
        x0, y0, x1, y1 = box
        rows: List[Tuple[str, str]] = []
        for line in _lines(ctx.slide.body_content, 7):
            m = re.match(r"^\s*([^:：]{1,8})\s*[:：]\s*(.+)$", line) or re.match(_LABEL_RE, line)
            rows.append((m.group(1).strip(), m.group(2).strip()) if m else ("", line))
        if not rows:
            return
        n = len(rows)
        gap = 18
        row_h = min(int(150 * self._ed_fs), ((y1 - y0) - gap * (n - 1)) // n)
        y = y0 + max(0, ((y1 - y0) - (row_h * n + gap * (n - 1))) // 2)
        for label, value in rows:
            draw.rounded_rectangle([x0, y, x1, y + row_h], radius=20, fill=k["panel"], outline=k["line"], width=2)
            cy = y + row_h // 2
            vx = x0 + 30
            if label:
                lf = display_font(30, label)
                pw = int(lf.getlength(label)) + 36
                draw.rounded_rectangle([x0 + 26, cy - 25, x0 + 26 + pw, cy + 25], radius=25, fill=k["sage_mid"])
                draw.text((x0 + 26 + pw / 2, cy), label, font=lf, fill=k["ink"], anchor="mm")
                vx += pw + 22
            weight = "semibold" if label else "regular"
            font, lines = self._fit_lines(value, x1 - vx - 26, int(40 * ctx.body_scale * self._ed_fs), 30, 1, weight)
            if lines and lines[-1].endswith("…"):   # 한 줄에 안 들어가면 두 줄로(칸 높이 안에 들어가게 작게)
                font, lines = self._fit_lines(value, x1 - vx - 26, min(36, (row_h - 30) // 3), 22, 2, weight)
            lh = int(text_height(font) * 1.3)
            ly = cy - lh * (len(lines) - 1) / 2
            for line in lines:   # 줄 가운데 기준(lm)으로 놓아 라벨 알약과 높이를 맞춘다
                draw.text((vx, ly), line, font=font, fill=k["text"], anchor="lm")
                ly += lh
            y += row_h + gap

    # --- 본체 ----------------------------------------------------------------
    def _layout_ed(self, ctx, photo: Optional[Image.Image]) -> Image.Image:
        from cards.card_renderer import normalize_table

        W, H, P = self.WIDTH, self.HEIGHT, self.ED_PAD
        Hc = H - getattr(self, "safe_top", 0) - getattr(self, "safe_bottom", 0)   # 실제로 쓰는 높이
        # 세로로 긴 화면(3:4·9:16 쇼츠)에서는 늘어난 높이만큼 글자·칸·사진을 키운다(4:5 기준 1.0, 최대 1.25배)
        self._ed_fs = max(1.0, min(1.25, Hc / 1350))
        k = self._ed_colors(ctx)
        img = Image.new("RGB", (W, H), k["bg"])
        draw = ImageDraw.Draw(img)
        t = ctx.slide.slide_type
        y = self._ed_header(draw, ctx, k)
        foot_top = H - getattr(self, "safe_bottom", 0) - 92 - 28             # 바닥 선 위 여백
        has_take = bool((ctx.slide.takeaway or "").strip())
        banner_h = 132 if has_take else 0
        banner_top = foot_top - banner_h
        content_bottom = banner_top - (32 if has_take else 0)

        if t == "cover":
            y += 10
            if photo is not None:
                ph = int(Hc * (0.42 if ctx.design.variant == "photo" else 0.36))
                self._ed_photo(img, photo, (P, y, W - P, y + ph))
                y += ph + 44
            else:   # 사진 없는 표지: 세이지 원 장식(글자 없음)
                cx, cy, r = W - P - 150, y + 150, 150
                for i, a in enumerate((0.0, 0.35, 0.7)):
                    from cards.card_renderer import tint
                    rr = r - i * 40
                    draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=tint(ctx.c.secondary, 0.82 + a * 0.2))
                draw.ellipse([cx + r * 0.45, cy + r * 0.45, cx + r * 0.45 + 70, cy + r * 0.45 + 70], fill=k["accent"])
                y += 340
            y = self._ed_title(draw, ctx, k, y, int(76 * self._ed_fs), int((content_bottom - y) * 0.55)) + 24
            body = _lines(ctx.slide.body_content, 4)
            if body and content_bottom - y > 60:
                self._ed_paragraph(draw, [" ".join(body)], (P, y, W - P, content_bottom), k["text"], int(36 * self._ed_fs), 26)
            self._ed_banner(draw, ctx, k, (P, banner_top, W - P, foot_top), "sage")
            self._ed_footer(draw, ctx, k)
            return img

        y = self._ed_kicker(draw, ctx, k, y)
        y = self._ed_title(draw, ctx, k, y, int(62 * self._ed_fs), int(260 * self._ed_fs)) + 30
        box = (P, y, W - P, content_bottom)
        body = _lines(ctx.slide.body_content, 6)
        style = "coral"

        if box[3] - box[1] < 80:
            pass   # 제목이 길어 내용 칸이 없으면 제목·요약 띠만
        elif t in LIST_TYPES and body:
            self._ed_rows(img, draw, ctx, k, body, box, "check" if t == "checklist" else "number")
            style = "sage" if t == "checklist" else "coral"
        elif t in ("call_to_action", "event_info"):
            self._ed_info_rows(draw, ctx, k, box)
            style = "solid"
        elif t == "big_number" and ctx.slide.stat_value:
            draw.rounded_rectangle(box, radius=28, fill=k["panel"], outline=k["line"], width=2)
            value = ctx.slide.stat_value
            size = 190
            while display_font(size, value).getlength(value) > (W - 2 * P) - 80 and size > 60:
                size -= 6
            cy = (box[1] + box[3]) // 2 - 30
            draw.text((W / 2, cy), value, font=display_font(size, value), fill=k["accent"], anchor="mm")
            if ctx.slide.stat_label:
                lf, lines = self._fit_lines(ctx.slide.stat_label, W - 2 * P - 80, 40, 26, 2, "semibold")
                ly = cy + size // 2 + 10
                for line in lines:
                    draw.text((W / 2, ly), line, font=lf, fill=k["text"], anchor="ma")
                    ly += int(text_height(lf) * 1.3)
        elif t == "comparison_table" and all(normalize_table(ctx.slide.comparison_table)):
            header, rows = normalize_table(ctx.slide.comparison_table)
            draw.rounded_rectangle(box, radius=28, fill=k["panel"], outline=k["line"], width=2)
            self._draw_table(draw, header, rows, (box[0] + 20, box[1] + 20, box[2] - 20, box[3] - 20), ctx)
        elif photo is not None:
            # 사진(둥근 모서리) + 그 아래 본문. 본문이 길면 사진을 줄인다.
            text_need = self._ed_paragraph(draw, body or [""], (P, 0, W - P, 10_000), k["text"], int(38 * ctx.body_scale * self._ed_fs), 30, measure=True)
            ph = max(int((box[3] - box[1]) * 0.42), (box[3] - box[1]) - text_need - 36)
            if ctx.design.variant == "photo":   # 큰 사진: 본문(34px 기준)이 다 들어갈 자리를 남기고 나머지를 사진으로
                need34 = self._ed_paragraph(draw, body or [""], (P, 0, W - P, 10_000), k["text"], int(34 * self._ed_fs), 34, measure=True)
                ph = max(int((box[3] - box[1]) * 0.42), (box[3] - box[1]) - need34 - 40)
            ph = min(ph, int((box[3] - box[1]) * (0.68 if ctx.design.variant == "photo" else 0.62)))
            self._ed_photo(img, photo, (P, box[1], W - P, box[1] + ph))
            self._ed_paragraph(draw, body, (P, box[1] + ph + 32, W - P, box[3]), k["text"], int(38 * ctx.body_scale * self._ed_fs), 26)
        elif body and box[3] - box[1] >= 140:
            # 글 카드: 흰 둥근 칸에 본문(왼쪽 코랄 세로선)
            draw.rounded_rectangle(box, radius=28, fill=k["panel"], outline=k["line"], width=2)
            inner = (P + 56, box[1] + 48, W - P - 44, box[3] - 40)
            need = self._ed_paragraph(draw, body, inner, k["text"], int(48 * ctx.body_scale), 28, measure=True)
            top = inner[1] + max(0, (inner[3] - inner[1] - need) // 2)
            if need > 40:
                draw.rounded_rectangle([P + 30, top + 6, P + 36, min(inner[3], top + need - 14)], radius=3, fill=k["accent"])
            self._ed_paragraph(draw, body, (inner[0], top, inner[2], inner[3]), k["text"], int(48 * ctx.body_scale), 28)
            style = "solid" if ctx.index % 2 == 0 else "coral"
        else:
            style = "solid" if ctx.index % 2 == 0 else "coral"   # 본문이 없으면 제목·요약 띠만

        self._ed_banner(draw, ctx, k, (P, banner_top, W - P, foot_top), style)
        self._ed_footer(draw, ctx, k)
        return img
