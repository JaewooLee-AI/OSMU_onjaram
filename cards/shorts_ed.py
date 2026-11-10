"""에디토리얼 쇼츠 장면 — 카드를 늘린 정지 화면이 아니라 쇼츠용으로 층을 나눠 합성합니다.

한 장면 = 바탕(카드를 9:16으로 그린 것, 목록 칸은 비움)
        + 사진 칸 미디어(SceneMedia: 이미지 한 장 · 이미지 두 장 · 영상 클립 — 사진 칸 안에서만 움직임)
        + 목록 칸(음성에 맞춰 하나씩 나타남)
        + 큰 자막(지금 읽는 문장, 아래 UI 가림 영역 바로 위 띠)

사진 칸 미디어를 한 가지로 박지 않은 것은 앞으로의 고도화(이미지 두 장을 이어 움직이기, 사용자가 올린 동영상을
사진 칸에 잘라 쓰기)를 같은 자리에 끼우기 위해서입니다. 지금은 카드의 사진(이미지) 또는 카드에 넣은 동영상 에셋을
쓰고, `ShortsOptions.media_overrides`로 장면마다 다른 미디어를 줄 수 있습니다.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from cards.fonts import display_font, text_height, wrap_text_px

MEDIA_KINDS = ("image", "image_pair", "video")
CAPTION_H = 250          # 큰 자막 띠 높이(아래 UI 가림 영역 바로 위)
CAPTION_SIZE = 50
CAPTION_MIN = 38
ROW_FADE = 0.35          # 목록 칸이 나타나는 시간(초)
ROW_RISE = 26            # 나타날 때 아래에서 올라오는 거리(px)
CAP_FADE = 0.15
PAIR_FADE = 0.6          # 이미지 두 장 사이 전환(초)


@dataclass
class SceneMedia:
    """사진 칸에 들어갈 미디어. kind: image(한 장) | image_pair(두 장을 이어서) | video(영상 클립, clip_start부터)."""
    kind: str
    paths: List[str] = field(default_factory=list)
    clip_start: float = 0.0

    def usable(self) -> bool:
        need = 2 if self.kind == "image_pair" else 1
        return self.kind in MEDIA_KINDS and len(self.paths) >= need and all(os.path.exists(p) for p in self.paths[:need])

    @property
    def moves_by_itself(self) -> bool:
        """사진 움직임 옵션이 '정지'여도 움직이는 미디어(영상·두 장 전환)."""
        return self.kind in ("video", "image_pair")


def media_for(storyboard, scene, slide, overrides: Optional[Dict[int, SceneMedia]] = None, index: int = 0) -> Optional[SceneMedia]:
    """장면의 사진 칸 미디어. 우선순위: 직접 지정(overrides) → 장면 에셋 → 카드 에셋. 동영상 에셋이면 영상 클립."""
    if overrides and index in overrides and overrides[index].usable():
        return overrides[index]
    for aid, start in ((getattr(scene, "asset_id", None), getattr(scene, "clip_start", 0.0)), (getattr(slide, "asset_id", None), 0.0)):
        asset = storyboard.asset(aid) if aid else None
        if asset is None or not asset.path:
            continue
        m = SceneMedia("video", [asset.path], float(start or 0.0)) if asset.kind == "video" else SceneMedia("image", [asset.path])
        if m.usable():
            return m
    return None


# --- 자막 ------------------------------------------------------------------
def caption_chunks(text: str, width: int, size: int = CAPTION_SIZE, max_lines: int = 2) -> List[str]:
    """내레이션을 화면에 한 번에 보일 덩어리로 나눈다(문장 단위, 길면 낱말 단위로 max_lines줄 안에)."""
    font = display_font(size, text or "가")
    out: List[str] = []
    for sent in re.split(r"(?<=[.!?。…])\s+", (text or "").strip()):
        sent = sent.strip()
        if not sent:
            continue
        if len(wrap_text_px(sent, font, width)) <= max_lines:
            out.append(sent)
            continue
        cur = ""
        for word in sent.split():
            trial = f"{cur} {word}".strip()
            if cur and len(wrap_text_px(trial, font, width)) > max_lines:
                out.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            out.append(cur)
    return out


def spread_times(weights: List[float], start: float, length: float) -> List[Tuple[float, float]]:
    """start부터 length초를 무게(글자 수)에 비례해 나눈 (시작, 끝) 목록."""
    total = sum(max(1.0, w) for w in weights) or 1.0
    out, t = [], start
    for w in weights:
        d = length * max(1.0, w) / total
        out.append((t, t + d))
        t += d
    return out


def caption_times(chunks: List[str], start: float, speech: float, seg_end: float) -> List[Tuple[float, float]]:
    """자막 덩어리마다 보일 구간. 글자 수에 비례(음성 단어 시각이 없어서), 마지막 덩어리는 장면 끝까지."""
    times = spread_times([len(c.replace(" ", "")) for c in chunks], start, speech)
    if times:
        times[-1] = (times[-1][0], seg_end)
    return times


def row_times(n: int, start: float, speech: float, already_shown: bool = False) -> List[float]:
    """목록 칸 n개가 나타날 시각. 음성 구간의 85% 안에 고르게(첫 칸은 조금 뒤). 이미 앞 장면에서 보인 카드면 처음부터."""
    if already_shown or n <= 0:
        return [0.0] * max(0, n)
    lead = min(0.4, speech * 0.1)
    step = max(0.0, speech * 0.85 - lead) / n
    return [start + lead + i * step for i in range(n)]


def row_times_from_text(narration: str, items: List[str], start: float, speech: float, already_shown: bool = False) -> List[float]:
    """목록 칸이 나타날 시각을 내레이션에서 그 항목을 읽기 시작하는 곳에 맞춘다(글자 위치 비례).
    항목을 찾지 못하면 고르게 나눈 시각(row_times)을 쓴다."""
    even = row_times(len(items), start, speech, already_shown)
    if already_shown or not items:
        return even
    text = narration or ""
    pos, out = 0, []
    for item, fallback in zip(items, even):
        key = re.sub(r"\s+", " ", item).strip()[:6]
        at = text.find(key, pos) if key else -1
        if at < 0:
            return even
        out.append(start + speech * at / max(1, len(text)) - 0.15)   # 읽기 직전에 나타나게
        pos = at + len(key)
    return [max(start, t) for t in out]


def caption_png(text: str, path: str, width: int, colors: dict, pad: int = 0) -> str:
    """자막 띠 한 장(투명 바탕 + 둥근 색 칸 + 흰 글자). 크기는 width x CAPTION_H."""
    pad = pad or int(colors.get("pad") or 72)   # 카드 디자인의 좌우 여백과 맞춤
    img = Image.new("RGBA", (width, CAPTION_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    inner = width - 2 * pad - 64
    size = CAPTION_SIZE
    while True:
        font = display_font(size, text)
        lines = wrap_text_px(text, font, inner)
        lh = int(text_height(font) * 1.32)
        if (len(lines) <= 2 and lh * len(lines) + 56 <= CAPTION_H - 20) or size <= CAPTION_MIN:
            break
        size -= 2
    lines = lines[:2]
    box_h = lh * len(lines) + 56
    y0 = (CAPTION_H - box_h) // 2
    d.rounded_rectangle([pad, y0, width - pad, y0 + box_h], radius=int(colors.get("cap_radius") or 28), fill=colors.get("solid") or "#35593F")
    ty = y0 + 28
    for line in lines:
        d.text((width // 2, ty + lh // 2), line, font=font, fill="#FFFFFF", anchor="mm")
        ty += lh
    img.save(path)
    return path


# --- 바탕·층 ----------------------------------------------------------------
def split_layers(frame_path: str, regions: dict, work_dir: str, tag: str):
    """카드 그림에서 목록 칸을 떼어 낸다. 반환: (목록 칸을 바탕색으로 비운 바탕 PNG, [(칸 PNG, x, y)])."""
    im = Image.open(frame_path).convert("RGB")
    base = im.copy()
    d = ImageDraw.Draw(base)
    rows = []
    for i, (x0, y0, x1, y1) in enumerate(regions.get("rows") or []):
        crop = im.crop((x0 - 2, y0 - 2, x1 + 3, y1 + 3))
        p = os.path.join(work_dir, f"row_{tag}_{i}.png")
        crop.save(p)
        rows.append((p, x0 - 2, y0 - 2))
        d.rectangle([x0 - 2, y0 - 2, x1 + 3, y1 + 3], fill=regions.get("bg") or "#FAF8F5")
    bp = os.path.join(work_dir, f"edbase_{tag}.png")
    base.save(bp)
    return bp, rows


def mask_png(path: str, w: int, h: int, radius: int) -> str:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    m.save(path)
    return path


def media_inputs(media: SceneMedia, fps: int) -> List[List[str]]:
    """미디어의 ffmpeg 입력 인자(입력마다 한 묶음)."""
    if media.kind == "video":
        return [["-ss", f"{max(0.0, media.clip_start):.3f}", "-i", media.paths[0]]]
    n = 2 if media.kind == "image_pair" else 1
    return [["-loop", "1", "-framerate", str(fps), "-i", p] for p in media.paths[:n]]


def media_chain(media: SceneMedia, first: int, w: int, h: int, frames: int, fps: int, motion) -> Tuple[List[str], str]:
    """사진 칸(w x h)을 채우는 영상 흐름을 만드는 필터. motion은 (zoom, x, y) zoompan 식 또는 None(정지).
    반환: (필터 조각들, 출력 이름)."""
    cover = f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2}"
    if media.kind == "video":
        return ([f"[{first}:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
                 f"tpad=stop_mode=clone:stop={frames},trim=end_frame={frames},setpts=PTS-STARTPTS[med]"], "med")

    def still(i: int, n: int, mv, label: str) -> str:
        if mv is None:
            return f"[{i}:v]{cover},scale={w}:{h},setsar=1,trim=end_frame={n},setpts=PTS-STARTPTS[{label}]"
        z, x, y = mv
        return f"[{i}:v]{cover},zoompan=z='{z}':x='{x}':y='{y}':d=1:s={w}x{h}:fps={fps},setsar=1,trim=end_frame={n},setpts=PTS-STARTPTS[{label}]"

    if media.kind == "image_pair":
        fade_f = max(2, int(PAIR_FADE * fps))
        half = (frames + fade_f) // 2
        mv = motion if motion is not None else None
        chains = [still(first, half, mv, "pa"), still(first + 1, frames - half + fade_f, mv, "pb"),
                  f"[pa][pb]xfade=transition=fade:duration={fade_f / fps:.3f}:offset={(half - fade_f) / fps:.3f},"
                  f"trim=end_frame={frames}[med]"]
        return chains, "med"
    return [still(first, frames, motion, "med")], "med"
