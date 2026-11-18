"""에디토리얼 레이아웃(layout="ed") — 온자람 '공감·회복' 트랙의 기본 카드·쇼츠 모양.

- 위 가는 색 띠 + 머리말 배지(카드 종류) + 시리즈 이름 + 쪽 번호
- 표지는 전용 화면(사진을 가득 깔고 큰 제목), 상담 안내는 전용 화면(큰 전화번호 칸 + 주소)
- 목록(단계·번호·체크)은 "1단계:" 같은 중복 번호를 떼고 칸마다 제목/설명 2단으로, 항목이 적으면 칸과 글자를 키워 빈 곳을 채움
- 아래 요약 한 줄은 카드 종류에 따라 진한 띠 / 가는 줄 / 없음(`take_mode`)
- 쇼츠(ED_SHORTS=True)는 위·아래 UI 가림 영역을 비우고 요약 띠·바닥글 없이 그림(자막이 그 자리를 맡음)

색은 디자인 색(ctx.c)에서 만들고 고정 색·문구는 cards/tokens.py(값은 core/brand_seed.CARD_TOKENS)에서 옵니다.
k["gold"]는 '보조 포인트 색'(온자람은 세이지), k["navy"]는 '진한 주조색'이라는 뜻의 이름입니다(다른 고객사 코드와 맞춘 이름).
모서리는 디자인의 radius가 크면(둥근 디자인) 두 배로 둥글게 그립니다(`_r`).
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from cards import tokens as T
from cards.fonts import display_font, korean_font, text_height, wrap_text_balanced, wrap_text_px

KICKERS = T.KICKERS      # 카드 종류별 머리말 — 값은 cards/tokens.py(고객사 값은 core/brand_seed.CARD_TOKENS)
LIST_TYPES = ("steps", "numbered", "checklist")
_LABEL_RE = r"^\s*(휴대폰|전화|이메일|메일|주소|홈페이지|예약|카카오톡|카톡|문의|위치|시간|운영|일시|장소|대상|신청|비용|일정|방문)\s+(?!또는\b|및\b|이나\b|으로\b|로\b)(.+)$"
_PREFIX_RE = re.compile(
    r"^\s*(?:제?\s*\d+\s*(?:단계|번|장|항목)|[①-⑳]|\d+\s*[.)]|첫째|둘째|셋째|넷째|다섯째|여섯째)\s*[:：.,\-—–]?\s*"
)
_SPLIT_RE = re.compile(r"\s+[—–-]\s+|\s*[:：]\s+")


def strip_step_prefix(text: str) -> str:
    """목록 문구 앞의 '1단계:', '1.', '첫째,' 같은 중복 번호 접두어를 제거한다."""
    return _PREFIX_RE.sub("", (text or "").strip()).strip()


def split_item_head_desc(text: str) -> Tuple[str, str]:
    """번호 접두어를 떼고 핵심 제목(head)과 보조 설명(desc) 2단으로 나눈다."""
    cleaned = strip_step_prefix(text)
    if not cleaned:
        return "", ""
    m = _SPLIT_RE.split(cleaned, maxsplit=1)
    if len(m) == 2 and m[0].strip() and m[1].strip():
        return m[0].strip(), m[1].strip()
    return cleaned, ""


def on_color(fill: str) -> str:
    """색 면 위에 올릴 글자색: 어두운 면이면 흰색, 밝은 면이면 진한 색."""
    from cards.card_renderer import luminance
    return T.WHITE if luminance(fill) < 0.6 else T.NAVY


def _draw_footer_row(
    draw,
    P: int,
    W: int,
    y_mid: int,
    left: str,
    right: str,
    left_fill: str,
    right_fill: str,
    left_weight: str = "medium",
    right_weight: str = "medium",
    right_size: int = 26,
) -> None:
    """바닥 글 좌·우 문구가 길어도 가운데서 겹치지 않게 크기를 줄여 배치한다."""
    rf = korean_font(right_size, right_weight)
    rw = int(rf.getlength(right)) if right else 0
    if left:
        max_lw = max(120, (W - 2 * P) - rw - (32 if right else 0))
        lf = korean_font(26, left_weight)
        for size in (26, 24, 22):
            cand = korean_font(size, left_weight)
            lf = cand
            if cand.getlength(left) <= max_lw:
                break
        label = left
        while lf.getlength(label) > max_lw and len(label) > 4:
            label = label[:-2] + "…"
        draw.text((P, y_mid), label, font=lf, fill=left_fill, anchor="lm")
    if right:
        draw.text((W - P, y_mid), right, font=rf, fill=right_fill, anchor="rm")


def _lines(body: str, limit: int = 6) -> List[str]:
    out = []
    for raw in (body or "").replace("\\n", "\n").split("\n"):
        line = re.sub(r"^\s*(?:[-•·*✓]|\d+[.)])\s*", "", raw).strip()
        if line:
            out.append(line)
    return out[:limit]


_PHONE_RE = re.compile(r"\d{2,4}[-.\s]\d{3,4}[-.\s]\d{4}")


def parse_info_rows(body: str, limit: int = 7) -> List[Tuple[str, str]]:
    """안내 카드 본문을 (라벨, 값) 줄로 나눈다. 라벨이 없는 문장은 ("", 문장)."""
    rows: List[Tuple[str, str]] = []
    for line in _lines(body, limit):
        m = re.match(r"^\s*([^:：]{1,8})\s*[:：]\s*(.+)$", line) or re.match(_LABEL_RE, line)
        rows.append((m.group(1).strip(), m.group(2).strip()) if m else ("", line))
    return rows


def word_fit_size(text: str, size: int, width: int, minimum: int) -> int:
    """가장 긴 낱말이 한 줄에 들어가는 글자 크기 — 제목이 낱말 중간에서 끊기지 않게 한다."""
    words = [w for w in re.split(r"\s+", (text or "").replace("*", "").replace("\u00a0", " ")) if w]
    if not words:
        return size
    longest = max(words, key=len)
    while size > minimum and display_font(size, text).getlength(longest) > width:
        size -= 2
    return size


def take_mode(slide) -> str:
    """아래 요약 한 줄의 모양: bar(진한 띠) | line(가는 줄) | none. 카드 style["takeaway"]가 우선이고,
    비우면 글·사진 카드만 진한 띠, 목록·표·숫자·안내 카드는 가는 줄 — 모든 카드가 같은 띠로 끝나지 않게 한다."""
    if not (slide.takeaway or "").strip():
        return "none"
    v = (slide.style or {}).get("takeaway")
    if v in ("bar", "line", "none"):
        return v
    return "bar" if slide.slide_type in ("body", "single", "quote", "qa") else "line"


def draw_take_line(renderer, draw, ctx, k, box) -> None:
    """요약 한 줄 '가는 줄' 모양: 위 가는 선 + 골드 짧은 막대 + 굵은 글자(바탕색 그대로)."""
    text = (ctx.slide.takeaway or "").strip()
    x0, y0, x1, y1 = box
    gold = k.get("gold", k["accent"])
    draw.line([x0, y0, x1, y0], fill=k["line"], width=2)
    cy = (y0 + y1) // 2 + 2
    draw.rectangle([x0, cy - 20, x0 + 7, cy + 20], fill=gold)
    font, lines = renderer._fit_lines(text, x1 - x0 - 30, int(36 * ctx.takeaway_scale), 28, 1, "bold")
    if lines and lines[-1].endswith("…"):
        font, lines = renderer._fit_lines(text, x1 - x0 - 30, int(30 * ctx.takeaway_scale), 22, 2, "bold")
    lh = int(text_height(font) * 1.28)
    ty = cy - lh * len(lines) // 2
    for ln in lines:
        draw.text((x0 + 30, ty), ln, font=font, fill=k["ink"])
        ty += lh


def body_start_size(lines: List[str]) -> int:
    """글만 있는 칸의 시작 글자 크기 — 글이 짧을수록 크게 시작해 칸을 채운다(넘치면 그리는 쪽에서 줄인다)."""
    n = sum(len(t) for t in lines)
    return 58 if n < 50 else 50 if n < 100 else 44


TEXT_CARD_TYPES = ("body", "single", "quote")
QA_BADGE = 36            # 묻고 답하기 Q·A 동그라미 반지름


def photo_shape(photo) -> str:
    """사진 모양: portrait(세로) | landscape(가로) | square — 카드가 사진 칸 모양을 고를 때 쓴다."""
    if photo is None:
        return "none"
    r = photo.height / max(1, photo.width)
    return "portrait" if r > 1.12 else "landscape" if r < 0.9 else "square"


def _draw_check_mark(draw, cx: float, cy: float, size: float, color: str) -> None:
    """벡터 체크 마크(폰트 의존 없음)."""
    s = size / 24.0
    draw.line(
        [(cx - 7 * s, cy + 1 * s), (cx - 2 * s, cy + 6 * s), (cx + 8 * s, cy - 6 * s)],
        fill=color,
        width=max(2, int(3.5 * s)),
        joint="curve",
    )


class EditorialLayoutMixin:
    """CardNewsRendererService에 섞어 쓰는 에디토리얼 레이아웃(layout="ed")."""

    ED_PAD = T.SPACE["pad"]
    _ed_fs = 1.0        # 세로 길이에 따른 크기 배율(_layout_ed가 정함)
    ED_SHORTS = False   # 쇼츠 프레임으로 그릴 때. safe_top·safe_bottom은 렌더러 값(쇼츠 UI 가림 영역)
    _ed_round = 1.0     # 모서리 배율 — 둥근 디자인(radius 24 이상)은 2배(_layout_ed가 정함)

    def _r(self, n: int) -> int:
        return int(round(n * self._ed_round))

    # --- 색 ----------------------------------------------------------------
    def _ed_colors(self, ctx):
        from cards.card_renderer import luminance, mix, tint
        c = ctx.c
        if ctx.design.variant == "dark":   # 어두운 배경: 미드나잇 네이비 바탕, 아이보리 글자, 로열 골드 포인트
            bg = getattr(ctx, "dark_bg", None) or T.NAVY
            gold = T.GOLD_LIGHT if luminance(c.secondary) < 0.5 else c.secondary   # 어두운 바탕에서 읽히는 밝기만
            accent = gold if luminance(c.accent) < 0.18 else c.accent
            return {
                "bg": bg, "ink": T.IVORY, "text": T.IVORY_TEXT, "muted": mix(bg, T.IVORY, 0.58),
                "line": mix(bg, T.IVORY, 0.18), "panel": mix(bg, T.IVORY, 0.08),
                "row_panel": mix(bg, T.IVORY, 0.10), "accent": accent, "gold": gold,
                "navy": mix(bg, T.BLACK, 0.35), "deep": mix(bg, T.BLACK, 0.45),
                "chip": mix(bg, T.IVORY, 0.14), "soft": mix(bg, T.IVORY, 0.20),
                "accent_tint": mix(bg, accent, 0.20), "accent_ink": tint(accent, 0.45),
                "sage_tint": mix(bg, gold, 0.16), "sage_mid": mix(bg, gold, 0.30), "green": gold,
                "solid": mix(bg, T.BLACK, 0.35), "dark": True,
            }
        gold = c.secondary
        sand = mix(c.background, T.SAND_MIX, 0.26) if luminance(c.background) > 0.7 else mix(c.background, T.WHITE, 0.08)
        navy = c.primary
        return {
            "bg": c.background, "ink": c.primary, "text": mix(c.primary, T.CHARCOAL, 0.65),
            "muted": mix(c.primary, c.background, 0.48),
            "line": mix(c.primary, c.background, 0.84), "panel": T.WHITE, "row_panel": sand,
            "accent": c.accent, "gold": gold, "navy": navy,
            "deep": mix(navy, T.BLACK, 0.45), "chip": mix(navy, T.IVORY, 0.14), "soft": mix(navy, T.IVORY, 0.20),
            "accent_tint": tint(c.accent, 0.90), "accent_ink": mix(c.accent, navy, 0.35),
            "sage_tint": sand, "sage_mid": tint(gold, 0.78), "green": c.primary,
            "solid": navy, "dark": False,
        }

    # --- 공통 조각 ------------------------------------------------------------
    def _ed_header(self, draw, ctx, k) -> int:
        """머리줄. 반환: 다음 요소를 놓을 y."""
        W, P = self.WIDTH, self.ED_PAD
        top = getattr(self, "safe_top", 0)
        kick = KICKERS.get(ctx.slide.slide_type, "")
        # 브랜드 이름은 바닥글에 있으므로 머리줄에는 시리즈 이름만(없으면 비움) — 같은 이름이 한 장에 두 번 나오지 않게
        series = (getattr(ctx.el, "series_label", "") or "").strip()

        if self.ED_SHORTS:
            # 쇼츠 9:16: safe_top 바깥은 k["bg"] 유지, 활성 영역 맨 위에 미드나잇 네이비 브리핑 헤더 바 배치
            bar_h = 84
            draw.rectangle([0, top, W, top + bar_h], fill=k["navy"])
            draw.rectangle([0, top, W, top + 6], fill=k.get("gold", T.GOLD))
            draw.rectangle([0, top + bar_h - 3, W, top + bar_h], fill=k.get("gold", T.GOLD))
            cy = top + bar_h // 2 + 1
            badge_txt = f"● {kick or T.COPY['shorts_badge']}"
            bf = display_font(24, badge_txt)
            bw = int(bf.getlength(badge_txt)) + 30
            draw.rounded_rectangle([P, cy - 20, P + bw, cy + 20], radius=self._r(5), fill=k["accent"])
            draw.text((P + bw / 2, cy), badge_txt, font=bf, fill=T.WHITE, anchor="mm")
            if series:
                sf = korean_font(24, "semibold")
                max_sw = max(120, W - P - 150 - (P + bw + 20))
                lbl = series
                while sf.getlength(lbl) > max_sw and len(lbl) > 4:
                    lbl = lbl[:-2] + "…"
                draw.text((P + bw + 18, cy), lbl, font=sf, fill=T.IVORY_TEXT, anchor="lm")
            page = f"{ctx.index + 1:02d} / {ctx.total:02d}"
            pf = korean_font(24, "bold")
            pw = int(pf.getlength(page)) + 30
            draw.rounded_rectangle([W - P - pw, cy - 20, W - P, cy + 20], radius=self._r(5), fill=k["chip"])
            draw.text((W - P - pw / 2, cy), page, font=pf, fill=T.IVORY, anchor="mm")
            return top + bar_h + 26

        # 4:5 / 3:4 카드뉴스: 상단 8px 로열 골드 액센트 바 + 직각 버건디 배지 + 인덱스 태그
        draw.rectangle([0, top, W, top + 8], fill=k.get("gold", k["accent"]))
        y = top + 46
        kh = 44
        kw = -18                             # 머리말이 없는 카드(글·한 장)는 배지 없이 시리즈 이름부터
        if kick:
            kf = display_font(24, kick)
            kw = int(kf.getlength(kick)) + 32
            badge_fill = k["gold"] if k["dark"] else k["accent"]
            draw.rounded_rectangle([P, y, P + kw, y + kh], radius=self._r(5), fill=badge_fill)
            draw.text((P + kw / 2, y + kh / 2), kick, font=kf, fill=on_color(badge_fill), anchor="mm")

        page = f"{ctx.index + 1:02d} / {ctx.total:02d}"
        pf = korean_font(23, "bold")
        pw = int(pf.getlength(page)) + 34
        draw.rounded_rectangle([W - P - pw, y + 1, W - P, y + kh - 1], radius=self._r(5),
                               fill=k.get("row_panel", k["panel"]), outline=k["line"], width=1)
        draw.text((W - P - pw / 2, y + kh / 2), page, font=pf, fill=k["ink"], anchor="mm")

        if series:
            sf = korean_font(24, "semibold")
            max_sw = max(80, (W - P - pw - 18) - (P + kw + 18))
            lbl = series
            while sf.getlength(lbl) > max_sw and len(lbl) > 4:
                lbl = lbl[:-2] + "…"
            draw.text((P + kw + 18, y + kh / 2), lbl, font=sf, fill=k["muted"], anchor="lm")

        rule_y = y + kh + 20
        draw.line([P, rule_y, W - P, rule_y], fill=k["line"], width=2)
        draw.line([P, rule_y, P + 120, rule_y], fill=k.get("gold", k["accent"]), width=4)
        return rule_y + 24

    def _ed_title(self, draw, ctx, k, y: int, start: int, max_h: int, bar: bool = True, badge: str = "") -> int:
        W, P = self.WIDTH, self.ED_PAD
        tx = P + (QA_BADGE * 2 + 24 if badge else 18 if bar else 0)
        tw = W - P - tx
        emph, mark = self._emph_style(ctx, k)
        size = word_fit_size(ctx.slide.lead_headline, int(start * ctx.title_scale), tw, 38)
        while True:
            end = self._emph_title(draw, ctx, y, size, 38, 3, x=tx, width=tw, color=k["ink"],
                                   emph_color=emph, mark=mark, measure=True, line_gap=1.24)
            if end - y <= max_h or size <= 38:
                break
            size -= 3
        end = self._emph_title(draw, ctx, y, size, 38, 3, x=tx, width=tw, color=k["ink"],
                               emph_color=emph, mark=mark, line_gap=1.24)
        if badge:
            first_h = int(text_height(display_font(size, ctx.slide.lead_headline)) * 1.24)
            self._fit_badge(draw, P, y + max(0, first_h // 2 - QA_BADGE), badge, k["accent"])
        elif bar and end > y + 8:
            draw.rectangle([P, y + 6, P + 7, end - 4], fill=k.get("gold", k["accent"]))
        self._ed_note(title=(int(P - 2), int(y), int(W - P), int(end + 2)))
        return end

    def _ed_paragraph(self, draw, text_lines: List[str], box, color: str, start: int, minimum: int = 26,
                      weight: str = "regular", measure: bool = False) -> int:
        x0, y0, x1, y1 = box
        size = start
        while True:
            font = korean_font(size, weight)
            lines: List[str] = []
            for t in text_lines:
                lines += wrap_text_balanced(t, font, x1 - x0)
            lh = int(text_height(font) * 1.48)
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

    def _ed_photo(self, img: Image.Image, photo: Image.Image, box, radius: int = 14, border_color: Optional[str] = None) -> None:
        x0, y0, x1, y1 = box
        self._ed_note(photo={"box": tuple(int(v) for v in box), "radius": radius})
        fitted = self._cover_fit(photo, max(1, x1 - x0), max(1, y1 - y0))
        mask = Image.new("L", fitted.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fitted.width - 1, fitted.height - 1], radius=radius, fill=255)
        img.paste(fitted, (x0, y0), mask)
        if border_color:
            ImageDraw.Draw(img).rounded_rectangle([x0, y0, x1 - 1, y1 - 1], radius=radius, outline=border_color, width=2)

    def _ed_banner(self, draw, ctx, k, box, style: str = "navy") -> None:
        """하단 요약 바(Stitch 스타일): 미드나잇 네이비(#111A2E) + 좌측 로열 골드 세로 바 + 골드 체크 배지."""
        text = (ctx.slide.takeaway or "").strip()
        mode = take_mode(ctx.slide)
        if not text or self.ED_SHORTS or mode == "none":      # 쇼츠: 요약은 내레이션·자막이 맡는다
            return
        if mode == "line":
            draw_take_line(self, draw, ctx, k, box)
            return
        x0, y0, x1, y1 = box
        fill = k["solid"]
        gold = k.get("gold", T.GOLD)
        draw.rounded_rectangle(box, radius=self._r(10), fill=fill, outline=gold if k["dark"] else None, width=1 if k["dark"] else 0)
        # 좌측 로열 골드 수직 포인트 바
        draw.rounded_rectangle([x0, y0, x0 + 10, y1], radius=self._r(4), fill=gold)
        draw.rectangle([x0 + 5, y0, x0 + 10, y1], fill=gold)

        cy = (y0 + y1) // 2
        badge = 42
        bx = x0 + 30
        draw.rounded_rectangle([bx, cy - badge // 2, bx + badge, cy + badge // 2], radius=self._r(8), fill=gold)
        _draw_check_mark(draw, bx + badge / 2, cy, 26, on_color(gold))

        tx = bx + badge + 22
        font, lines = self._fit_lines(text, x1 - tx - 26, int(36 * ctx.takeaway_scale), 28, 1, "bold")
        if lines and lines[-1].endswith("…"):
            font, lines = self._fit_lines(text, x1 - tx - 26, int(30 * ctx.takeaway_scale), 22, 2, "bold")
        lh = int(text_height(font) * 1.28)
        ty = cy - lh * len(lines) // 2
        for line in lines:
            draw.text((tx, ty), line, font=font, fill=T.IVORY)
            ty += lh

    @staticmethod
    def _ed_heart(draw, cx: float, cy: float, r: float, fill: str) -> None:
        """작은 하트(글꼴에 기대지 않고 도형으로)."""
        q = r * 0.55
        draw.ellipse([cx - r, cy - r * 0.75, cx - r + 2 * q * 0.95, cy - r * 0.75 + 2 * q * 0.95], fill=fill)
        draw.ellipse([cx + r - 2 * q * 0.95, cy - r * 0.75, cx + r, cy - r * 0.75 + 2 * q * 0.95], fill=fill)
        draw.polygon([(cx - r + 0.5, cy - r * 0.2), (cx + r - 0.5, cy - r * 0.2), (cx, cy + r * 0.95)], fill=fill)

    def _ed_footer(self, draw, ctx, k) -> None:
        if self.ED_SHORTS:                  # 쇼츠: 바닥글 없음(아래는 자막 자리)
            return
        W, H, P = self.WIDTH, self.HEIGHT - getattr(self, "safe_bottom", 0), self.ED_PAD
        y = H - 86
        draw.line([P, y, W - P, y], fill=k["line"], width=2)
        ends = ctx.index == 0 or ctx.index >= ctx.total - 1
        brand = ctx.kit.brand_name or ""
        mid_y = y + 43

        # 좌측: 로열 골드 엠블럼 + 브랜드명
        emblem_x = P + 8
        self._ed_heart(draw, emblem_x, mid_y, 9, k["accent"])
        text_x = P + 26

        right = ""
        has_phone = ends and ctx.el.show_phone and bool(ctx.kit.phone) and not getattr(ctx, "cta_hero", False)
        if has_phone:
            right = f"{T.COPY['phone_prefix']} {ctx.kit.phone}"
        elif not ends and not self.ED_SHORTS:
            right = T.COPY["next"]

        rw = 0
        if has_phone and right:
            rf = korean_font(24, "bold")
            rw = int(rf.getlength(right)) + 34
            bx0, by0, bx1, by1 = W - P - rw, mid_y - 22, W - P, mid_y + 22
            draw.rounded_rectangle([bx0, by0, bx1, by1], radius=self._r(6), fill=k["navy"], outline=k.get("gold", T.GOLD), width=1)
            draw.text(((bx0 + bx1) / 2, mid_y), right, font=rf, fill=T.IVORY, anchor="mm")
        elif right:
            rf = korean_font(22, "semibold")
            rw = int(rf.getlength(right))
            draw.text((W - P, mid_y), right, font=rf, fill=k["muted"], anchor="rm")

        if brand:
            max_lw = max(120, (W - P) - rw - 24 - text_x)
            lf = korean_font(24, "semibold")
            for sz in (24, 22, 20):
                cand = korean_font(sz, "semibold")
                lf = cand
                if cand.getlength(brand) <= max_lw:
                    break
            lbl = brand
            while lf.getlength(lbl) > max_lw and len(lbl) > 4:
                lbl = lbl[:-2] + "…"
            draw.text((text_x, mid_y), lbl, font=lf, fill=k["ink"] if k["dark"] else k["muted"], anchor="lm")

    def _ed_rows(self, img, draw, ctx, k, items: List[str], box, mode: str) -> None:
        """건축 정보 카드 목록(중복 번호 자동 제거 + head/desc 2단 구성). mode: check | number."""
        x0, y0, x1, y1 = box
        n = max(1, len(items))
        gap = 14 if self.ED_SHORTS else 18
        roomy = n <= 3                      # 항목이 적으면 칸과 글자를 키워 빈 곳을 채운다
        cap = (290 if self.ED_SHORTS else 236) if roomy else 178
        row_h = min(int(cap * self._ed_fs), ((y1 - y0) - gap * (n - 1)) // n)
        total = row_h * n + gap * (n - 1)
        y = y0 + max(0, ((y1 - y0) - total) // 2)
        badge_sz = min(78 if roomy else 62, max(44, row_h - 32))
        parts = [split_item_head_desc(it) for it in items]
        tw = (x1 - x0) - badge_sz - 84

        h_top = (58 if self.ED_SHORTS else 54) if roomy else 40
        h_size = min(h_top, max(24, int((h_top - 4 if roomy else 38) * ctx.body_scale * self._ed_fs)))
        while h_size > 24:
            hf = korean_font(h_size, "bold")
            df = korean_font(max(20, int(h_size * 0.76)), "regular")
            hl, dl = int(text_height(hf) * 1.25), int(text_height(df) * 1.32)
            ok = True
            for head, desc in parts:
                h_n = len(wrap_text_px(head, hf, tw))
                d_n = len(wrap_text_px(desc, df, tw)) if desc else 0
                need = h_n * hl + (6 + d_n * dl if desc else 0)
                if need > row_h - 22 or h_n > 2 or d_n > 2:
                    ok = False
                    break
            if ok:
                break
            h_size -= 2

        hf = korean_font(h_size, "bold")
        df = korean_font(max(20, int(h_size * 0.76)), "regular")
        hl, dl = int(text_height(hf) * 1.25), int(text_height(df) * 1.32)
        row_fill = k.get("row_panel", k["panel"])
        gold = k.get("gold", T.GOLD)

        for i, (head, desc) in enumerate(parts):
            self._ed_note(row=(int(x0), int(y), int(x1), int(y + row_h)))
            draw.rounded_rectangle([x0, y, x1, y + row_h], radius=self._r(10), fill=row_fill, outline=k["line"], width=2)
            stripe = gold if i == 0 else (k["accent"] if i % 2 == 1 else k["navy"])
            draw.rectangle([x0, y + 10, x0 + 6, y + row_h - 10], fill=stripe)

            bx, cy = x0 + 24, y + row_h // 2
            if mode == "check":
                chk_bg = k["accent"] if i == 0 else k["navy"]
                draw.rounded_rectangle([bx, cy - badge_sz // 2, bx + badge_sz, cy + badge_sz // 2], radius=self._r(8), fill=chk_bg)
                _draw_check_mark(draw, bx + badge_sz / 2, cy, badge_sz * 0.56, T.IVORY)
            else:
                num_bg = k["navy"] if not k["dark"] else (gold if i == 0 else k["soft"])
                num_ink = on_color(num_bg)
                draw.rounded_rectangle([bx, cy - badge_sz // 2, bx + badge_sz, cy + badge_sz // 2], radius=self._r(8), fill=num_bg)
                num = f"{i + 1:02d}"
                draw.text((bx + badge_sz / 2, cy), num, font=display_font(int(badge_sz * 0.44), num), fill=num_ink, anchor="mm")

            tx = bx + badge_sz + 22
            h_all = wrap_text_px(head, hf, tw)
            d_all = wrap_text_px(desc, df, tw) if desc else []
            h_lines, d_lines = h_all[:2], d_all[:2]
            self._clip(items[i], len(h_all) > 2 or len(d_all) > 2)
            block_h = len(h_lines) * hl + (6 + len(d_lines) * dl if d_lines else 0)
            ty = cy - block_h // 2
            for line in h_lines:
                draw.text((tx, ty), line, font=hf, fill=k["ink"])
                ty += hl
            if d_lines:
                ty += 4
                for line in d_lines:
                    draw.text((tx, ty), line, font=df, fill=k["muted"])
                    ty += dl
            y += row_h + gap

    def _draw_cta_extras(self, img, draw, ctx, k, box) -> Tuple[int, int, int, int]:
        """CTA 카드에서 할인·위치 배지(`promo_badge`)와 QR(`qr_image`)을 그리고 남은 목록 영역을 반환한다."""
        from cards.layout_onjaram import load_qr_image
        x0, y0, x1, y1 = box
        slide = ctx.slide
        if slide.slide_type != "call_to_action":
            return box
        gold = k.get("gold", T.GOLD)
        badge = (getattr(slide, "promo_badge", "") or "").strip()
        if badge and y1 - y0 > 260:
            bf = korean_font(26, "bold")
            btxt = badge.replace("\\n", " ").replace("\n", " ")
            bw = min(x1 - x0, int(bf.getlength(btxt)) + 44)
            bh = 50
            draw.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=self._r(8), fill=gold)
            draw.text((x0 + bw / 2, y0 + bh / 2), btxt, font=bf, fill=on_color(gold), anchor="mm")
            y0 += bh + 16
        qr = load_qr_image(getattr(slide, "qr_image", "") or "")
        if qr is not None and y1 - y0 > 320:
            qh = 156
            qy0 = y1 - qh
            side = qh - 24
            draw.rounded_rectangle([x0, qy0, x1, y1], radius=self._r(10), fill=k["panel"], outline=gold, width=2)
            img.paste(qr.resize((side, side), Image.NEAREST), (x0 + 18, qy0 + 12))
            cap = (getattr(slide, "qr_caption", "") or "").strip() or T.COPY["qr_caption"]
            tx = x0 + 18 + side + 24
            cf, clines = self._fit_lines(cap.replace("\\n", " ").replace("\n", " "), x1 - tx - 20, 30, 22, 2, "bold")
            clh = int(text_height(cf) * 1.3)
            cy = (qy0 + y1) // 2 - clh * len(clines) // 2
            for ln in clines:
                draw.text((tx, cy), ln, font=cf, fill=k["ink"])
                cy += clh
            y1 = qy0 - 16
        return (x0, y0, x1, y1)

    def _ed_info_rows(self, img, draw, ctx, k, box, legacy: bool = False) -> None:
        """'라벨 값' 줄(안내·문의): 건축 메타데이터 카드(좌측 골드/네이비 스트라이프 + 라벨 태그 + 볼드 값).
        카드(쇼츠 아님)는 내용 맞춤 표(`_ed_info_table`)로 그린다."""
        if not legacy and not self.ED_SHORTS:
            self._ed_info_table(img, draw, ctx, k, box)
            return
        x0, y0, x1, y1 = self._draw_cta_extras(img, draw, ctx, k, box)
        rows = parse_info_rows(ctx.slide.body_content, 7)
        if not rows:
            return
        n = len(rows)
        gap = 16
        roomy = n <= 3
        row_h = min(int((196 if roomy else 146) * self._ed_fs), ((y1 - y0) - gap * (n - 1)) // n)
        y = y0 + max(0, ((y1 - y0) - (row_h * n + gap * (n - 1))) // 2)
        gold = k.get("gold", T.GOLD)
        for idx, (label, value) in enumerate(rows):
            self._ed_note(row=(int(x0), int(y), int(x1), int(y + row_h)))
            draw.rounded_rectangle([x0, y, x1, y + row_h], radius=self._r(10), fill=k["panel"], outline=k["line"], width=2)
            draw.rectangle([x0, y + 10, x0 + 6, y + row_h - 10], fill=gold if idx == 0 else k["navy"])
            cy = y + row_h // 2
            vx = x0 + 28
            if label:
                lf = display_font(26, label)
                pw = int(lf.getlength(label)) + 34
                draw.rounded_rectangle([x0 + 24, cy - 22, x0 + 24 + pw, cy + 22], radius=self._r(6), fill=k["navy"])
                draw.text((x0 + 24 + pw / 2, cy), label, font=lf, fill=T.IVORY, anchor="mm")
                vx += pw + 22
            weight = "bold" if label else "semibold"
            font, lines = self._fit_lines(value, x1 - vx - 24, int((46 if roomy else 38) * ctx.body_scale * self._ed_fs), 28, 1, weight)
            if lines and lines[-1].endswith("…"):
                font, lines = self._fit_lines(value, x1 - vx - 24, min(34, max(22, (row_h - 24) // 3)), 22, 2, weight)
            lh = int(text_height(font) * 1.3)
            ly = cy - lh * (len(lines) - 1) / 2
            for line in lines:
                draw.text((vx, ly), line, font=font, fill=k["ink"] if label else k["text"], anchor="lm")
                ly += lh
            y += row_h + gap

    # --- 표지 전용 화면 ----------------------------------------------------------
    def _hero_cover(self, img, ctx, k, photo, top: int, pad: int, radius: int, chip: str = "", label: str = "", page_tag: bool = True) -> None:
        """표지 전용 화면: 사진을 화면 가득 깔고(없으면 네이비 바탕) 아래쪽 어두운 그라데이션 위에 큰 제목을 둔다.
        chip: 왼쪽 위 배지 문구(에디토리얼). label: 제목 바로 위 작은 골드 문구(리포트)."""
        from cards.card_renderer import luminance, mix
        W = self.WIDTH
        H = self.HEIGHT - getattr(self, "safe_bottom", 0)
        shorts = self.ED_SHORTS
        fs = max(1.0, min(1.22, (H - top) / 1350))
        navy = k.get("deep", T.NAVY_DEEP)
        g, a = k.get("gold", T.GOLD), k["accent"]          # 어두운 바탕 위 강조색: 두 포인트 색 중 더 밝은 쪽
        gold = mix(g if luminance(g) >= luminance(a) else a, T.WHITE, 0.22)
        gh = max(1, H - top)
        if photo is not None:
            self._ed_note(photo={"box": (0, int(top), W, int(H)), "radius": radius})
            img.paste(self._cover_fit(photo, W, gh), (0, top))
            ramp = Image.linear_gradient("L").resize((W, gh))            # 위 0 → 아래 255
            shade = ramp.point([0 if v < 64 else min(238, int((v - 64) * 1.62)) for v in range(256)])
            img.paste(Image.new("RGB", (W, gh), navy), (0, top), shade)
            top_h = min(220, gh)                                         # 배지가 읽히도록 위쪽도 살짝 어둡게
            scrim = Image.linear_gradient("L").resize((W, top_h)).point([int((255 - v) * 0.42) for v in range(256)])
            img.paste(Image.new("RGB", (W, top_h), navy), (0, top), scrim)
        else:
            ImageDraw.Draw(img).rectangle([0, top, W, H], fill=navy)
        draw = ImageDraw.Draw(img)
        P = pad
        line = mix(navy, T.WHITE, 0.32)

        # 아래에서부터 쌓는다: 바닥 줄(브랜드·전화) ← 요약 한 줄 ← 리드 ← 큰 제목
        y_end = H - 44
        if not shorts:
            fy = H - 62
            phone = f"{T.COPY['phone_prefix']} {ctx.kit.phone}" if (ctx.el.show_phone and ctx.kit.phone) else ""
            _draw_footer_row(draw, P, W, fy, ctx.kit.brand_name or "", phone, T.IVORY_DIM, gold,
                             left_weight="semibold", right_weight="bold", right_size=28)
            draw.line([P, fy - 44, W - P, fy - 44], fill=line, width=2)
            y_end = fy - 44 - 34

        take = (ctx.slide.takeaway or "").strip()
        tf, tlines, tlh = None, [], 0
        if take:
            tf, tlines = self._fit_lines(take, W - 2 * P - 30, int(36 * ctx.takeaway_scale * fs), 28, 2, "bold")
            tlh = int(text_height(tf) * 1.3)
        lead = " ".join(_lines(ctx.slide.body_content, 4))
        lf, llines, llh = None, [], 0
        if lead:
            lf = korean_font(int(34 * fs), "medium")
            l_all = wrap_text_balanced(lead, lf, W - 2 * P)
            llines = l_all[:3]
            self._clip(lead, len(l_all) > 3)
            llh = int(text_height(lf) * 1.46)
        below = (len(llines) * llh + 22 if llines else 0) + (len(tlines) * tlh + 30 if tlines else 0)

        head_room = top + (150 if chip else 60) + (60 if label else 0)
        max_h = max(160, min(int(gh * 0.44), y_end - below - head_room))
        size = word_fit_size(ctx.slide.lead_headline, int(T.TYPE["cover_title"] * fs * ctx.title_scale), W - 2 * P, 56)
        while True:
            end = self._emph_title(draw, ctx, 0, size, 56, 3, x=P, width=W - 2 * P, color=T.WHITE,
                                   emph_color=gold, measure=True, line_gap=1.2)
            if end <= max_h or size <= 56:
                break
            size -= 4
        y = max(head_room, y_end - below - end)

        if photo is None:                                                 # 사진 없는 표지: 위쪽 빈 곳에 골드 원 장식
            cx, cy = W - P - 150, top + max(190, (y - top) // 2)
            for r in (150, 112, 74):
                if cy - r > top + 20 and cy + r < y - 20:
                    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=mix(navy, gold, 0.55), width=2)

        if chip:
            cf = display_font(26, chip)
            cw, ch = int(cf.getlength(chip)) + 36, 50
            cy0 = top + 44
            fill = k["accent"]
            draw.rounded_rectangle([P, cy0, P + cw, cy0 + ch], radius=self._r(5), fill=fill)
            draw.text((P + cw / 2, cy0 + ch / 2), chip, font=cf, fill=on_color(fill), anchor="mm")
        if page_tag:                                                      # 쪽 번호(리포트는 위 띠에 이미 있어 끔)
            cy0, ch = top + 44, 50
            page = f"{ctx.index + 1:02d} / {ctx.total:02d}"
            pf = korean_font(24, "bold")
            pw = int(pf.getlength(page)) + 34
            draw.rounded_rectangle([W - P - pw, cy0 + 2, W - P, cy0 + ch - 2], radius=self._r(5), fill=navy, outline=line, width=1)
            draw.text((W - P - pw / 2, cy0 + ch / 2), page, font=pf, fill=T.IVORY, anchor="mm")
        if label:
            draw.text((P, y - 54), label, font=display_font(28, label), fill=gold)

        y = self._emph_title(draw, ctx, y, size, 56, 3, x=P, width=W - 2 * P, color=T.WHITE,
                             emph_color=gold, line_gap=1.2)
        if llines:
            y += 22
            for ln in llines:
                draw.text((P, y), ln, font=lf, fill=T.IVORY_TEXT)
                y += llh
        if tlines:
            y += 30
            draw.rectangle([P, y + 4, P + 7, y + len(tlines) * tlh - 6], fill=gold)
            for ln in tlines:
                draw.text((P + 30, y), ln, font=tf, fill=T.WHITE)
                y += tlh

    # --- 상담 안내 전용 화면 -------------------------------------------------------
    def _cta_hero(self, img, draw, ctx, k, box, radius: int = 12) -> bool:
        """상담 안내 카드: 안내 문장 → 큰 전화번호 칸(주소 포함) → 나머지 안내 줄.
        전화번호는 본문에 있으면 그 줄, 없으면 브랜드 킷 값. 둘 다 없으면 False(예전 줄 목록으로 그린다)."""
        rows = parse_info_rows(ctx.slide.body_content, 7)
        hit = next((i for i, (_, v) in enumerate(rows) if _PHONE_RE.search(v)), None)
        if hit is not None:
            phone = _PHONE_RE.search(rows[hit][1]).group(0)
            p_label = rows[hit][0]
        elif ctx.el.show_phone and ctx.kit.phone:
            phone, p_label = ctx.kit.phone, ""
        else:
            return False
        x0, y0, x1, y1 = self._draw_cta_extras(img, draw, ctx, k, box)
        fs = self._ed_fs
        leads = [v for i, (lab, v) in enumerate(rows) if not lab and i != hit]
        others = [(lab, v) for i, (lab, v) in enumerate(rows) if lab and i != hit]
        address = (ctx.kit.address or "").strip()
        if address and any(address[:8] in v for _, v in rows):
            address = ""
        gold = k.get("gold", T.GOLD)
        gap = 22

        card = not getattr(self, "ED_SHORTS", False)
        lead_font = korean_font(int((44 if card else 38) * ctx.body_scale * fs), "medium")
        lead_lh = int(text_height(lead_font) * 1.46)
        lead_blocks = [wrap_text_balanced(t, lead_font, x1 - x0)[:3] for t in leads[:2]]
        lead_h = sum(len(b) * lead_lh for b in lead_blocks) + (gap if lead_blocks else 0)
        other_h = min(int(104 * fs), 104)
        avail = (y1 - y0) - lead_h - len(others) * (other_h + 12)
        hero_h = max(170, min(int((540 if card else 440) * fs), avail))
        if hero_h > avail and others:                                     # 자리가 모자라면 아래 줄을 낮춘다
            other_h = max(64, ((y1 - y0) - lead_h - hero_h) // len(others) - 12)
        total = lead_h + hero_h + len(others) * (other_h + 12)
        y = y0 + max(0, ((y1 - y0) - total) // 2)

        for block in lead_blocks:
            self._ed_note(row=(int(x0), int(y), int(x1), int(y + len(block) * lead_lh)))
            for ln in block:
                draw.text((x0, y), ln, font=lead_font, fill=k["text"])
                y += lead_lh
        if lead_blocks:
            y += gap

        # 큰 전화번호 칸
        self._ed_note(row=(int(x0), int(y), int(x1), int(y + hero_h)))
        draw.rounded_rectangle([x0, y, x1, y + hero_h], radius=radius, fill=k["solid"],
                               outline=gold if k["dark"] else None, width=2 if k["dark"] else 0)
        draw.rectangle([x0, y + 22, x0 + 9, y + hero_h - 22], fill=gold)
        ix = x0 + 48
        iw = (x1 - 40) - ix
        tag = p_label if p_label and p_label not in ("문의",) else T.COPY["cta_tag"]
        tag_f = display_font(int(30 * fs), tag)
        addr_f, addr_lines = (None, [])
        if address and hero_h >= 230:
            addr_f, addr_lines = self._fit_lines(address, iw, int(30 * fs), 24, 2, "medium")
        email = (getattr(ctx.kit, "email", "") or "").strip()
        if card and email and hero_h >= 300 and not any(email in v for _, v in rows):
            ef, elines = self._fit_lines(email, iw, int(30 * fs), 24, 1, "medium")
            if addr_f is None:
                addr_f = ef
            addr_lines = addr_lines + elines
        addr_lh = int(text_height(addr_f) * 1.34) if addr_f else 0
        tag_h = int(text_height(tag_f) * 1.5)
        room = hero_h - 56 - tag_h - (len(addr_lines) * addr_lh + 18 if addr_lines else 0)
        size = int(T.TYPE["phone"] * fs)
        while size > 54 and (display_font(size, phone).getlength(phone) > iw or text_height(display_font(size, phone)) > room):
            size -= 4
        num_f = display_font(size, phone)
        num_h = int(text_height(num_f) * 1.12)
        block_h = tag_h + num_h + (len(addr_lines) * addr_lh + 18 if addr_lines else 0)
        ty = y + max(22, (hero_h - block_h) // 2)
        draw.text((ix, ty), tag, font=tag_f, fill=gold if k["dark"] else T.GOLD_LIGHT)
        ty += tag_h
        draw.text((ix, ty), phone, font=num_f, fill=T.IVORY)
        ty += num_h
        if addr_lines:
            ty += 18
            for ln in addr_lines:
                draw.text((ix, ty), ln, font=addr_f, fill=T.IVORY_DIM)
                ty += addr_lh
        y += hero_h

        for lab, value in others:
            y += 12
            self._ed_note(row=(int(x0), int(y), int(x1), int(y + other_h)))
            cy = y + other_h // 2
            lf2 = korean_font(28, "bold")
            draw.text((x0 + 8, cy), lab, font=lf2, fill=k["muted"], anchor="lm")
            vx = x0 + max(150, int(lf2.getlength(lab)) + 40)
            vf, vlines = self._fit_lines(value, x1 - vx, int(36 * ctx.body_scale * fs), 24, 1, "bold")
            draw.text((vx, cy), vlines[0] if vlines else "", font=vf, fill=k["ink"], anchor="lm")
            draw.line([x0, y + other_h, x1, y + other_h], fill=k["line"], width=2)
            y += other_h
        ctx.cta_hero = True                                               # 바닥글에 전화번호를 또 쓰지 않는다
        return True

    def _table_palette(self, ctx, k) -> dict:
        """비교표 색(밝은·어두운 바탕 공용)."""
        from cards.card_renderer import mix
        return {"head": k["solid"], "head_ink": T.IVORY, "row_a": k["bg"], "row_b": mix(k["bg"], k["ink"], 0.06),
                "line": k["line"], "ink": k["ink"], "text": k["text"], "accent": k.get("gold", k["accent"]) if k["dark"] else k["accent"]}

    # --- 내용 맞춤 배치(카드 전용 — 쇼츠 프레임은 예전 그대로) ----------------------------
    # 칸 크기를 미리 정하지 않고 내용(글·사진)의 양과 사진 모양에 맞춰 놓는다. 글은 영역에 들어가는 가장 큰 크기로,
    # 사진은 비율을 지켜(잘리지 않게) 놓고, 남는 높이는 위아래에 나눈다. 쇼츠 '글자 중심' 모양에서 옮긴 원칙.
    def _emph_style(self, ctx, k):
        """제목 강조어: 밝은 카드는 형광펜(글자색은 그대로), 어두운 바탕·쇼츠는 예전처럼 강조어 글자색."""
        from cards.card_renderer import tint
        if getattr(self, "ED_SHORTS", False) or k["dark"]:
            return k["accent"], None
        return None, tint(ctx.c.accent, 0.62)

    def _fit_badge(self, draw, x: int, y: int, letter: str, fill: str) -> None:
        r = QA_BADGE
        draw.ellipse([x, y, x + 2 * r, y + 2 * r], fill=fill)
        draw.text((x + r, y + r), letter, font=display_font(int(r * 1.1), letter), fill=on_color(fill), anchor="mm")

    def _fit_text_body(self, draw, ctx, k, body: List[str], box, para, fs: float) -> None:
        """사진 없는 글 카드: 상자 없이 짧은 포인트 선 + 큰 본문(영역에 맞는 가장 큰 크기), 위쪽에 조금 더 가깝게."""
        x0, y0, x1, y1 = box
        start = int(body_start_size(body) * 1.12 * ctx.body_scale * fs)
        rule, gap = 8, 34
        need = para(draw, body, (x0, y0 + rule + gap, x1, y1), k["text"], start, 26, measure=True)
        top = y0 + max(0, ((y1 - y0) - (rule + gap + need)) * 2 // 5)
        draw.rounded_rectangle([x0, top, x0 + 120, top + rule], radius=4, fill=k["accent"])
        para(draw, body, (x0, top + rule + gap, x1, y1), k["text"], start, 26)

    def _fit_qa(self, draw, ctx, k, body: List[str], box, para, fs: float) -> None:
        """묻고 답하기: (제목 앞 Q는 제목이 그림) 가는 선 아래 A 동그라미 + 큰 답."""
        x0, y0, x1, y1 = box
        r = QA_BADGE
        tx = x0 + 2 * r + 24
        start = int(body_start_size(body) * ctx.body_scale * fs)
        need = para(draw, body, (tx, y0 + 34, x1, y1), k["text"], start, 26, measure=True)
        top = y0 + max(0, ((y1 - y0) - (34 + max(need, 2 * r))) * 2 // 5)
        draw.line([x0, top, x1, top], fill=k["line"], width=2)
        a_fill = k.get("gold", k["accent"]) if k["dark"] else k.get("green", k.get("navy"))
        self._fit_badge(draw, x0, top + 34, "A", a_fill)
        para(draw, body, (tx, top + 34 + 4, x1, y1), k["text"], start, 26)

    def _fit_body_photo(self, img, draw, ctx, k, photo, body: List[str], box, para, photo_fn, radius: int, fs: float) -> None:
        """글 + 사진: 세로 사진은 본문 옆 세로 칸, 가로·정사각 사진은 본문 아래 폭 가득. 사진 비율을 지켜 잘리지 않게."""
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        ratio = photo.height / max(1, photo.width)
        start = int(body_start_size(body) * ctx.body_scale * fs) if body else 0
        if photo_shape(photo) == "portrait" and body:
            pw = int(bw * 0.42)
            ph = int(pw * ratio)
            if ph > bh:
                ph, pw = bh, int(bh / ratio)
            tx1 = x1 - pw - 40
            need = para(draw, body, (x0, y0, tx1, y1), k["text"], start, 26, measure=True)
            if need <= bh:                       # 옆 칸에 다 들어가면 나란히(안 들어가면 아래 '폭 가득'으로)
                row = max(ph, need)
                top = y0 + max(0, (bh - row) // 2)
                para(draw, body, (x0, top + max(0, (row - need) // 2), tx1, y1), k["text"], start, 26)
                py = top + max(0, (row - ph) // 2)
                photo_fn(img, photo, (x1 - pw, py, x1, py + ph), radius=radius)
                return
        gap = 30 if body else 0
        # 글은 영역의 42%까지 먼저 재고, 사진은 남는 높이를 모두 쓴다(비율 유지 — 넘치면 폭을 줄여 가운데)
        need = para(draw, body, (x0, y0, x1, y0 + int(bh * 0.42)), k["text"], start, 24, measure=True) if body else 0
        ph = int(bw * ratio)
        cap = bh - need - gap
        pw = bw
        if ph > cap:
            ph, pw = cap, int(cap / ratio)
        top = y0 + max(0, (bh - (need + gap + ph)) // 2)
        if body:
            para(draw, body, (x0, top, x1, top + need + 4), k["text"], start, 24)
        py, px = top + need + gap, x0 + (bw - pw) // 2
        photo_fn(img, photo, (px, py, px + pw, py + ph), radius=radius)

    def _fit_big_number(self, draw, ctx, k, body: List[str], box, rows_fn, fs: float, color: str) -> None:
        """큰 숫자 + 본문 항목: 왼쪽 위 큰 숫자·설명, 그 아래 항목 칸(본문이 화면에서 빠지지 않게)."""
        x0, y0, x1, y1 = box
        value = ctx.slide.stat_value
        size = int(220 * fs)
        while size > 80 and display_font(size, value).getlength(value) > (x1 - x0) * 0.9:
            size -= 6
        vf = display_font(size, value)
        vh = int(text_height(vf) * 1.08)
        self._ed_note(stat=(int(x0), int(y0), int(x1), int(y0 + vh)))
        draw.text((x0 - 4, y0), value, font=vf, fill=color)
        y = y0 + vh + 8
        if ctx.slide.stat_label:
            lf, lines = self._fit_lines(ctx.slide.stat_label, x1 - x0, int(42 * fs), 26, 2, "bold")
            for ln in lines:
                draw.text((x0, y), ln, font=lf, fill=k["text"])
                y += int(text_height(lf) * 1.3)
        rows_fn((x0, y + 30, x1, y1))

    def _ed_info_table(self, img, draw, ctx, k, box) -> None:
        """안내 카드(카드 전용): 라벨 없는 문장은 위 안내 글, 라벨 줄은 큰 라벨 칸 + 큰 값, 줄 사이 가는 선."""
        rows = parse_info_rows(ctx.slide.body_content, 7)
        leads = [v for lab, v in rows if not lab]
        items = [(lab, v) for lab, v in rows if lab]
        if not items:
            self._ed_info_rows(img, draw, ctx, k, box, legacy=True)
            return
        x0, y0, x1, y1 = self._draw_cta_extras(img, draw, ctx, k, box)
        fs = self._ed_fs
        lead_box_h = int((y1 - y0) * 0.3)
        lead_start = int(40 * ctx.body_scale * fs)
        lead_h = self._ed_paragraph(draw, leads, (x0, y0, x1, y0 + lead_box_h), k["text"], lead_start, 26, measure=True) if leads else 0
        gap = 40 if leads else 0
        n = len(items)
        row_h = max(70, min(int(172 * fs), ((y1 - y0) - lead_h - gap) // n))
        top = y0 + max(0, ((y1 - y0) - (lead_h + gap + row_h * n)) // 2)
        if leads:
            self._ed_paragraph(draw, leads, (x0, top, x1, top + lead_h + 4), k["text"], lead_start, 26)
        y = top + lead_h + gap
        lab_f = display_font(int(32 * fs), "".join(lab for lab, _ in items))
        lab_w = int(max(lab_f.getlength(lab) for lab, _ in items)) + 48
        pill = k.get("green", k["navy"])
        for i, (lab, value) in enumerate(items):
            self._ed_note(row=(int(x0), int(y), int(x1), int(y + row_h)))
            cy = y + row_h // 2
            half = min(42, (row_h - 20) // 2)
            draw.rounded_rectangle([x0, cy - half, x0 + lab_w, cy + half], radius=self._r(10), fill=pill)
            draw.text((x0 + lab_w / 2, cy), lab, font=lab_f, fill=on_color(pill), anchor="mm")
            vx = x0 + lab_w + 30
            font, lines = self._fit_lines(value, x1 - vx, int(52 * ctx.body_scale * fs), 26, 2, "bold")
            lh = int(text_height(font) * 1.3)
            ly = cy - lh * (len(lines) - 1) / 2
            for ln in lines:
                draw.text((vx, ly), ln, font=font, fill=k["ink"], anchor="lm")
                ly += lh
            if i < n - 1:
                draw.line([x0, y + row_h, x1, y + row_h], fill=k["line"], width=2)
            y += row_h

    # --- 쇼츠가 쓰는 칸 위치 -----------------------------------------------------
    def _ed_note(self, photo=None, row=None, title=None, stat=None) -> None:
        reg = getattr(self, "ed_regions", None)
        if reg is None:
            return
        if title is not None:
            reg["title"] = title
        if stat is not None:
            reg["stat"] = stat
        if photo is not None:
            reg["photo"] = photo
        if row is not None:
            reg["rows"].append(row)

    # --- 본체 ----------------------------------------------------------------
    def _layout_ed(self, ctx, photo: Optional[Image.Image]) -> Image.Image:
        from cards.card_renderer import normalize_table

        W, H, P = self.WIDTH, self.HEIGHT, self.ED_PAD
        Hc = H - getattr(self, "safe_top", 0) - getattr(self, "safe_bottom", 0)
        self._ed_fs = max(1.0, min(1.22, Hc / 1350))
        self._ed_round = 2.0 if (getattr(ctx.design, "radius", 0) or 0) >= 24 else 1.0
        k = self._ed_colors(ctx)
        self.ed_regions = {
            "photo": None, "rows": [], "title": None, "stat": None, "bg": k["bg"], "ink": k["ink"], "solid": k["solid"],
            "accent": k["accent"], "gold": k.get("gold", T.GOLD), "dark": k["dark"],
            "pad": self.ED_PAD, "cap_radius": self._r(18),
        }
        img = Image.new("RGB", (W, H), k["bg"])
        draw = ImageDraw.Draw(img)
        t = ctx.slide.slide_type
        shorts = self.ED_SHORTS
        if t == "cover" and (not shorts or photo is None):
            # 표지 전용 화면: 사진을 가득 깔고 큰 제목(쇼츠는 사진이 없을 때만 — 사진이 있으면 사진 칸을 따로 움직인다)
            top = getattr(self, "safe_top", 0)
            draw.rectangle([0, top, W, top + 8], fill=k.get("gold", k["accent"]))
            series = (getattr(ctx.el, "series_label", "") or "").strip()
            self._hero_cover(img, ctx, k, photo, top + 8, P, 0, chip=series or KICKERS.get("cover", ""))
            return img
        y = self._ed_header(draw, ctx, k)
        # 쇼츠는 요약 띠·바닥글을 그리지 않고(자막이 그 자리를 맡는다) 내용 칸을 자막 바로 위까지 쓴다
        foot_top = H - getattr(self, "safe_bottom", 0) - (20 if shorts else 86 + 24)
        mode = "none" if shorts else take_mode(ctx.slide)
        has_take = mode != "none"
        docked = mode == "bar"              # 진한 띠만 사진 아래에 맞닿게 붙인다
        banner_h = {"bar": 118, "line": 92}.get(mode, 0)
        banner_top = foot_top - banner_h
        content_bottom = banner_top - (26 if has_take else 0)

        # --- 1) 쇼츠 표지(사진 있음): 머리줄 바로 아래 큰 사진·영상 칸 → 그 아래 큰 제목·리드
        if t == "cover":
            body = _lines(ctx.slide.body_content, 4)
            ph = int(Hc * 0.50)
            self._ed_photo(img, photo, (P, y + 4, W - P, y + 4 + ph), radius=self._r(14), border_color=k.get("gold", k["line"]))
            y = y + 4 + ph + 32
            y = self._ed_title(draw, ctx, k, y, int(T.TYPE["shorts_cover_title"] * self._ed_fs), int((content_bottom - y) * 0.62)) + 20
            if body and content_bottom - y > 56:
                self._ed_paragraph(draw, [" ".join(body)], (P + 18, y, W - P, content_bottom),
                                   k["text"], int(40 * self._ed_fs), 26, weight="medium")
            return img

        # --- 2) 본문 / 목록 / 지표 / 비교표 / CTA 등 일반 슬라이드
        # '큰 사진' 변형: 글·사진 카드는 머리줄 바로 아래에 사진을 화면 폭 가득 먼저 놓고 그 아래에 제목·글
        big_photo = (ctx.design.variant == "photo" and photo is not None and not shorts
                     and t not in LIST_TYPES + ("call_to_action", "event_info", "big_number", "comparison_table"))
        if big_photo:
            ph = int((foot_top - y) * 0.50)
            self._ed_photo(img, photo, (0, y - 10, W, y - 10 + ph), radius=self._r(0))
            y = y - 10 + ph + 30
        title_max_h = int(190 * self._ed_fs) if (shorts and t in LIST_TYPES and photo is not None) else int((280 if shorts else 230) * self._ed_fs)
        title_start = int(T.TYPE["title_shorts" if shorts else "title"] * self._ed_fs)
        text_card = not shorts and photo is None and not big_photo and t in TEXT_CARD_TYPES + ("qa",)
        if text_card:                       # 사진 없는 글 카드: 제목을 더 크게(내용 맞춤 배치)
            title_start, title_max_h = int(title_start * 1.12), int(title_max_h * 1.3)
        badge = "Q" if (t == "qa" and not shorts and not big_photo) else ""
        y = self._ed_title(draw, ctx, k, y, title_start, title_max_h, badge=badge) + (30 if badge else 22)
        box = (P, y, W - P, content_bottom)
        body = _lines(ctx.slide.body_content, 6)

        if box[3] - box[1] < 80:
            pass
        elif t in LIST_TYPES and body:
            if self.ED_SHORTS and photo is not None and (box[3] - box[1]) > 540:
                # 쇼츠에서 동영상이 연결된 체크리스트/단계 카드: 상단 영상 투어 뷰포트 + 하단 순차 등장 목록
                ph = min(380, int((box[3] - box[1]) * 0.42))
                self._ed_photo(img, photo, (P, box[1], W - P, box[1] + ph), radius=self._r(12), border_color=k.get("gold", k["line"]))
                row_box = (P, box[1] + ph + 20, W - P, box[3])
            else:
                row_box = box
            self._ed_rows(img, draw, ctx, k, body, row_box, "check" if t == "checklist" else "number")
        elif t == "call_to_action":
            if not self._cta_hero(img, draw, ctx, k, box, radius=self._r(12)):
                self._ed_info_rows(img, draw, ctx, k, box)
        elif t == "event_info":
            self._ed_info_rows(img, draw, ctx, k, box)
        elif t == "big_number" and ctx.slide.stat_value and body and not shorts:
            self._fit_big_number(draw, ctx, k, body, box, lambda b: self._ed_rows(img, draw, ctx, k, body, b, "number"),
                                 self._ed_fs, k["accent"])
        elif t == "big_number" and ctx.slide.stat_value:
            draw.rounded_rectangle(box, radius=self._r(14), fill=k["panel"], outline=k["line"], width=2)
            draw.rectangle([box[0], box[1] + 24, box[0] + 8, box[3] - 24], fill=k.get("gold", k["accent"]))
            self._ed_note(stat=tuple(int(v) for v in box))
            value = ctx.slide.stat_value
            size = 186
            while display_font(size, value).getlength(value) > (W - 2 * P) - 100 and size > 60:
                size -= 6
            cy = (box[1] + box[3]) // 2 - 28
            draw.text((W / 2, cy), value, font=display_font(size, value), fill=k["accent"], anchor="mm")
            if ctx.slide.stat_label:
                lf, lines = self._fit_lines(ctx.slide.stat_label, W - 2 * P - 100, 38, 24, 2, "semibold")
                ly = cy + size // 2 + 16
                for line in lines:
                    draw.text((W / 2, ly), line, font=lf, fill=k["text"], anchor="ma")
                    ly += int(text_height(lf) * 1.3)
        elif t == "comparison_table" and all(normalize_table(ctx.slide.comparison_table)):
            header, rows = normalize_table(ctx.slide.comparison_table)
            draw.rounded_rectangle(box, radius=self._r(14), fill=k["panel"], outline=k["line"], width=2)
            self._draw_table(draw, header, rows, (box[0] + 20, box[1] + 20, box[2] - 20, box[3] - 20), ctx,
                             start=46, stretch=True, pal=self._table_palette(ctx, k))
        elif big_photo:
            if body and box[3] - box[1] > 60:
                self._ed_paragraph(draw, body, box, k["text"], int(body_start_size(body) * 0.86 * ctx.body_scale * self._ed_fs), 26)
        elif photo is not None and not shorts:
            self._fit_body_photo(img, draw, ctx, k, photo, body, box, self._ed_paragraph,
                                 lambda im, ph, b, radius: self._ed_photo(im, ph, b, radius=radius), self._r(14), self._ed_fs)
        elif photo is not None:
            # Stitch 본문+사진 계층: 상단 리드 본문 → 하단 대형 건축 프레임 사진 (+ 도킹 네이비 캡션)
            p_limit_bottom = foot_top if docked else content_bottom
            text_area_max = min(int((p_limit_bottom - box[1]) * 0.42), 260)
            para_y = box[1]
            if body:
                para_h = self._ed_paragraph(draw, body, (P, box[1], W - P, box[1] + text_area_max),
                                            k["text"], int(34 * ctx.body_scale * self._ed_fs), 24, measure=True)
                self._ed_paragraph(draw, body, (P, box[1], W - P, box[1] + text_area_max),
                                   k["text"], int(34 * ctx.body_scale * self._ed_fs), 24)
                para_y = box[1] + min(text_area_max, para_h) + 24

            if docked:
                p_bot = max(para_y + 180, foot_top)
                self._ed_photo(img, photo, (P, para_y, W - P, p_bot), radius=self._r(14), border_color=k["line"])
                self._ed_banner(draw, ctx, k, (P, foot_top - 116, W - P, foot_top), "navy")
                self._ed_footer(draw, ctx, k)
                return img
            else:
                p_bot = max(para_y + 180, content_bottom)
                self._ed_photo(img, photo, (P, para_y, W - P, p_bot), radius=self._r(14), border_color=k.get("gold", k["line"]))
        elif body and t == "qa" and not shorts:
            self._fit_qa(draw, ctx, k, body, box, self._ed_paragraph, self._ed_fs)
        elif body and not shorts:
            self._fit_text_body(draw, ctx, k, body, box, self._ed_paragraph, self._ed_fs)
        elif body and box[3] - box[1] >= 140:
            # 글 카드: 건축 인용·브리핑 패널 + 좌측 골드/버건디 세로 바
            draw.rounded_rectangle(box, radius=self._r(14), fill=k["panel"], outline=k["line"], width=2)
            draw.rectangle([box[0], box[1] + 24, box[0] + 8, box[3] - 24], fill=k.get("gold", k["accent"]))
            inner = (P + 46, box[1] + 40, W - P - 40, box[3] - 36)
            start = int(body_start_size(body) * ctx.body_scale)
            need = self._ed_paragraph(draw, body, inner, k["text"], start, 26, measure=True)
            top = inner[1] + max(0, (inner[3] - inner[1] - need) // 2)
            self._ed_paragraph(draw, body, (inner[0], top, inner[2], inner[3]), k["text"], start, 26)

        self._ed_banner(draw, ctx, k, (P, banner_top, W - P, foot_top), "navy")
        self._ed_footer(draw, ctx, k)
        return img
