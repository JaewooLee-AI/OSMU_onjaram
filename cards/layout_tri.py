"""3단 레이아웃 — 위 텍스트 / 가운데 미디어 / 아래 텍스트.

치과병원 카드뉴스·쇼츠(설계안 §3)에서 확인한 구성입니다. 위쪽에 제목, 가운데에 사진·영상 또는 인포그래픽, 아래쪽에
소속·이름·핵심 한 줄. 세 영역의 높이는 `DesignTemplate.ratio`(예: [2, 5, 3])로 정하고, 카드(4:5)와 쇼츠(9:16)가
같은 템플릿을 쓰도록 캔버스 크기는 렌더러의 WIDTH·HEIGHT를 따릅니다. 쇼츠는 `safe_top`·`safe_bottom`(UI 가림 영역)을
비워 둡니다.

가운데 미디어 자리:
- 사진이 있으면 폭을 꽉 채워 자릅니다(얼굴이 잘리지 않게 위쪽 기준). 사진 안 캡션·QR을 올릴 수 있습니다.
- 사진이 없으면 슬라이드 종류에 따른 인포그래픽(번호 단계·체크리스트·빅넘버)을 AI 호출 없이 그립니다.
- 그것도 아니면 글 패널.
"""
from __future__ import annotations

import re
from typing import List, Optional

from PIL import Image, ImageDraw

from cards.fonts import display_font, korean_font, text_height, wrap_text_px

_DARK_BG = "#23262B"
STEP_TYPES = ("numbered", "steps")
CHECK_TYPES = ("checklist",)


def _items(body: str, limit: int = 6) -> List[str]:
    """본문 줄 → 항목(앞의 번호·기호는 뗀다)."""
    out = []
    for raw in (body or "").replace("\\n", "\n").split("\n"):
        line = re.sub(r"^\s*(?:[-•·*]|\d+[.)])\s*", "", raw).strip()
        if line:
            out.append(line)
    return out[:limit]


class TriLayoutMixin:
    """CardNewsRendererService에 섞어 쓰는 3단 레이아웃."""

    safe_top = 0       # 쇼츠용: 위쪽 UI 안전 여백(px)
    safe_bottom = 0

    def _tri_zones(self, ratio: List[int]):
        parts = [max(1, int(x)) for x in (ratio or [2, 5, 3])[:3]]
        while len(parts) < 3:
            parts.append(1)
        usable = self.HEIGHT - self.safe_top - self.safe_bottom
        total = sum(parts)
        h1 = round(usable * parts[0] / total)
        h2 = round(usable * parts[1] / total)
        h3 = usable - h1 - h2
        y0 = self.safe_top
        return (y0, y0 + h1), (y0 + h1, y0 + h1 + h2), (y0 + h1 + h2, y0 + h1 + h2 + h3)

    # ------------------------------------------------------------------
    def _layout_tri(self, ctx, photo: Optional[Image.Image]) -> Image.Image:
        from cards.card_renderer import make_qr, mix, normalize_table, tint  # 순환 import 방지

        W, H = self.WIDTH, self.HEIGHT
        dark = ctx.design.tri_theme == "dark"
        c = ctx.c
        if getattr(ctx, "custom_colors", False):     # 카드별 색 덮어쓰기: 색은 모두 ctx.c(배경·글자)에서 온다
            dark = False
        bg = (getattr(ctx, "dark_bg", None) or _DARK_BG) if dark else c.background
        fg = "#FFFFFF" if dark else c.primary
        sub = "#E2E8F0" if dark else c.secondary
        img = Image.new("RGB", (W, H), bg)
        draw = ImageDraw.Draw(img)
        (t0, t1), (m0, m1), (b0, b1) = self._tri_zones(ctx.design.ratio)
        M = self.MARGIN

        # --- 위: 제목 --------------------------------------------------------
        text_w = W - 2 * M
        box_h = t1 - t0
        # 제목은 줄 수뿐 아니라 영역 높이에 맞을 때까지 글자 크기를 줄인다(3줄 긴 제목이 가운데 영역을 침범하지 않게).
        size = int((78 if box_h >= 260 else 60) * ctx.title_scale)
        emph = c.accent if dark else None
        while True:
            need = self._emph_title(draw, ctx, 0, size, 40, 3, x=M, width=text_w, color=fg, center=True,
                                    emph_color=emph, measure=True)
            if need <= box_h - 36 or size <= 40:
                break
            size -= 4
        top = t0 + max(18, (box_h - need) // 2)
        self._emph_title(draw, ctx, top, size, 40, 3, x=M, width=text_w, color=fg, center=True, emph_color=emph)

        # --- 가운데: 미디어 --------------------------------------------------
        mid_h = m1 - m0
        slide_type = ctx.slide.slide_type
        if photo is not None:
            fitted = self._cover_fit(photo, W, mid_h)
            img.paste(fitted, (0, m0))
            self._tri_overlays(img, ctx, m0, m1, make_qr)
        else:
            panel = (M // 2, m0 + 10, W - M // 2, m1 - 10)
            panel_fill = "#2F333A" if dark else (mix(bg, fg, 0.10) if getattr(ctx, "custom_colors", False) else tint(c.secondary, 0.9))
            draw.rounded_rectangle(panel, radius=ctx.design.radius, fill=panel_fill)
            if slide_type in STEP_TYPES or slide_type in CHECK_TYPES:
                self._tri_steps(img, draw, ctx, panel, dark, check=slide_type in CHECK_TYPES)
            elif slide_type == "big_number" and ctx.slide.stat_value:
                self._tri_big_number(draw, ctx, panel, dark)
            elif slide_type == "event_info":
                self._tri_event(draw, ctx, panel, dark)
            elif slide_type == "comparison_table" and all(normalize_table(ctx.slide.comparison_table)):
                header, rows = normalize_table(ctx.slide.comparison_table)
                self._draw_table(draw, header, rows, (panel[0] + 20, panel[1] + 20, panel[2] - 20, panel[3] - 20), ctx)
            else:
                self._tri_text_panel(draw, ctx, panel, dark)
            if ctx.el.qr_url.strip() or ctx.el.qr_image:
                self._tri_overlays(img, ctx, m0, m1, make_qr, caption=False)

        # --- 아래: 요약 한 줄 + 소속·연락처 ---------------------------------------
        takeaway = (ctx.slide.takeaway or "").strip()
        byline_h = 130   # 아래쪽 소속·연락처 줄이 차지하는 높이
        if takeaway:
            font, lines = self._fit_lines(takeaway, text_w, int(56 * ctx.takeaway_scale), 32, 2, "bold")
            lh = int(text_height(font) * 1.25)
            avail = (b1 - byline_h) - b0
            y = b0 + max(16, (avail - lh * len(lines)) // 2)
            for line in lines:
                draw.text((W / 2, y), line, font=font, fill=c.accent if dark else c.secondary, anchor="ma")
                y += lh
        bottom = b1 - 26
        name = ctx.kit.brand_name if self._logo_visible(ctx) else ""
        sub_line = "  |  ".join(p for p in (ctx.kit.footer_text, f"상담 {ctx.kit.phone}" if ctx.el.show_phone and ctx.kit.phone else "") if p)
        if sub_line:
            draw.text((W / 2, bottom), sub_line, font=korean_font(30, "medium"), fill=sub, anchor="ms")
            bottom -= 48
        if name:
            draw.text((W / 2, bottom), name, font=display_font(38, name), fill=fg, anchor="ms")
        return img

    # ------------------------------------------------------------------
    def _tri_overlays(self, img: Image.Image, ctx, m0: int, m1: int, make_qr, caption: bool = True) -> None:
        """사진 위 캡션(왼쪽 아래)과 QR(오른쪽 아래)."""
        W = self.WIDTH
        draw = ImageDraw.Draw(img)
        if caption:
            cap = _items(ctx.slide.body_content, 1)
            if cap:
                font = korean_font(36, "bold")
                tw = int(font.getlength(cap[0]))
                x, y = 36, m1 - 34
                shade = Image.new("RGBA", (tw + 36, 64), (0, 0, 0, 120))
                img.paste(shade, (x - 18, y - 48), shade)
                draw.text((x, y), cap[0], font=font, fill="#FFFFFF", anchor="ls")
        qr = make_qr(ctx.el)
        if qr is not None:
            size = 150
            qr = qr.resize((size, size))
            img.paste(qr, (W - size - 30, m1 - size - 24))

    def _tri_text_panel(self, draw, ctx, panel, dark: bool) -> None:
        x0, y0, x1, y1 = panel
        items = _items(ctx.slide.body_content, 5) or [ctx.slide.body_content or ""]
        if not any(i.strip() for i in items):   # 사진도 내용도 없는 표지: 비워 두지 않고 브랜드 한 줄을 크게 보여 준다
            tagline = ctx.kit.tagline or ctx.kit.brand_name
            font, lines = self._fit_lines(tagline, (x1 - x0) - 120, 56, 34, 3, "bold")
            lh = int(text_height(font) * 1.3)
            y = (y0 + y1) // 2 - lh * len(lines) // 2
            for line in lines:
                draw.text(((x0 + x1) // 2, y), line, font=font, fill=ctx.c.accent if dark else ctx.c.secondary, anchor="ma")
                y += lh
            return
        color = "#FFFFFF" if dark else ctx.c.primary
        pad = 40
        width = (x1 - x0) - 2 * pad
        size = int(56 * ctx.body_scale)
        while True:
            font = korean_font(size, "medium")
            lines: List[str] = []
            for it in items:
                lines += wrap_text_px(it, font, width - 40) + [""]
            lines = lines[:-1] if lines else lines
            lh = int(text_height(font) * 1.35)
            if lh * len(lines) <= (y1 - y0) - 2 * pad or size <= 24:
                break
            size -= 2
        y = y0 + max(pad, ((y1 - y0) - lh * len(lines)) // 2)
        for line in lines:
            if line:
                draw.text((x0 + pad, y), line, font=font, fill=color)
            y += lh

    def _tri_event(self, draw, ctx, panel, dark: bool) -> None:
        """행사·이벤트 안내: '라벨: 값' 줄을 라벨 알약 + 값으로. 라벨이 없는 줄은 값만."""
        x0, y0, x1, y1 = panel
        rows = []
        for line in (ctx.slide.body_content or "").replace("\\n", "\n").splitlines():
            if not line.strip():
                continue
            m = re.match(r"^\s*([^:：]{1,8})\s*[:：]\s*(.+)$", line)
            rows.append((m.group(1).strip(), m.group(2).strip()) if m else ("", line.strip()))
        rows = rows[:6]
        if not rows:
            return self._tri_text_panel(draw, ctx, panel, dark)
        pad = 28
        label_w = max((int(display_font(34, l).getlength(l)) + 40 for l, _ in rows if l), default=0)
        value_x = x0 + pad + (label_w + 26 if label_w else 0)
        text_color = "#FFFFFF" if dark else ctx.c.primary
        row_h = (y1 - y0 - 2 * pad) // len(rows)
        size = int(46 * ctx.body_scale)
        while True:
            font = korean_font(size, "semibold")
            lh = int(text_height(font) * 1.2)
            wrapped = [wrap_text_px(v, font, x1 - pad - value_x) or [""] for _, v in rows]
            if all(len(w) * lh <= row_h - 10 for w in wrapped) or size <= 26:
                break
            size -= 2
        for (label, _), lines, n in zip(rows, wrapped, range(len(rows))):
            top = y0 + pad + n * row_h
            mid = top + row_h // 2
            if label:
                ph = min(64, row_h - 12)
                self._pill(draw, (x0 + pad, mid - ph // 2), label, display_font(34, label), ctx.c.accent if dark else ctx.c.primary,
                           "#FFFFFF", pad_x=20, height=ph, radius=ph // 2)
            ty = mid - len(lines) * lh // 2
            for line in lines:
                draw.text((value_x, ty), line, font=font, fill=text_color)
                ty += lh

    def _tri_big_number(self, draw, ctx, panel, dark: bool) -> None:
        x0, y0, x1, y1 = panel
        cx = (x0 + x1) // 2
        value = ctx.slide.stat_value
        size = 170
        while display_font(size, value).getlength(value) > (x1 - x0) - 80 and size > 60:
            size -= 6
        font = display_font(size, value)
        draw.text((cx, (y0 + y1) // 2 - 30), value, font=font, fill=ctx.c.accent if dark else ctx.c.primary, anchor="mm")
        if ctx.slide.stat_label:
            lf, lines = self._fit_lines(ctx.slide.stat_label, (x1 - x0) - 100, 46, 28, 2, "medium")
            ly = (y0 + y1) // 2 + size // 2 + 10
            for line in lines:
                draw.text((cx, ly), line, font=lf, fill="#E2E8F0" if dark else ctx.c.secondary, anchor="ma")
                ly += int(text_height(lf) * 1.25)

    def _tri_steps(self, img, draw, ctx, panel, dark: bool, check: bool = False) -> None:
        """번호(또는 체크) 원 + 문구. 항목 1~3개는 세로, 4개 이상은 2열."""
        x0, y0, x1, y1 = panel
        items = _items(ctx.slide.body_content, 6)
        if not items:
            return
        # 글자를 크게 키울 때(body_scale)는 한 줄에 하나씩 세로로 늘어놓아야 큰 글자가 들어간다
        cols = 1 if (len(items) <= 3 or (ctx.body_scale > 1.25 and len(items) <= 5)) else 2
        rows = -(-len(items) // cols)
        pad = 30
        cell_w = ((x1 - x0) - 2 * pad) // cols
        cell_h = ((y1 - y0) - 2 * pad) // rows
        circle = min(84, cell_h - 16)
        text_color = "#FFFFFF" if dark else ctx.c.primary
        for i, item in enumerate(items):
            col, row = i % cols, i // cols
            cx = x0 + pad + col * cell_w
            cy = y0 + pad + row * cell_h
            mid = cy + cell_h // 2
            draw.ellipse([cx, mid - circle // 2, cx + circle, mid + circle // 2], fill=ctx.c.accent)
            label = "✓" if check else str(i + 1)
            draw.text((cx + circle / 2, mid), label, font=display_font(int(circle * 0.55), label), fill="#FFFFFF", anchor="mm")
            font, lines = self._fit_lines(item, cell_w - circle - 40, int(50 * ctx.body_scale), 26, 3, "medium")
            lh = int(text_height(font) * 1.2)
            ty = mid - lh * len(lines) // 2
            for line in lines:
                draw.text((cx + circle + 22, ty), line, font=font, fill=text_color)
                ty += lh
