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
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from cards import ffmpeg_tools
from cards import tokens as T
from cards.fonts import display_font, text_height, wrap_text_px

MEDIA_KINDS = ("image", "image_pair", "video")
CAPTION_H = T.SPACE["caption_h"]          # 큰 자막 띠 높이(아래 UI 가림 영역 바로 위)
CAPTION_SIZE = 50
CAPTION_MIN = T.TYPE["caption_min"]
ROW_FADE = 0.35          # 목록 칸이 나타나는 시간(초)
ROW_RISE = 26            # 나타날 때 아래에서 올라오는 거리(px)
CAP_FADE = 0.15
PAIR_FADE = 0.6          # 이미지 두 장 사이 전환(초)
TITLE_FADE = 0.35        # 제목이 나타나는 시간(초)
TITLE_DROP = 22          # 제목이 위에서 내려오는 거리(px)
COUNT_STEPS = 8          # 큰 숫자가 올라가는 단계 수
COUNT_SEC = 0.9          # 큰 숫자가 올라가는 시간(초)
PAUSE_MIN = 0.16         # 이보다 긴 무음을 '쉬는 곳'으로 본다(초)
PAUSE_NOISE_DB = -38     # 이보다 조용하면 무음
PAUSE_SNAP = 0.9         # 자막 경계를 쉬는 곳으로 옮기는 최대 거리(초)
PROGRESS_H = 8           # 진행 막대 두께(px) — 자막 띠 바로 아래


@dataclass
class SceneMedia:
    """사진 칸에 들어갈 미디어. kind: image(한 장) | image_pair(두 장을 이어서) | video(영상 클립, clip_start부터)."""
    kind: str
    paths: List[str] = field(default_factory=list)
    clip_start: float = 0.0
    speed: float = 1.0           # 재생 속도(1=보통, 0.5=절반 속도로 느리게, 2=두 배 빠르게)

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


def detect_pauses(audio_path: str, min_len: float = PAUSE_MIN, noise_db: int = PAUSE_NOISE_DB) -> List[float]:
    """음성 파일에서 말이 쉬는 곳(무음 구간의 가운데 시각, 초)을 찾는다. 맨 앞·맨 뒤 무음은 뺀다.
    FFmpeg의 silencedetect를 쓰므로 추가 설치가 없다. 찾지 못하거나 실패하면 빈 목록(→ 글자 수 비례로 나눔)."""
    if not audio_path or not os.path.exists(audio_path):
        return []
    try:
        proc = subprocess.run(
            [ffmpeg_tools.ffmpeg(), "-hide_banner", "-nostats", "-i", audio_path,
             "-af", f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, **ffmpeg_tools.no_window())
    except (OSError, subprocess.SubprocessError):
        return []
    log = proc.stderr or ""
    starts = [float(v) for v in re.findall(r"silence_start:\s*(-?[\d.]+)", log)]
    ends = [float(v) for v in re.findall(r"silence_end:\s*(-?[\d.]+)", log)]
    total = ffmpeg_tools.probe_duration(audio_path) or 0.0
    out = []
    for a, b in zip(starts, ends):
        if a <= 0.12 or (total and b >= total - 0.12):     # 맨 앞·맨 뒤 무음(또는 통째로 무음)은 쉬는 곳이 아니다
            continue
        out.append(round((a + b) / 2, 3))
    return out


def snap_to_pauses(cuts: List[float], pauses: List[float], tolerance: float = PAUSE_SNAP, min_gap: float = 0.45) -> List[float]:
    """나누는 시각들을 가장 가까운 '쉬는 곳'으로 옮긴다(tolerance초 안에 있을 때만, 순서는 유지, 한 곳은 한 번만)."""
    out, used, prev = [], set(), None
    for cut in cuts:
        cands = [p for p in pauses if p not in used and abs(p - cut) <= tolerance and (prev is None or p >= prev + min_gap)]
        if cands:
            cut = min(cands, key=lambda p: abs(p - cut))
            used.add(cut)
        elif prev is not None and cut < prev + min_gap:
            cut = prev + min_gap
        out.append(cut)
        prev = cut
    return out


def caption_times(chunks: List[str], start: float, speech: float, seg_end: float,
                  pauses: Optional[List[float]] = None) -> List[Tuple[float, float]]:
    """자막 덩어리마다 보일 구간. 기본은 글자 수 비례이고, 음성에서 찾은 쉬는 곳(pauses: 장면 음성 기준 초)이 있으면
    덩어리 사이 경계를 가까운 쉬는 곳으로 옮겨 실제 말과 맞춘다. 마지막 덩어리는 장면 끝까지."""
    times = spread_times([len(c.replace(" ", "")) for c in chunks], start, speech)
    if pauses and len(times) > 1:
        cuts = snap_to_pauses([b for _, b in times[:-1]], [start + p for p in pauses])
        edges = [times[0][0]] + cuts + [times[-1][1]]
        times = [(edges[i], edges[i + 1]) for i in range(len(times))]
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


def snap_rows(times: List[float], pauses: Optional[List[float]], start: float) -> List[float]:
    """목록 칸이 나타날 시각을 가까운 쉬는 곳으로 옮긴다(항목을 읽기 직전의 쉼에 맞춤). 쉬는 곳이 없으면 그대로."""
    if not pauses or not times or not any(times):
        return times
    return [max(start, t) for t in snap_to_pauses(times, [start + p for p in pauses], tolerance=0.7, min_gap=0.3)]


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


def assign_video_relay(storyboard, overwrite: bool = False) -> int:
    """업로드된 동영상 에셋을 쇼츠 전 장면(또는 비어 있는 장면)에 순서대로 이어붙인다.

    한 동영상(예: 25초 단지 투어)을 장면 1(0초~) → 장면 2(4초~) → 장면 3(8초~)… 처럼
    누적 길이(duration_seconds)를 따라 `clip_start`를 자동 배분한다.
    """
    videos = [a for a in getattr(storyboard, "assets", []) if a.kind == "video" and a.path and os.path.exists(a.path)]
    if not videos:
        return 0
    for vid in videos:
        if vid.duration <= 0:
            vid.duration = ffmpeg_tools.probe_duration(vid.path)

    assigned = 0
    cursor = 0.0
    for i, scene in enumerate(getattr(storyboard, "shorts_scenes", []) or []):
        dur = max(1.0, float(getattr(scene, "duration_seconds", 4.0) or 4.0))
        cur_asset = storyboard.asset(scene.asset_id) if getattr(scene, "asset_id", None) else None
        if overwrite or cur_asset is None:
            vid = videos[min(i * len(videos) // max(1, len(storyboard.shorts_scenes)), len(videos) - 1)] if len(videos) > 1 else videos[0]
            scene.asset_id = vid.id
            if vid.duration > dur + 0.5:
                max_off = max(0.5, vid.duration - dur)
                scene.clip_start = round(cursor % max_off, 2)
            else:
                scene.clip_start = 0.0
            assigned += 1
        cursor += dur
    return assigned


def _rgba(hex_color: str, alpha: int = 242) -> Tuple[int, int, int, int]:
    h = (hex_color or T.NAVY).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)
    except ValueError:
        return (17, 26, 46, alpha)


def caption_png(text: str, path: str, width: int, colors: dict, pad: int = 0) -> str:
    """큰 자막 한 덩어리(네이비 띠 + 위 골드 선 + 지금 읽는 문장 최대 2줄). 크기: width x CAPTION_H.
    작은 머리 문구·전화번호는 넣지 않는다 — 휴대폰에서 읽히지 않고, 연락처는 마지막 상담 안내 장면이 크게 보여 준다."""
    pad = pad or int(colors.get("pad") or 72)
    img = Image.new("RGBA", (width, CAPTION_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    gold = colors.get("gold") or T.GOLD
    bg_hex = colors.get("solid") or T.NAVY
    radius = int(colors.get("cap_radius") or 18)

    y0, y1 = 10, CAPTION_H - 10
    d.rounded_rectangle([pad, y0, width - pad, y1], radius=radius, fill=_rgba(bg_hex, 246), outline=_rgba(gold, 210), width=2)
    d.rounded_rectangle([pad + 2, y0 + 2, width - pad - 2, y0 + 14], radius=min(6, radius), fill=gold)
    d.rectangle([pad + 2, y0 + 8, width - pad - 2, y0 + 14], fill=gold)

    inner = width - 2 * pad - 64
    top, bottom = y0 + 28, y1 - 14
    size = T.TYPE["caption"]
    while True:
        font = display_font(size, text or "가")
        lines = wrap_text_px(text or "", font, inner)
        lh = int(text_height(font) * 1.3)
        if (len(lines) <= 2 and lh * len(lines) <= bottom - top) or size <= CAPTION_MIN:
            break
        size -= 2
    lines = lines[:2]
    ty = top + max(0, ((bottom - top) - lh * len(lines)) // 2)
    for line in lines:
        d.text((width // 2, ty + lh // 2), line, font=font, fill=T.IVORY, anchor="mm")
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
        d.rectangle([x0 - 2, y0 - 2, x1 + 3, y1 + 3], fill=regions.get("bg") or T.IVORY)
    bp = os.path.join(work_dir, f"edbase_{tag}.png")
    base.save(bp)
    return bp, rows


def split_title(base_path: str, frame_path: str, regions: dict, work_dir: str, tag: str):
    """바탕에서 제목 칸을 떼어 낸다(제목이 장면 시작에 따로 나타나게). 반환: (제목 PNG, x, y) 또는 None."""
    box = regions.get("title")
    if not box:
        return None
    x0, y0, x1, y1 = box
    im = Image.open(frame_path).convert("RGB")
    p = os.path.join(work_dir, f"title_{tag}.png")
    im.crop((x0, y0, x1, y1)).save(p)
    base = Image.open(base_path).convert("RGB")
    ImageDraw.Draw(base).rectangle([x0, y0, x1 - 1, y1 - 1], fill=regions.get("bg") or T.IVORY)
    base.save(base_path)
    return p, x0, y0


def count_fractions(steps: int = COUNT_STEPS) -> List[float]:
    """큰 숫자 올라가기의 단계별 비율(처음엔 빠르게, 끝에서 느리게). 마지막 1.0은 바탕 그림이 맡으므로 빼고 돌려준다."""
    return [round(1 - (1 - i / steps) ** 3, 4) for i in range(steps)]


def progress_png(path: str, width: int, color: str) -> str:
    Image.new("RGB", (width, PROGRESS_H), color or T.GOLD).save(path)
    return path


def mask_png(path: str, w: int, h: int, radius: int) -> str:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    m.save(path)
    return path


def media_inputs(media: SceneMedia, fps: int) -> List[List[str]]:
    """미디어의 ffmpeg 입력 인자(입력마다 한 묶음)."""
    if media.kind == "video":       # -stream_loop -1: 영상이 장면보다 짧으면 처음부터 다시 재생한다(마지막 장면에서 멈추지 않음)
        return [["-stream_loop", "-1", "-ss", f"{max(0.0, media.clip_start):.3f}", "-i", media.paths[0]]]
    n = 2 if media.kind == "image_pair" else 1
    return [["-loop", "1", "-framerate", str(fps), "-i", p] for p in media.paths[:n]]


def media_chain(media: SceneMedia, first: int, w: int, h: int, frames: int, fps: int, motion, over: float = 2.0) -> Tuple[List[str], str]:
    """사진 칸(w x h)을 채우는 영상 흐름을 만드는 필터. motion은 (zoom, x, y) zoompan 식 또는 None(정지).
    반환: (필터 조각들, 출력 이름)."""
    ow, oh = int(w * over) // 2 * 2, int(h * over) // 2 * 2       # 움직일 때 떨리지 않게 크게 만들어 두고 줄인다(전체 화면은 over를 낮춰 시간을 아낀다)
    cover = f"scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh}"
    if media.kind == "video":
        spd = f"setpts=PTS/{media.speed:.4f}," if abs(media.speed - 1.0) > 0.001 else ""
        return ([f"[{first}:v]{spd}fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
                 f"trim=end_frame={frames},setpts=PTS-STARTPTS[med]"], "med")

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


# =============================================================================
# 영상 중심 장면 — 표지·본문·한 장 요약·인용 장면은 미디어(영상·사진)를 화면 전체에 깔고,
# 위에 시리즈 이름 칩과 큰 제목, 아래에 큰 자막을 얹는다. 목록·숫자·표·안내 장면은 카드 모양을 그대로 쓴다.
# =============================================================================
FULL_TYPES = ("cover", "body", "single", "quote", "qa")   # 미디어를 화면 전체에 까는 카드 종류
FULL_PAD = 56
FULL_TITLE_TOP = 84        # 위 UI 가림 영역(safe_top) 아래에서 제목까지(칩 높이 포함)
FULL_SCRIM_TOP = 640       # 위 그라데이션 높이
FULL_SCRIM_BOTTOM = 760    # 아래 그라데이션 높이
LANDSCAPE_AR = 0.85        # 가로/세로 비율이 이보다 크면(거의 정사각형·가로 영상) 흐린 배경 위에 둔다


class FullSceneError(RuntimeError):
    """영상 중심 장면을 만들지 못했다(호출한 쪽이 카드 모양으로 대신 만든다)."""


def is_landscape(size: Tuple[int, int]) -> bool:
    w, h = size
    return bool(w and h and w / h > LANDSCAPE_AR)


def full_palette(design, radius_big: Optional[bool] = None) -> dict:
    """영상 중심 장면의 색·모서리. 디자인 색(배색 포함)에서 만들어서 공감(세이지)·신뢰(네이비)가 저절로 구분된다."""
    from cards.card_renderer import mix
    c = dict(getattr(design, "colors", None) or {})
    dark = getattr(design, "variant", "") == "dark" and c.get("dark_bg")
    band = mix(c["dark_bg"], T.WHITE, 0.10) if dark else (c.get("primary") or T.NAVY)
    accent = c.get("accent") or T.GOLD
    big = (getattr(design, "radius", 0) or 0) >= 24 if radius_big is None else radius_big
    return {
        "band": band, "deep": mix(band, T.BLACK, 0.55), "accent": accent, "soft": mix(accent, T.WHITE, 0.42),
        "line": mix(band, T.WHITE, 0.55), "cap_radius": 36 if big else 14, "pad": FULL_PAD,
    }


def _grad(w: int, h: int, color: str, a0: int, a1: int) -> Image.Image:
    """위→아래로 투명도가 a0→a1로 변하는 색 띠(RGBA)."""
    ramp = Image.linear_gradient("L").resize((w, h)).point(lambda v: int(a0 + (a1 - a0) * v / 255))
    layer = Image.new("RGBA", (w, h), _rgba(color, 255)[:3] + (255,))
    layer.putalpha(ramp)
    return layer


def scrim_png(path: str, pal: dict, width: int, height: int, safe_top: int, series: str, page: str, gradients: bool = True) -> str:
    """위·아래 어두운 그라데이션 + 시리즈 이름 칩 + 쪽 번호(움직이지 않는 층, 전체 화면 크기 RGBA). gradients=False(띠 모양)면 칩·쪽 번호만."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if gradients:
        img.alpha_composite(_grad(width, FULL_SCRIM_TOP, pal["deep"], 235, 0), (0, 0))
        img.alpha_composite(_grad(width, FULL_SCRIM_BOTTOM, pal["deep"], 0, 235), (0, height - FULL_SCRIM_BOTTOM))
    d = ImageDraw.Draw(img)
    pad = pal["pad"]
    if series:
        f = display_font(28, series)
        tw, h = int(f.getlength(series)) + 40, 28 + 24
        d.rounded_rectangle([pad, safe_top, pad + tw, safe_top + h], radius=h // 2, fill=_rgba(pal["accent"], 255))
        d.text((pad + tw / 2, safe_top + h / 2), series, font=f, fill=T.WHITE, anchor="mm")
    if page:
        d.text((width - pad, safe_top + 26), page, font=display_font(26, page), fill=T.WHITE, anchor="rm")
    img.save(path)
    return path


def full_title_png(path: str, text: str, pal: dict, width: int, safe_top: int, start: int = 80, minimum: int = 52, max_lines: int = 2):
    """큰 제목(*강조어*는 강조색, 글자 그림자로 밝은 영상 위에서도 읽힘). 최대 max_lines줄, 모자라면 글자를 줄인다(start→minimum).
    반환: (PNG 경로, x, y) — 폭 전체 크기의 투명 PNG라 x는 0."""
    toks, emph = [], False
    for seg in (text or "").split("*"):
        parts = seg.split(" ")
        for i, p in enumerate(parts):
            if p == "":
                if toks and i > 0:
                    toks[-1][2] = True
                continue
            toks.append([p, emph, i < len(parts) - 1])        # [글자, 강조, 뒤에 공백]
        emph = not emph
    avail = width - 2 * pal["pad"]
    plain = (text or "").replace("*", "") or "가"
    lines, font = [], None
    for size in range(start, minimum - 1, -4):
        font = display_font(size, plain)
        lines, cur, cw = [], [], 0.0
        for t in toks:
            ww = font.getlength(t[0] + (" " if t[2] else ""))
            if cur and cw + ww > avail and cur[-1][2]:
                lines.append(cur)
                cur, cw = [], 0.0
            cur.append(t)
            cw += ww
        lines.append(cur)
        if len(lines) <= max_lines and max(font.getlength("".join(w[0] + (" " if w[2] else "") for w in ln)) for ln in lines) <= avail:
            break
    lh = int(text_height(font) * 1.22)
    img = Image.new("RGBA", (width, lh * min(max_lines, len(lines)) + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 0
    for ln in lines[:max_lines]:
        x = pal["pad"]
        for word, em, sp in ln:
            fill = pal["soft"] if em else T.WHITE
            d.text((x + 2, y + 3), word, font=font, fill=(0, 0, 0, 110))     # 그림자
            d.text((x, y), word, font=font, fill=fill)
            x += font.getlength(word + (" " if sp else ""))
        y += lh
    img.save(path)
    return path, 0, safe_top + FULL_TITLE_TOP


def landscape_fit(size: Tuple[int, int], width: int) -> int:
    """가로 영상을 폭에 맞췄을 때의 높이(짝수)."""
    w, h = size
    return max(2, int(round(width * h / max(1, w))) // 2 * 2)


# --- 모든 장면을 영상 위에: 올린 영상 자동 사용 + 정보 장면 패널 ------------------------------------------------
NO_FULL = ("comparison_table",)     # 표는 영상 위에 올리면 읽기 어려워 카드 모양 그대로 둔다


def uses_full(slide_type: str) -> bool:
    return slide_type not in NO_FULL


def auto_video_media(storyboard, durations: List[float], explicit: Dict[int, bool], speed: float = 1.0) -> Dict[int, SceneMedia]:
    """올린 동영상을 장면 순서대로 이어 재생하도록 장면마다 SceneMedia(video, 시작 초)를 정한다.
    영상이 여러 편이면 장면마다 돌려 쓰고, 한 편이 끝나면 처음으로 돌아간다. explicit[n]이 참인 장면(사용자가 영상을 직접 고름)은 건너뛴다."""
    videos = [a for a in getattr(storyboard, "assets", []) if a.kind == "video" and a.path and os.path.exists(a.path)]
    if not videos:
        return {}
    for v in videos:
        if v.duration <= 0:
            v.duration = ffmpeg_tools.probe_duration(v.path)
    cursor = {v.id: 0.0 for v in videos}
    out: Dict[int, SceneMedia] = {}
    for n, dur in enumerate(durations):
        v = videos[n % len(videos)]
        dur = max(1.0, float(dur or 4.0))
        start = cursor[v.id]
        used = dur * speed                                 # 이 장면이 영상에서 쓰는 원본 길이(초)
        if v.duration > 0 and start + used > v.duration + 0.05:
            start = 0.0                                    # 영상이 끝나면 처음부터
        if not explicit.get(n):
            out[n] = SceneMedia("video", [v.path], round(start, 2), speed)
        cursor[v.id] = start + used
    return out


IVORY_DIM_ON_PANEL = "#CFCBC2"     # 강조되지 않은 패널의 글자색
LIST_PANEL_TYPES = ("steps", "numbered", "checklist", "event_info")     # 항목마다 패널이 있고 읽는 항목을 강조하는 종류
PANEL_STATES = ("on", "dim")      # on: 지금 읽는 항목(밝은 테두리·강조색 칸·흰 글자) | dim: 그 밖의 항목(차분하게)
HILITE_FADE = 0.2                 # 강조가 옮겨 갈 때 나타나는 시간(초)


def _glass(w: int, h: int, pal: dict, radius: int, state: str = "on") -> Tuple[Image.Image, ImageDraw.ImageDraw]:
    """영상 위에 얹는 반투명 어두운 패널(RGBA). state="dim"이면 테두리·왼쪽 막대를 차분하게."""
    from cards.card_renderer import mix
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if state == "dim":
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=_rgba(pal["deep"], 214), outline=_rgba(pal["line"], 80), width=2)
        d.rounded_rectangle([0, radius, 8, h - radius], radius=4, fill=_rgba(mix(pal["accent"], pal["deep"], 0.5), 255))
    else:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=_rgba(mix(pal["deep"], pal["band"], 0.55), 244),
                            outline=_rgba(pal["soft"], 255), width=4)
        d.rounded_rectangle([0, radius, 10, h - radius], radius=5, fill=_rgba(pal["accent"], 255))
    return img, d


def merge_layers(path: str, layers, width: int, height: int) -> str:
    """여러 패널을 화면 크기 투명 그림 한 장으로 합친다(ffmpeg 입력 수를 줄인다)."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for p, x, y in layers:
        with Image.open(p) as im:
            img.alpha_composite(im.convert("RGBA"), (int(x), int(y)))
    img.save(path)
    return path


def _fit_box(font_fn, text: str, width: int, height: int, start: int, minimum: int, max_lines: int):
    """width x height 칸 안에 max_lines줄 이내로 들어가는 가장 큰 글자 크기와 줄 목록(줄 높이까지 맞춰 잘리지 않게)."""
    size = start
    while True:
        font = font_fn(size, text or "가")
        wrapped = wrap_text_px(text or "", font, width)
        if (len(wrapped) <= max_lines and len(wrapped) * int(text_height(font) * 1.2) <= height) or size <= minimum:
            return font, wrapped[:max_lines]
        size -= 2


def panel_count(slide, items: List[str]) -> int:
    """이 장면이 아래 띠에 만드는 패널 줄 수(목록 항목 수 · 안내 줄 수 · 상담/큰 숫자는 1 · 나머지 0)."""
    from cards.layout_editorial import parse_info_rows
    t = slide.slide_type
    if t in ("steps", "numbered", "checklist"):
        return min(5, len(items))
    if t == "event_info":
        return min(5, len(parse_info_rows(slide.body_content, 5)))
    if t == "call_to_action" or (t == "big_number" and (slide.stat_value or "").strip()):
        return 1
    return 0


def band_geometry(height: int, rows: int) -> Tuple[int, int, int]:
    """띠 모양의 (영상 창 높이, 아래 띠 내용 시작 y, 아래 띠 내용 끝 y). 패널 줄이 많으면 영상 창을 줄여 줄마다 118px 이상을 준다."""
    region_bot = height - FULL_BOTTOM_SAFE - PROGRESS_H - 14           # 진행 막대 바로 위까지
    need = BAND_REGION_MIN if rows <= 0 else min(640, max(BAND_REGION_MIN, rows * 118 + (rows - 1) * 14))
    region_top = region_bot - need
    return region_top - 22 - BAND_VIDEO_TOP, region_top, region_bot


def _fit_text(draw_font_fn, text: str, width: int, start: int, minimum: int, lines: int):
    """width 안에 lines줄로 들어가는 가장 큰 글자 크기와 줄 목록."""
    size = start
    while True:
        font = draw_font_fn(size, text or "가")
        wrapped = wrap_text_px(text or "", font, width)
        if len(wrapped) <= lines or size <= minimum:
            return font, wrapped[:lines]
        size -= 2


def panel_layers(slide, items: List[str], pal: dict, width: int, bottom: int, work_dir: str, tag: str, phone: str = "", address: str = "",
                 top: Optional[int] = None, state: str = "on"):
    """정보 장면(단계·번호·체크·안내·상담 안내·큰 숫자)의 내용을 영상 위 패널로 만든다. 아래쪽(자막 바로 위)에 쌓고 위는 영상이 보이게 둔다.
    top을 주면(영상 띠 모양의 아래 띠) bottom-top 높이 안에 맞춘다.
    state: 목록·안내 줄 패널의 모양(PANEL_STATES). 상담 안내·큰 숫자 패널은 늘 "on" 모양.
    반환: [(PNG 경로, x, y), ...] — 목록 패널은 items 순서와 같다."""
    from cards.card_renderer import mix
    dim = state == "dim"
    ink = _rgba(IVORY_DIM_ON_PANEL, 255) if dim else T.WHITE
    chip = _rgba(mix(pal["accent"], pal["deep"], 0.45), 255) if dim else _rgba(pal["accent"], 255)
    from cards.layout_editorial import _draw_check_mark, parse_info_rows, split_item_head_desc
    pad, w = pal["pad"], width - 2 * pal["pad"]
    avail = (bottom - top) if top else min(bottom - 760, 620)
    r = int(pal["cap_radius"] * 0.7)
    t = slide.slide_type
    out: List[Tuple[str, int, int]] = []

    def save(img, y, name):
        p = os.path.join(work_dir, f"{name}_{tag}_{state}_{len(out)}.png")           # 패널마다 다른 파일(같은 이름이면 덮어써진다)
        img.save(p)
        out.append((p, pad, y))

    if t in ("steps", "numbered", "checklist") and items:
        items = items[:5]
        n, gap = len(items), 18
        rh = min(200, (avail - gap * (n - 1)) // n)
        y = bottom - (rh * n + gap * (n - 1))
        for i, it in enumerate(items):
            head, desc = split_item_head_desc(it)
            img, d = _glass(w, rh, pal, r, state)
            b = min(88, rh - 36)
            cy = rh // 2
            if t == "checklist":
                d.rounded_rectangle([40, cy - b // 2, 40 + b, cy + b // 2], radius=14, fill=chip)
                _draw_check_mark(d, 40 + b / 2, cy, b * 0.58, ink)
            else:
                num = f"{i + 1:02d}"
                d.rounded_rectangle([40, cy - b // 2, 40 + b, cy + b // 2], radius=14, fill=chip)
                d.text((40 + b / 2, cy), num, font=display_font(int(b * 0.46), num), fill=ink, anchor="mm")
            tx = 40 + b + 30
            budget = rh - 28
            hb = int(budget * (0.62 if desc else 1.0))
            hf, hl = _fit_box(display_font, head, w - tx - 30, hb, 54 if not desc else 46, 24, 2)
            df, dl = (_fit_box(display_font, desc, w - tx - 30, budget - hb - 4, 32, 18, 2) if desc else (None, []))
            hh, dh = int(text_height(hf) * 1.2), (int(text_height(df) * 1.25) if df else 0)
            ty = cy - (len(hl) * hh + len(dl) * dh) // 2
            for ln in hl:
                d.text((tx, ty), ln, font=hf, fill=ink)
                ty += hh
            for ln in dl:
                d.text((tx, ty), ln, font=df, fill=_rgba(pal["line"], 255))
                ty += dh
            save(img, y + i * (rh + gap), "pn")
    elif t == "event_info":
        rows = parse_info_rows(slide.body_content, 5)
        n, gap = len(rows), 18
        if n:
            rh = min(170, ((avail if top else min(bottom - 800, 560)) - gap * (n - 1)) // n)
            y = bottom - (rh * n + gap * (n - 1))
            for i, (label, value) in enumerate(rows):
                img, d = _glass(w, rh, pal, r, state)
                cy, vx = rh // 2, 40
                if label:
                    lf = display_font(30, label)
                    lw = int(lf.getlength(label)) + 36
                    d.rounded_rectangle([36, cy - 26, 36 + lw, cy + 26], radius=10, fill=chip)
                    d.text((36 + lw / 2, cy), label, font=lf, fill=ink, anchor="mm")
                    vx = 36 + lw + 26
                vf, vl = _fit_box(display_font, value, w - vx - 30, rh - 26, 50, 24, 2)
                vh = int(text_height(vf) * 1.2)
                ty = cy - vh * len(vl) // 2
                for ln in vl:
                    d.text((vx, ty), ln, font=vf, fill=ink)
                    ty += vh
                save(img, y + i * (rh + gap), "pn")
    elif t == "call_to_action":
        num = phone
        if not num:
            return out
        h = 400
        img, d = _glass(w, h, pal, r)
        d.text((56, 70), "상담 문의", font=display_font(36, "상담 문의"), fill=_rgba(pal["soft"], 255), anchor="lm")
        size = 140
        while display_font(size, num).getlength(num) > w - 112 and size > 60:
            size -= 4
        d.text((56, 195), num, font=display_font(size, num), fill=T.WHITE, anchor="lm")
        if address:
            af, al = _fit_text(display_font, address, w - 112, 34, 22, 2)
            ty = 290
            for ln in al:
                d.text((56, ty), ln, font=af, fill=_rgba(pal["line"], 255))
                ty += int(text_height(af) * 1.3)
        save(img, bottom - h, "pn")
    elif t == "big_number" and (slide.stat_value or "").strip():
        h = 440
        img, d = _glass(w, h, pal, r)
        val = slide.stat_value.strip()
        size = 190
        while display_font(size, val).getlength(val) > w - 120 and size > 70:
            size -= 6
        d.text((60, 170), val, font=display_font(size, val), fill=_rgba(pal["soft"], 255), anchor="lm")
        if (slide.stat_label or "").strip():
            lf, ll = _fit_text(display_font, slide.stat_label.strip(), w - 120, 44, 26, 2)
            ty = 170 + size // 2 + 30
            for ln in ll:
                d.text((60, ty), ln, font=lf, fill=T.WHITE)
                ty += int(text_height(lf) * 1.3)
        save(img, bottom - h, "pn")
    return out


# --- 영상 띠 모양: 위 띠(시리즈 칩·제목) + 가운데 영상 창 + 아래 띠(자막 또는 내용 패널) ---------------------------------
BAND_VIDEO_TOP = 430       # 영상 창이 시작하는 y(위 띠 높이)
BAND_VIDEO_H = 886         # 영상 창 기본 높이(폭은 화면 폭 전체). 정보 장면은 패널 줄 수에 따라 band_geometry가 줄인다
FULL_BOTTOM_SAFE = 150     # 영상 위주 모양의 아래 UI 가림 영역(예전 카드 모양은 240) — 그 아래는 쓰지 않는다
BAND_REGION_MIN = 420      # 아래 띠 내용 영역의 최소 높이
BAND_TITLE_SHIFT = 18      # 제목을 전체 화면 모양보다 조금 아래로(칩과 간격)
VIDEO_LAYOUTS = ("band", "full", "card")     # 영상 띠 | 영상 전체 화면(영상 위 글자) | 카드 모양(예전, 사진 칸)


def band_base_png(path: str, pal: dict, width: int, height: int, vh: int = BAND_VIDEO_H) -> str:
    """띠 모양의 바탕: 위 띠는 디자인 색, 영상 창 아래는 한 단계 어두운 색, 위 띠 끝에 가는 포인트 선. (영상 창 자리는 영상이 덮는다)"""
    img = Image.new("RGB", (width, height), _rgba(pal["band"], 255)[:3])
    d = ImageDraw.Draw(img)
    d.rectangle([0, BAND_VIDEO_TOP + vh, width, height], fill=_rgba(pal["deep"], 255)[:3])
    d.rectangle([0, BAND_VIDEO_TOP - 6, width, BAND_VIDEO_TOP - 1], fill=_rgba(pal["accent"], 255)[:3])
    img.save(path)
    return path


def fit_size(size: Tuple[int, int], win_w: int, win_h: int) -> Tuple[int, int]:
    """미디어 전체가 창에 들어가게 맞춘 크기(짝수). 창과 거의 같은 비율이면 창을 꽉 채운다."""
    w, h = size
    sc = min(win_w / max(1, w), win_h / max(1, h))
    fw, fh = max(2, int(round(w * sc)) // 2 * 2), max(2, int(round(h * sc)) // 2 * 2)
    return fw, fh


VIDEO_SPEEDS = ("auto", "0.5", "0.75", "1", "1.5", "2")      # 재생 속도 선택값(auto: 영상이 짧으면 천천히, 최대 0.5배까지)


def resolve_speed(option: str, storyboard, total_seconds: float) -> float:
    """재생 속도 옵션 → 배수. auto는 올린 영상의 합계가 쇼츠 길이보다 짧을 때만 그만큼 천천히(0.5배까지, 모자라면 반복)."""
    opt = str(option or "auto")
    if opt != "auto":
        try:
            return max(0.25, min(4.0, float(opt)))
        except ValueError:
            return 1.0
    total = sum(max(0.0, a.duration) for a in getattr(storyboard, "assets", []) if a.kind == "video" and a.path and os.path.exists(a.path))
    if total <= 0 or total_seconds <= 0 or total >= total_seconds:
        return 1.0
    return max(0.5, round(total / total_seconds, 2))


# --- 띠 모양의 내용 맞춤 배치: 고정 높이 없이 [칩·쪽 번호] [머리말] [제목] [영상 창] [요약 한 줄] [자막 또는 패널]을 위에서부터 쌓는다 ---
BAND_HEAD_H = 56           # 시리즈 칩·쪽 번호 줄
BAND_KICK_H = 46           # 머리말 줄
BAND_TIGHT = 22            # 칩-머리말-제목 사이
BAND_GAP_MIN = 26          # 그 밖의 블록 사이 최소 간격
BAND_WIN_MIN = 440         # 영상 창 최소 높이
BAND_TITLE_SIZES = (108, 84, 60)     # 제목 글자: 최대(남는 자리가 있을 때) · 기본 · 최소


def band_lower_height(slide, items: List[str]) -> int:
    """아래 블록 높이: 정보 장면은 패널 묶음, 그 밖에는 자막 칸."""
    n = panel_count(slide, items)
    if n <= 0:
        return CAPTION_H
    if slide.slide_type == "call_to_action":
        return 400
    if slide.slide_type == "big_number":
        return 440
    return min(640, max(150, n * 132 + (n - 1) * 14))


def takeaway_lines(text: str, width: int, pad: int):
    """요약 한 줄(최대 2줄)의 글꼴·줄·줄 높이."""
    text = " ".join((text or "").replace("*", "").split())
    if not text:
        return None, [], 0
    font = display_font(50, text)
    lines = wrap_text_px(text, font, width - 2 * pad - 40)
    if len(lines) > 2:
        font = display_font(42, text)
        lines = wrap_text_px(text, font, width - 2 * pad - 40)[:2]
    return font, lines, int(text_height(font) * 1.25)


def band_plan(work_dir: str, tag: str, pal: dict, width: int, height: int, safe_top: int, series: str, page: str, kicker: str,
              title: str, takeaway: str, lower_h: int, media_size: Tuple[int, int]) -> dict:
    """띠 모양 장면의 배치를 정하고 움직이지 않는 층을 그린다.
    영상 창은 미디어 비율 그대로(폭 전체)가 들어가면 그 높이, 아니면 남는 높이(미디어 전체가 보이게 맞추고 양옆은 흐린 배경).
    남는 높이가 있으면 제목을 키우고(최대 108px·3줄), 그래도 남는 여백은 블록 사이에 고르게 나눈다.
    반환: base(그라데이션 바탕 PNG) · static(칩·쪽 번호·머리말·요약 한 줄 RGBA PNG) · title(PNG)·title_y · win_y·win_h · lower_y·lower_h · takeaway(그렸는지)."""
    from cards.card_renderer import mix
    top, bottom = safe_top, height - FULL_BOTTOM_SAFE - PROGRESS_H - 14
    avail = bottom - top
    kick_h = BAND_KICK_H if kicker else 0
    tk_font, tk_lines, tk_lh = takeaway_lines(takeaway, width, pal["pad"])
    mw, mh = media_size
    nat = max(2, int(round(width * mh / max(1, mw)))) if mw and mh else 608

    def title_png(start: int, lines: int = 3):
        path, _x, _y = full_title_png(os.path.join(work_dir, f"btitle_{tag}.png"), title, pal, width, 0, start=start,
                                      minimum=BAND_TITLE_SIZES[2], max_lines=lines)
        with Image.open(path) as im:
            return path, im.height

    def measure(title_h: int, tk_h: int):
        """(영상 창 높이, 남는 높이). 블록 수에 맞는 최소 간격을 뺀 뒤."""
        n_loose = 2 + (1 if tk_h else 0)                       # 제목-영상, 영상-(요약), (요약)-아래
        tight = BAND_TIGHT * (2 if kick_h else 1)
        room = avail - BAND_HEAD_H - kick_h - title_h - tk_h - lower_h - tight - BAND_GAP_MIN * n_loose
        return min(nat, room), room - min(nat, room), n_loose

    tk_h = tk_lh * len(tk_lines) + 10 if tk_lines else 0
    tpath, th = title_png(BAND_TITLE_SIZES[1])
    win_h, spare, n_loose = measure(th, tk_h)
    if win_h < BAND_WIN_MIN and tk_h:                          # 자리가 모자라면 요약 한 줄부터 뺀다
        tk_h, tk_lines = 0, []
        win_h, spare, n_loose = measure(th, tk_h)
    if win_h < BAND_WIN_MIN:                                   # 그래도 모자라면 제목을 2줄 이내로
        tpath, th = title_png(BAND_TITLE_SIZES[1], lines=2)
        win_h, spare, n_loose = measure(th, tk_h)
    win_h = max(240, win_h // 2 * 2)
    size = BAND_TITLE_SIZES[1]
    while size < BAND_TITLE_SIZES[0] and spare > 60:           # 남는 자리로 제목을 키운다
        cand, ch = title_png(size + 4)
        w2, s2, _n = measure(ch, tk_h)
        if w2 < win_h or s2 < 40:
            tpath, th = title_png(size)                        # 마지막으로 그린 파일을 이 크기로 되돌린다
            break
        size, tpath, th, spare = size + 4, cand, ch, s2
    gap = BAND_GAP_MIN + max(0, spare) // n_loose

    y = top
    head_y = y
    y += BAND_HEAD_H + BAND_TIGHT
    kick_y = y
    if kick_h:
        y += kick_h + BAND_TIGHT
    title_y = y
    y += th + gap
    win_y = y
    y += win_h + gap
    tk_y = y
    if tk_h:
        y += tk_h + gap
    lower_y = y

    base = Image.new("RGB", (width, height))
    bd = ImageDraw.Draw(base)
    for yy in range(height):                                   # 하나로 이어진 바탕(위 디자인 색 → 아래 어두운 색)
        bd.line([(0, yy), (width, yy)], fill=mix(pal["band"], pal["deep"], min(1.0, yy / height * 1.15)))
    base_path = os.path.join(work_dir, f"bbase_{tag}.png")
    base.save(base_path)

    st = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(st)
    pad = pal["pad"]
    if series:
        f = display_font(28, series)
        tw = int(f.getlength(series)) + 40
        d.rounded_rectangle([pad, head_y + 2, pad + tw, head_y + 54], radius=26, fill=_rgba(pal["accent"], 255))
        d.text((pad + tw / 2, head_y + 28), series, font=f, fill=T.WHITE, anchor="mm")
    if page:
        d.text((width - pad, head_y + 28), page, font=display_font(26, page), fill=T.WHITE, anchor="rm")
    if kick_h:
        d.text((pad, kick_y), kicker, font=display_font(34, kicker), fill=_rgba(pal["soft"], 255))
    if tk_h:
        d.rounded_rectangle([pad, tk_y + 4, pad + 9, tk_y + tk_lh * len(tk_lines)], radius=4, fill=_rgba(pal["accent"], 255))
        for i, ln in enumerate(tk_lines):
            d.text((pad + 34, tk_y + i * tk_lh), ln, font=tk_font, fill=T.WHITE)
    static_path = os.path.join(work_dir, f"bstatic_{tag}.png")
    st.save(static_path)
    return {"base": base_path, "static": static_path, "title": tpath, "title_y": title_y, "win_y": win_y, "win_h": win_h,
            "lower_y": lower_y, "lower_h": lower_h, "takeaway": bool(tk_h), "title_size": size, "gap": gap, "kicker": bool(kick_h)}


# --- 영상 전체 화면 모양: 가로 영상 아래에 카드의 요약 한 줄·본문을 정리한 패널 ------------------------------------------
INFO_PANEL_MIN = 220       # 이보다 낮은 자리에는 패널을 넣지 않는다(자막을 쓴다)
INFO_PANEL_MAX = 640


def card_body_lines(slide, limit: int = 5) -> List[str]:
    """카드 본문을 화면에 보일 줄로(글머리표·번호·강조 표시 제거)."""
    out = []
    for raw in (getattr(slide, "body_content", "") or "").replace("\\n", "\n").split("\n"):
        line = re.sub(r"^\s*(?:[-•·*✓]|\d+[.)])\s*", "", raw).replace("*", "").strip()
        if line:
            out.append(line)
    return out[:limit]


def info_panel_png(path: str, pal: dict, width: int, avail: int, takeaway: str, body: List[str]):
    """요약 한 줄(굵게, 강조색 막대) + 본문(자리에 맞는 가장 큰 글자)을 담은 반투명 패널. 높이는 내용에 맞추되 avail·INFO_PANEL_MAX 이내.
    반환: (PNG 경로, 높이, 다 들어갔는지) — 내용이 없거나 자리가 모자라면 None. '다 들어갔는지'는 본문이 잘리지 않고 글자가 36px 이상일 때 참."""
    takeaway = " ".join((takeaway or "").replace("*", "").split())
    text = " ".join(body)
    if avail < INFO_PANEL_MIN or not (takeaway or text):
        return None
    w = width - 2 * pal["pad"]
    inner = w - 96
    limit = min(avail, INFO_PANEL_MAX)
    tk_font, tk_lines, tk_lh = (None, [], 0)
    if takeaway:
        tk_font = display_font(52, takeaway)
        tk_lines = wrap_text_px(takeaway, tk_font, inner - 30)
        if len(tk_lines) > 2:
            tk_font = display_font(44, takeaway)
            tk_lines = wrap_text_px(takeaway, tk_font, inner - 30)[:2]
        tk_lh = int(text_height(tk_font) * 1.25)
    tk_h = tk_lh * len(tk_lines)
    b_font, b_lines, b_lh, fits = None, [], 0, True
    if text:
        room = limit - 80 - tk_h - (34 if tk_h else 0)
        size = 46
        while True:                                            # 문장마다 줄바꿈해 자리에 들어가는 가장 큰 글자
            b_font = display_font(size, text)
            b_lines = [ln for t in body for ln in wrap_text_px(t, b_font, inner)]
            b_lh = int(text_height(b_font) * 1.4)
            if b_lh * len(b_lines) <= room or size <= 30:
                break
            size -= 2
        fits = b_lh * len(b_lines) <= room and size >= 36
        b_lines = b_lines[:max(0, room // max(1, b_lh))]
    h = 80 + tk_h + (34 if (tk_h and b_lines) else 0) + b_lh * len(b_lines)
    img, d = _glass(w, h, pal, int(pal["cap_radius"] * 0.7), "dim")
    y = 40
    if tk_lines:
        d.rounded_rectangle([44, y + 4, 52, y + tk_h - 6], radius=4, fill=_rgba(pal["accent"], 255))
        for ln in tk_lines:
            d.text((74, y), ln, font=tk_font, fill=T.WHITE)
            y += tk_lh
        y += 34 if b_lines else 0
    for ln in b_lines:
        d.text((48, y), ln, font=b_font, fill=_rgba(IVORY_TEXT_ON_PANEL, 255))
        y += b_lh
    img.save(path)
    return path, h, fits


IVORY_TEXT_ON_PANEL = "#EDEAE3"
