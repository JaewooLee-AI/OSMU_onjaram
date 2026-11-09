import logging
import os
import re
import shutil
import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from cards.schema import ShortsScene, EditableStoryboard, MediaAsset
from cards.fonts import korean_font, display_font, wrap_text_px, text_height
from cards import brand as bk
from cards import ffmpeg_tools
from cards.card_renderer import tint, _rgb
SCENE_GAP = 0.3  # 씬 사이 호흡(초)


@dataclass
class ShortsOptions:
    """렌더링 시점 옵션 (스토리보드를 다시 만들지 않고 바꿀 수 있는 항목)"""
    frame_style: str = "tri"            # tri(3단: 위 제목·가운데 사진/인포그래픽·아래 소속 — 카드와 같은 템플릿) | kinetic(키네틱 타이포 영상)
    caption_style: str = "basic"        # (kinetic 전용) basic(기본 팝업) | kinetic(키네틱 타이포)
    voice: str = "auto"                 # auto | Gemini 목소리 이름 | free(무료 gTTS)
    tts_call: Any = None                # 시험용: 음성 합성 호출을 대신하는 async 함수
    photo_motion: str = "none"          # (tri 전용) none(정지) | zoom_in | zoom_out | alternate(확대·축소 번갈아) | dynamic(확대·축소+좌우상하 이동을 장면마다 바꿔 씀) — 가운데 사진 칸만 움직임
    text_motion: str = "none"           # (tri 전용) none | slide(제목은 위에서·아래 글자는 아래에서 미끄러져 들어오며 나타남)
    transition: str = "none"            # (tri 전용) none | auto(장면 사이 전환 효과 — 장면마다 다른 효과를 돌려 씀)
    video_scope: str = "none"           # none | opening | key2 | all  (AI 영상화 범위)
    video_mode: str = "image"           # image(사진 움직이기) | link(다음 장면 사진까지 이어서)
    video_overrides: Optional[Dict[int, MediaAsset]] = None  # {장면 인덱스: AI 동영상} — 해당 장면 배경만 교체


class ShortsRendererService:
    """쇼츠/릴스 (9:16, 1080x1920) 비디오 렌더링 서비스

    파이프라인: 씬별 TTS → 단어 타임라인 산출 → 씬별 영상 세그먼트(첨부 영상 구간 9:16 변환 /
    이미지 켄 번스 / 브랜드 배경) → 자막·타이틀 오버레이 PNG 시퀀스(Pillow) → FFmpeg 최종 인코딩.
    자막을 Pillow로 직접 그리므로 libass가 없는 FFmpeg 빌드에서도 자막이 입혀진다.
    `captions.ass`는 편집 툴용 사이드카 파일로 함께 저장한다.
    """

    WIDTH = 1080
    HEIGHT = 1920
    FPS = 30
    SECTION_LABELS = {"hook": "오프닝", "body": "핵심 포인트", "conclusion": "마무리"}

    def __init__(self, export_dir: str = None):
        if not export_dir:
            from cards.paths import EXPORTS_DIR
            self.export_dir = os.path.join(EXPORTS_DIR, "shorts")
        else:
            self.export_dir = export_dir
        os.makedirs(self.export_dir, exist_ok=True)
        self.last_warnings: List[str] = []
        self.last_tts_engine: str = ""
        self.options = ShortsOptions()
        self.kit: bk.BrandKit = bk.active_kit()
        self.elements = None

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------
    async def render_shorts_video(self, storyboard: EditableStoryboard, progress_callback=None,
                                  options: Optional[ShortsOptions] = None) -> str:
        scenes = [s for s in storyboard.shorts_scenes if (s.narration_script or "").strip()]
        if not scenes:
            raise ValueError("내레이션이 있는 쇼츠 씬이 없습니다.")
        ffmpeg_tools.require()

        self.last_warnings = []
        self.options = options or ShortsOptions()
        try:
            self.kit = bk.load_kit(storyboard.brand_id) if storyboard.brand_id else bk.active_kit()
        except (OSError, ValueError):
            self.kit = bk.active_kit()
        self.elements = storyboard.brand_elements
        if self.options.frame_style == "tri":
            return await self._render_tri(storyboard, scenes, progress_callback)
        output_mp4 = os.path.join(self.export_dir, "final_shorts.mp4")
        audio_path = os.path.join(self.export_dir, "combined_narration.mp3")
        ass_path = os.path.join(self.export_dir, "captions.ass")
        bg_path = os.path.join(self.export_dir, "shorts_bg.png")
        work_dir = os.path.join(self.export_dir, "_work")
        shutil.rmtree(work_dir, ignore_errors=True)
        os.makedirs(work_dir)

        async def progress(pct: float, msg: str):
            if progress_callback:
                await progress_callback(pct, msg)

        try:
            await progress(0.1, "씬별 한국어 내레이션 음성 합성 중...")
            scene_timeline, total_duration = await self._synthesize_scenes(
                scenes, work_dir, audio_path, storyboard.tone_and_manner or "")

            await progress(0.4, "단어별 하이라이트 자막 타임라인 계산 중...")
            events = self._build_caption_events(scene_timeline, total_duration)
            self._build_karaoke_ass_file(events, Path(ass_path))

            await progress(0.5, "씬별 영상 트랙 구성 중 (첨부 영상 트림·9:16 변환, 이미지 모션)...")
            await asyncio.to_thread(self._generate_vertical_background, bg_path)
            video_track, media_flags = await self._build_video_track(storyboard, scene_timeline, work_dir, bg_path)

            await progress(0.65, "자막·타이틀 오버레이 프레임 생성 중...")
            concat_path = await asyncio.to_thread(
                self._render_overlay_sequence, storyboard.title, scene_timeline, events, total_duration, work_dir, media_flags
            )

            await progress(0.8, "FFmpeg H.264 최종 인코딩 중 (영상 + 자막 + 내레이션)...")
            await self._run_ffmpeg_encode(video_track, concat_path, audio_path, output_mp4, total_duration)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        await progress(1.0, "쇼츠 렌더링 완료!")
        return output_mp4

    # ------------------------------------------------------------------
    # 3단(tri) 프레임 쇼츠: 카드와 같은 템플릿을 9:16(1080x1920, 위아래 250px 안전 여백)으로 그려 이어 붙입니다.
    # 장면마다 원본 카드를 한 프레임으로 그리고, 내레이션 길이만큼 보여 줍니다(영상 클립·AI 영상은 쓰지 않음).
    # ------------------------------------------------------------------
    async def _render_tri(self, storyboard: EditableStoryboard, scenes: List[ShortsScene], progress_callback=None) -> str:
        from cards import design_templates
        from cards.card_renderer import CardNewsRendererService

        async def progress(pct: float, msg: str):
            if progress_callback:
                await progress_callback(pct, msg)

        output_mp4 = os.path.join(self.export_dir, "final_shorts.mp4")
        audio_path = os.path.join(self.export_dir, "combined_narration.mp3")
        work_dir = os.path.join(self.export_dir, "_work")
        shutil.rmtree(work_dir, ignore_errors=True)
        os.makedirs(work_dir)
        try:
            await progress(0.1, "씬별 한국어 내레이션 음성 합성 중...")
            timeline, total = await self._synthesize_scenes(scenes, work_dir, audio_path, storyboard.tone_and_manner or "")

            await progress(0.5, "3단 프레임 그리는 중...")
            design = design_templates.get(storyboard.design_id)
            # 3단 디자인은 쇼츠용 3단 프레임으로, 그 밖의 디자인(온자람 등)은 카드를 그 디자인 그대로 9:16 화면 가운데 놓는다.
            card_mode = design.layout != "tri"
            tri_id = storyboard.design_id
            if card_mode:
                sb2 = storyboard
                frames = CardNewsRendererService(export_dir=os.path.join(work_dir, "frames"))
            else:
                sb2 = storyboard.model_copy(update={"design_id": tri_id})
                frames = CardNewsRendererService(export_dir=os.path.join(work_dir, "frames"))
                frames.HEIGHT, frames.safe_top, frames.safe_bottom = self.HEIGHT, 250, 250
                frames.FOLLOW_ASPECT = False
            motion = self.options.photo_motion
            text_motion = self.options.text_motion != "none"
            use_trans = self.options.transition != "none" and len(timeline) > 1
            fps = self.FPS
            half = max(1, round(self.TRANSITION_SEC * fps / 2)) if use_trans else 0
            _, (m0, m1), _ = frames._tri_zones(design.ratio if design.layout == "tri" else [2, 5, 3])
            if card_mode:
                m0 = m1 = 0
            animated = motion != "none" or text_motion or use_trans
            listing, last, moved = [], None, 0
            seg_frames: List[Tuple[str, int]] = []
            n_scenes = len(timeline)
            for n, item in enumerate(timeline):
                scene = item["scene"]
                source = (scene.source_cards or [1])[0]
                idx = max(0, min(source, len(storyboard.card_slides)) - 1)
                path = await frames.render_slide(sb2, idx)
                dur = item["end"] - item["start"]
                if card_mode:
                    bg_path, card_path, cy, path = self._card_canvas(path, work_dir, f"{n:02d}", scene)
                if animated:
                    slide = storyboard.card_slides[idx]
                    has_photo = (not card_mode) and bool(slide.asset_id and storyboard.asset(slide.asset_id)
                                     and slide.slide_type in ("cover", "body", "single", "quote")
                                     and design_templates.get(tri_id).uses_photo(slide.slide_type))
                    if motion == "alternate":
                        kind = "zoom_in" if n % 2 == 0 else "zoom_out"
                    elif motion == "dynamic":
                        kind = f"dyn{n % len(self.DYNAMIC_MOTIONS)}"
                    else:
                        kind = motion
                    b_f, e_f = round(item["start"] * fps), round(item["end"] * fps)
                    lead = half if (use_trans and n > 0) else 0
                    tail = half if (use_trans and n < n_scenes - 1) else 0
                    n_frames = max(2, (e_f + tail) - (b_f - lead)) if use_trans else max(2, int(round(dur * fps)))
                    seg = os.path.join(work_dir, f"seg_{n:02d}.mp4")
                    if card_mode:
                        await self._card_scene_segment(bg_path, card_path, cy, n_frames, seg, motion, n, text_motion,
                                                       delay=(lead / fps + 0.1) if text_motion else 0.0)
                        moved += 1
                        path = seg
                        seg_frames.append((seg, n_frames))
                        listing.append((path, dur))
                        last = path
                        continue
                    await self._tri_scene_segment(path, n_frames, seg, (m0, m1), has_photo and motion != "none", kind,
                                                  text_motion, delay=(lead / fps + 0.1) if text_motion else 0.0, tag=f"{n:02d}", work_dir=work_dir)
                    moved += 1 if (has_photo and motion != "none") else 0
                    path = seg
                    seg_frames.append((seg, n_frames))
                listing.append((path, dur))
                last = path
            if motion != "none" and not moved and not card_mode:
                self.last_warnings.append("사진이 들어간 장면이 없어 움직임을 적용하지 못했습니다(카드에 사진을 넣으면 가운데 사진이 움직입니다).")
            video_in = None
            if use_trans:
                video_in = await self._xfade_segments(seg_frames, half, work_dir)
            if video_in is None:
                lines = []
                for path, dur in listing:
                    lines += [f"file '{path.replace(chr(92), '/').replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'", f"duration {dur:.3f}"]
                lines.append(f"file '{last.replace(chr(92), '/')}'")   # concat 규칙: 마지막 프레임을 한 번 더
                concat = os.path.join(work_dir, "frames.txt")
                with open(concat, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                video_in = ["-f", "concat", "-safe", "0", "-i", concat]
                if use_trans:   # 전환 합성이 실패했을 때: 겹침 없이 잘라 이어 붙인다
                    video_in = await self._trim_concat(seg_frames, half, work_dir) or video_in

            await progress(0.8, "FFmpeg H.264 최종 인코딩 중 (영상 + 내레이션)...")
            if animated:   # 이미 장면마다 H.264로 만들어 둔 조각을 이어 붙이고 음성만 얹는다
                await self._run([ffmpeg_tools.ffmpeg(), "-y", "-v", "error", *video_in, "-i", audio_path,
                                 "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}",
                                 "-movflags", "+faststart", output_mp4], "3단 쇼츠 인코딩 실패")
            else:
                await self._run([ffmpeg_tools.ffmpeg(), "-y", "-v", "error", *video_in, "-i", audio_path,
                                 "-vf", f"fps={self.FPS},format=yuv420p,scale={self.WIDTH}:{self.HEIGHT}", *ffmpeg_tools.h264_args("good", "medium"), "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", output_mp4],
                                "3단 쇼츠 인코딩 실패")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        await progress(1.0, "쇼츠 렌더링 완료!")
        return output_mp4

    # 확대·축소와 좌우상하 이동을 섞은 "다이나믹" 동작. (시작 확대, 끝 확대, 시작 x, 끝 x, 시작 y, 끝 y) — x·y는 0~1(가장자리~가장자리)
    DYNAMIC_MOTIONS = [
        (1.05, 1.40, 0.50, 0.78, 0.55, 0.30),   # 확대하며 오른쪽 위로
        (1.32, 1.32, 0.08, 0.92, 0.50, 0.50),   # 왼쪽에서 오른쪽으로 훑기
        (1.45, 1.08, 0.72, 0.30, 0.28, 0.62),   # 축소하며 왼쪽 아래로
        (1.30, 1.30, 0.92, 0.08, 0.62, 0.38),   # 오른쪽에서 왼쪽으로 훑기
    ]
    TRI_TRANSITIONS = ["smoothleft", "zoomin", "smoothup", "smoothright"]
    TEXT_SLIDE_SEC = 0.45
    TEXT_SLIDE_PX = 70

    def _zone_motion_expr(self, kind: str, frames: int) -> Tuple[str, str, str]:
        """사진 칸 zoompan용 (zoom, x, y) 식. `dyn<n>`은 DYNAMIC_MOTIONS[n]을 부드럽게(ease in-out) 따라간다."""
        if kind.startswith("dyn"):
            z0, z1, x0, x1, y0, y1 = self.DYNAMIC_MOTIONS[int(kind[3:]) % len(self.DYNAMIC_MOTIONS)]
            p = f"(on/{max(1, frames - 1)})"
            e = f"({p}*{p}*(3-2*{p}))"
            return (f"{z0}+({z1 - z0:.4f})*{e}", f"(iw-iw/zoom)*({x0}+({x1 - x0:.4f})*{e})", f"(ih-ih/zoom)*({y0}+({y1 - y0:.4f})*{e})")
        return self._motion_expr(kind, frames)

    def _split_text_layers(self, frame_path: str, zone, work_dir: str, tag: str):
        """3단 프레임에서 위·아래 글자 칸을 따로 떼어 낸다. 위·아래 칸 배경은 한 색이라, 배경과 다른 픽셀만 글자 층(투명 PNG)으로 만들고
        바탕 프레임에서는 그 칸을 배경색으로 비운다. 배경이 한 색이 아니면(그라데이션 등) 그 칸은 움직이지 않고 그대로 둔다.
        반환: (바탕 프레임 경로, [(글자 층 경로, 놓을 y, 방향 -1 위/+1 아래)])"""
        m0, m1 = zone
        im = Image.open(frame_path).convert("RGB")
        W, H = im.size
        base = im.copy()
        layers = []
        for name, (y0, y1), sign in (("top", (0, m0), -1), ("bot", (m1, H), 1)):
            if y1 - y0 < 4:
                continue
            band = im.crop((0, y0, W, y1))
            bg = band.getpixel((2, 2 if sign < 0 else y1 - y0 - 3))
            diff = ImageChops.difference(band, Image.new("RGB", band.size, bg)).convert("L")
            mask = diff.point(lambda v: 255 if v > 0 else 0)
            hist = mask.histogram()
            if hist[255] > 0.4 * band.width * band.height or hist[255] == 0:
                continue                      # 배경이 한 색이 아님 / 글자가 없음 → 그대로 둔다
            mask = mask.filter(ImageFilter.MaxFilter(3))
            layer = band.convert("RGBA")
            layer.putalpha(mask)
            lpath = os.path.join(work_dir, f"txt_{tag}_{name}.png")
            layer.save(lpath)
            base.paste(Image.new("RGB", band.size, bg), (0, y0))
            layers.append((lpath, y0, sign))
        bpath = os.path.join(work_dir, f"base_{tag}.png")
        base.save(bpath)
        return bpath, layers

    def _card_canvas(self, card_path: str, work_dir: str, tag: str, scene: Optional[ShortsScene] = None):
        """카드(폭 1080)를 9:16 화면 가운데에 놓는다. 가장자리가 한 색이면 그 색으로, 아니면 카드를 흐리게 키운 것으로 바탕을 채운다.
        반환: (바탕만 있는 PNG, 카드 PNG, 카드를 놓을 y, 바탕+카드를 합친 PNG)"""
        W, H = self.WIDTH, self.HEIGHT
        card = Image.open(card_path).convert("RGB")
        if card.width != W:
            card = card.resize((W, round(card.height * W / card.width)), Image.LANCZOS)
        if card.height > H:
            card = card.resize((round(card.width * H / card.height), H), Image.LANCZOS)
        w, h = card.size
        strips = [card.crop((0, 0, w, 4)), card.crop((0, h - 4, w, h)), card.crop((0, 0, 4, h)), card.crop((w - 4, 0, w, h))]
        # 가장자리 네 줄이 거의 한 색이면(색이 조금씩 달라도 됨) 위→아래 색을 이은 단색 바탕, 아니면 카드를 흐리게 키운 바탕.
        flat = all(max(hi - lo for lo, hi in st.getextrema()) <= 14 for st in strips)
        if flat:
            c_top = strips[0].resize((1, 1), Image.BOX).getpixel((0, 0))
            c_bot = strips[1].resize((1, 1), Image.BOX).getpixel((0, 0))
            col = Image.new("RGB", (1, 2))
            col.putpixel((0, 0), c_top)
            col.putpixel((0, 1), c_bot)
            bg = col.resize((W, H), Image.BILINEAR)
        else:
            small = card.resize((max(1, w // 8), max(1, h // 8)))
            bg = small.resize((W, H), Image.BILINEAR).filter(ImageFilter.GaussianBlur(24))
            bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.25)
        y = (H - card.height) // 2
        if scene is not None:
            self._fill_margins(bg, y, card.height, scene)
        bg_path = os.path.join(work_dir, f"cbg_{tag}.png")
        cp = os.path.join(work_dir, f"card_{tag}.png")
        full = os.path.join(work_dir, f"cfull_{tag}.png")
        bg.save(bg_path)
        card.save(cp)
        merged = bg.copy()
        merged.paste(card, (0, y))
        merged.save(full)
        return bg_path, cp, y, full

    def _fill_margins(self, bg: Image.Image, y: int, card_h: int, scene: ShortsScene) -> None:
        """카드 위·아래 빈 띠에 내용을 채운다. 위: 브랜드 이름·한 줄 소개. 아래: 이 장면의 자막, 그 밑에 상담 연락처.
        띠가 낮으면(<120px) 그 띠는 비워 둔다. 글자색은 바탕 밝기에 맞춘다."""
        W, H = self.WIDTH, self.HEIGHT
        kit = getattr(self, "kit", None)
        el = getattr(self, "elements", None)
        d = ImageDraw.Draw(bg)

        def ink(box):
            r, g, b = bg.crop(box).resize((1, 1), Image.BOX).getpixel((0, 0))
            dark = (0.299 * r + 0.587 * g + 0.114 * b) < 140
            return ("#FFFFFF", "#E2E8F0") if dark else ("#1F2937", "#4B5563")

        top_h, bot_y = y, y + card_h
        bot_h = H - bot_y
        if top_h >= 120 and kit is not None and kit.brand_name:
            main, sub = ink((0, 0, W, top_h))
            name = kit.brand_name
            f1 = display_font(46, name)
            tag = kit.tagline or ""
            f2 = korean_font(28, "semibold")
            while tag and f2.getlength(tag) > W - 160 and len(tag) > 4:
                tag = tag[:-2].rstrip() + "…"
            cy0 = top_h // 2 - (20 if tag else 0)
            d.text((W // 2, cy0), name, font=f1, fill=main, anchor="mm")
            if tag:
                d.text((W // 2, cy0 + 52), tag, font=f2, fill=sub, anchor="mm")
        if bot_h >= 120:
            main, sub = ink((0, bot_y, W, H))
            parts = []
            if kit is not None and (el is None or el.show_phone) and kit.phone:
                parts.append(f"상담 {kit.phone}")
            if kit is not None and (el is None or el.show_homepage) and kit.homepage:
                parts.append(kit.homepage_short)
            contact = "  |  ".join(parts)
            room = bot_h - (64 if contact else 24)
            cap = (scene.display_caption or "").strip()
            lines, font = [], None
            for size in (50, 44, 38, 32):
                font = display_font(size, cap)
                lines = wrap_text_px(cap, font, W - 160)
                if len(lines) * (size + 14) <= room and len(lines) <= 3:
                    break
            lines = lines[:3]
            if cap and lines:
                lh = font.size + 14 if hasattr(font, "size") else 58
                ty = bot_y + 20 + (room - lh * len(lines)) // 2 + lh // 2
                for ln in lines:
                    d.text((W // 2, ty), ln, font=font, fill=main, anchor="mm")
                    ty += lh
            if contact:
                size = 30
                while display_font(size, contact).getlength(contact) > W - 160 and size > 20:
                    size -= 2
                d.text((W // 2, H - 44), contact, font=display_font(size, contact), fill=sub, anchor="mm")

    CARD_MOTIONS = {  # 카드 모양 쇼츠의 화면 전체 움직임: (시작 확대, 끝 확대, 시작 x, 끝 x, 시작 y, 끝 y)
        "zoom_in": (1.0, 1.06, 0.5, 0.5, 0.5, 0.5),
        "zoom_out": (1.06, 1.0, 0.5, 0.5, 0.5, 0.5),
        "dyn0": (1.0, 1.07, 0.35, 0.65, 0.55, 0.45),
        "dyn1": (1.07, 1.0, 0.65, 0.35, 0.45, 0.55),
    }

    async def _card_scene_segment(self, bg_path: str, card_path: str, cy: int, frames: int, out: str, motion: str, n: int,
                                  text_motion: bool, delay: float = 0.0) -> None:
        """카드 한 장 → `frames`장짜리 H.264 조각. 카드는 바탕 위에 떠올라 나타나고(text_motion), 화면 전체가 천천히 확대·축소·이동한다(motion)."""
        W, H, fps = self.WIDTH, self.HEIGHT, self.FPS
        inputs = ["-loop", "1", "-framerate", str(fps), "-i", bg_path, "-loop", "1", "-framerate", str(fps), "-i", card_path]
        chains = []
        if text_motion:
            d_sec, px = self.TEXT_SLIDE_SEC, self.TEXT_SLIDE_PX
            chains.append(f"[1:v]format=rgba,fade=t=in:st={delay:.3f}:d={d_sec}:alpha=1[cd]")
            off = f"{px}*pow(clip(1-(t-{delay:.3f})/{d_sec},0,1),3)"
            chains.append(f"[0:v][cd]overlay=x=0:y='{cy}+{off}':eval=frame:shortest=1[c0]")
        else:
            chains.append(f"[0:v][1:v]overlay=x=0:y={cy}:shortest=1[c0]")
        if motion != "none":
            key = {"zoom_in": "zoom_in", "zoom_out": "zoom_out", "alternate": "zoom_in" if n % 2 == 0 else "zoom_out",
                   "dynamic": f"dyn{n % 2}"}.get(motion, "zoom_in" if n % 2 == 0 else "zoom_out")
            z0, z1, x0, x1, y0, y1 = self.CARD_MOTIONS[key]
            p = f"(on/{max(1, frames - 1)})"
            e = f"({p}*{p}*(3-2*{p}))"
            chains.append(f"[c0]scale={W * 2}:{H * 2},zoompan=z='{z0}+({z1 - z0:.4f})*{e}':"
                          f"x='(iw-iw/zoom)*({x0}+({x1 - x0:.4f})*{e})':y='(ih-ih/zoom)*({y0}+({y1 - y0:.4f})*{e})':"
                          f"d=1:s={W}x{H}:fps={fps},setsar=1[c1]")
            cur = "c1"
        else:
            cur = "c0"
        chains.append(f"[{cur}]setsar=1,format=yuv420p[v]")
        cmd = [ffmpeg_tools.ffmpeg(), "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains), "-map", "[v]",
               "-frames:v", str(frames), "-pix_fmt", "yuv420p", *ffmpeg_tools.h264_args("good", "veryfast"), "-r", str(fps), out]
        await self._run(cmd, "카드 움직임 조각 생성 실패")

    async def _tri_scene_segment(self, frame_path: str, frames: int, out: str, zone, photo_moves: bool, motion: str,
                                 text_motion: bool, delay: float = 0.0, tag: str = "", work_dir: str = "") -> None:
        """3단 프레임 한 장 → `frames`장짜리 H.264 조각. 가운데 사진 칸은 `motion`대로 움직이고(photo_moves일 때),
        text_motion이면 위 제목·아래 글자가 미끄러지며 나타난다. 둘 다 아니면 정지 화면."""
        W, fps = self.WIDTH, self.FPS
        m0, m1 = zone
        zh = m1 - m0
        src, layers = frame_path, []
        if text_motion:
            src, layers = self._split_text_layers(frame_path, zone, work_dir or os.path.dirname(out), tag or "x")
        inputs = ["-loop", "1", "-framerate", str(fps), "-i", src]
        for lpath, _, _ in layers:
            inputs += ["-loop", "1", "-framerate", str(fps), "-i", lpath]
        chains = []
        if photo_moves:
            z, x, y = self._zone_motion_expr(motion, frames)
            # 같은 크기로 크게 키운 뒤 움직여야 정수 좌표 떨림이 줄고, d=1은 입력 프레임마다 한 장씩 내보내라는 뜻이다.
            chains.append(f"[0:v]split[a][b];[b]crop={W}:{zh}:0:{m0},scale={W * 2}:{zh * 2},"
                          f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{zh}:fps={fps},setsar=1[z];[a][z]overlay=0:{m0}[c0]")
        else:
            chains.append("[0:v]null[c0]")
        cur = "c0"
        d_sec, px = self.TEXT_SLIDE_SEC, self.TEXT_SLIDE_PX
        for i, (_, y0, sign) in enumerate(layers, start=1):
            st = delay + 0.12 * (i - 1)
            chains.append(f"[{i}:v]format=rgba,fade=t=in:st={st:.3f}:d={d_sec}:alpha=1[t{i}]")
            off = f"{sign * px}*pow(clip(1-(t-{st:.3f})/{d_sec},0,1),3)"
            chains.append(f"[{cur}][t{i}]overlay=x=0:y='{y0}+{off}':eval=frame:shortest=1[c{i}]")
            cur = f"c{i}"
        chains.append(f"[{cur}]setsar=1,format=yuv420p[v]")
        cmd = [ffmpeg_tools.ffmpeg(), "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains), "-map", "[v]",
               "-frames:v", str(frames), "-pix_fmt", "yuv420p", *ffmpeg_tools.h264_args("good", "veryfast"), "-r", str(fps), out]
        await self._run(cmd, "사진·글자 움직임 조각 생성 실패")

    async def _xfade_segments(self, segments: List[Tuple[str, int]], half: int, work_dir: str):
        """장면 조각들을 전환 효과(xfade)로 이어 붙여 영상 입력 인자를 돌려준다. 실패하면 None."""
        fps, n = self.FPS, len(segments)
        track = os.path.join(work_dir, "tri_track.mp4")
        inputs, chains = [], []
        for i, (seg, _) in enumerate(segments):
            inputs += ["-i", seg]
            chains.append(f"[{i}:v]fps={fps},settb=AVTB,format=yuv420p[s{i}]")
        prev, out_frames, dur = "s0", segments[0][1], 2 * half / fps
        for i in range(1, n):
            offset = (out_frames - 2 * half) / fps
            trans = self.TRI_TRANSITIONS[(i - 1) % len(self.TRI_TRANSITIONS)]
            chains.append(f"[{prev}][s{i}]xfade=transition={trans}:duration={dur:.4f}:offset={offset:.4f}[x{i}]")
            out_frames += segments[i][1] - 2 * half
            prev = f"x{i}"
        cmd = [ffmpeg_tools.ffmpeg(), "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains), "-map", f"[{prev}]",
               "-frames:v", str(out_frames), "-pix_fmt", "yuv420p", *ffmpeg_tools.h264_args("good", "veryfast"), "-r", str(fps), track]
        try:
            await self._run(cmd, "장면 전환 합성 실패")
        except RuntimeError as ex:
            logging.getLogger(__name__).warning(f"{ex} → 전환 없이 연결")
            self.last_warnings.append("장면 전환 효과를 넣지 못해 생략했습니다.")
            return None
        return ["-i", track]

    async def _trim_concat(self, segments: List[Tuple[str, int]], half: int, work_dir: str):
        """전환을 못 넣을 때: 겹친 앞뒤를 잘라 내 길이를 맞춰 이어 붙인 영상 입력 인자(실패하면 None)."""
        fps, n = self.FPS, len(segments)
        parts = []
        try:
            for i, (seg, nf) in enumerate(segments):
                lead = half if i > 0 else 0
                keep = nf - lead - (half if i < n - 1 else 0)
                t_seg = os.path.join(work_dir, f"trim_{i:02d}.mp4")
                await self._run([ffmpeg_tools.ffmpeg(), "-y", "-v", "error", "-i", seg, "-vf",
                                 f"trim=start_frame={lead}:end_frame={lead + keep},setpts=PTS-STARTPTS", "-r", str(fps),
                                 *ffmpeg_tools.h264_args("good", "veryfast"), t_seg], "세그먼트 정리 실패")
                parts.append(t_seg)
            concat = os.path.join(work_dir, "trim.ffconcat")
            with open(concat, "w", encoding="utf-8") as f:
                f.write("ffconcat version 1.0\n" + "".join(f"file '{os.path.basename(x)}'\n" for x in parts))
            return ["-f", "concat", "-safe", "0", "-i", concat]
        except RuntimeError:
            return None

    # ------------------------------------------------------------------
    # 1. 음성 합성 (씬 단위)
    # ------------------------------------------------------------------
    def _free_tts_scene(self, text: str, out_base: str, est_duration: float) -> Tuple[str, str]:
        """(오디오 경로, 사용 엔진) — 무료 gTTS(인터넷 필요) → 무음 순으로 시도"""
        try:
            from gtts import gTTS
            mp3 = out_base + ".mp3"
            gTTS(text=text, lang="ko", slow=False).save(mp3)
            if os.path.getsize(mp3) > 0:
                return mp3, "gtts"
        except Exception as e:
            logging.getLogger(__name__).warning(f"{e}")
        wav = out_base + ".wav"
        subprocess.run([ffmpeg_tools.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                        "-t", f"{est_duration:.2f}", wav], check=True, **ffmpeg_tools.no_window())
        return wav, "silent"

    def _silent_scenes(self, scenes: List[ShortsScene], work_dir: str) -> List[str]:
        """장면마다 예상 길이(대본 글자 수 기준)만큼의 무음 파일. 움직임·전환 효과를 보려는 테스트용입니다."""
        outs = []
        for i, scene in enumerate(scenes):
            wav = os.path.join(work_dir, f"scene_{i:02d}.wav")
            subprocess.run([ffmpeg_tools.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                            "-t", f"{max(1.0, scene.duration_seconds):.2f}", wav], check=True,
                           **ffmpeg_tools.no_window())
            outs.append(wav)
        self.last_tts_engine = "테스트 전용 무음"
        self.last_warnings.append("테스트 전용: 음성 없이 만든 무음 영상입니다.")
        return outs

    async def _gemini_tts(self, scenes: List[ShortsScene], work_dir: str) -> Optional[List[str]]:
        """Gemini TTS로 전체 씬 합성. 못 쓰거나 실패하면 None (호출 측이 전체를 무료 음성으로 대체해 목소리가 섞이지 않게 함)"""
        from cards.tts import GeminiTTS, TtsUnavailable
        opts = self.options
        if opts.voice == "free":
            return None
        outs = [os.path.join(work_dir, f"scene_{i:02d}.wav") for i in range(len(scenes))]
        try:
            tts = GeminiTTS(opts.voice, os.path.join(self.export_dir, "tts_cache"), call=opts.tts_call)
            reused = await tts.synthesize_all([s.narration_script.strip() for s in scenes], outs)
        except TtsUnavailable as e:
            self.last_warnings.append(f"{e} → 무료 음성으로 대체했습니다.")
            return None
        except Exception as e:
            logging.getLogger(__name__).warning(f"Gemini TTS 실패: {e}")
            self.last_warnings.append(f"Gemini 음성 합성 실패 → 무료 음성으로 대체했습니다 ({type(e).__name__})")
            return None
        self.last_warnings += tts.warnings
        self.last_tts_engine = f"Gemini TTS · {tts.voice} ({tts.model['model_id']})" + (f" · 캐시 {reused}개 재사용" if reused else "")
        return outs

    async def _synthesize_scenes(self, scenes: List[ShortsScene], work_dir: str, audio_path: str, tone: str = ""):
        timeline: List[Dict[str, Any]] = []
        if self.options.voice == "silent":     # 테스트 전용: 음성 합성·인터넷·사용 기록 없이 장면 길이만큼 무음
            files = await asyncio.to_thread(self._silent_scenes, scenes, work_dir)
        else:
            files = await self._gemini_tts(scenes, work_dir)
        if files is None:
            engines, files = set(), []
            for i, scene in enumerate(scenes):
                path, engine = await asyncio.to_thread(
                    self._free_tts_scene, scene.narration_script.strip(), os.path.join(work_dir, f"scene_{i:02d}"),
                    max(1.0, scene.duration_seconds))
                engines.add(engine)
                files.append(path)
            self.last_tts_engine = ", ".join(sorted(engines))
            if "silent" in engines:
                self.last_warnings.append("음성 합성 실패 구간은 무음 처리됨")
            elif "gtts" in engines:
                self.last_warnings.append("무료 음성(gTTS)을 썼습니다 — 인터넷이 필요하고 품질이 낮습니다")
        for scene, path in zip(scenes, files):
            dur = await self._get_audio_duration(path)
            timeline.append({"scene": scene, "speech": dur if dur > 0 else max(1.0, scene.duration_seconds)})

        # 씬 오디오 이어붙이기 (씬 사이 SCENE_GAP초 여백)
        inputs, filters = [], []
        for idx, f in enumerate(files):
            inputs += ["-i", f]
            pad = f",apad=pad_dur={SCENE_GAP}" if idx < len(files) - 1 else ""
            filters.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo{pad}[a{idx}]")
        concat = "".join(f"[a{i}]" for i in range(len(files))) + f"concat=n={len(files)}:v=0:a=1[out]"
        cmd = [ffmpeg_tools.ffmpeg(), "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters + [concat]),
               "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "192k", audio_path]
        await self._run(cmd, "내레이션 오디오 결합 실패")

        t = 0.0
        for idx, item in enumerate(timeline):
            item["start"] = t
            item["end"] = t + item["speech"] + (SCENE_GAP if idx < len(timeline) - 1 else 0.0)
            t = item["end"]
        total = await self._get_audio_duration(audio_path)
        return timeline, max(total, t)

    async def _get_audio_duration(self, path: str) -> float:
        proc = await asyncio.create_subprocess_exec(
            ffmpeg_tools.ffprobe(), "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **ffmpeg_tools.no_window(),
        )
        stdout, _ = await proc.communicate()
        try:
            return float(stdout.decode().strip())
        except ValueError:
            return 0.0

    # ------------------------------------------------------------------
    # 2. 자막 이벤트 (단어별 하이라이트)
    # ------------------------------------------------------------------
    def _build_caption_events(self, timeline: List[Dict[str, Any]], total: float) -> List[Dict[str, Any]]:
        """씬마다 실제 음성 길이 안에서 글자 수(+문장부호 쉼) 비례로 단어 시간을 배분"""
        events: List[Dict[str, Any]] = []
        for s_idx, item in enumerate(timeline):
            words = item["scene"].narration_script.split()
            weights = []
            for w in words:
                weight = max(1, len(re.sub(r"[^\w]", "", w)))
                if re.search(r"[.!?]$", w):
                    weight += 2
                elif re.search(r"[,，]$", w):
                    weight += 1
                weights.append(weight)
            unit = item["speech"] / max(1, sum(weights))
            starts, t = [], item["start"]
            for wgt in weights:
                starts.append(t)
                t += wgt * unit

            groups = self._group_words(words)
            pos = 0
            for group in groups:
                for g_idx in range(len(group)):
                    w_idx = pos + g_idx
                    start = starts[w_idx]
                    end = starts[w_idx + 1] if w_idx + 1 < len(words) else item["end"]
                    events.append({"scene_index": s_idx, "words": group, "active": g_idx,
                                   "start": round(start, 3), "end": round(end, 3)})
                pos += len(group)
        if events:
            events[-1]["end"] = max(events[-1]["end"], total)
        return events

    def _group_words(self, words: List[str]) -> List[List[str]]:
        """한 화면 자막이 2줄을 넘지 않도록 최대 3단어씩 묶기"""
        font = korean_font(72, "bold")
        groups, curr = [], []
        for w in words:
            trial = curr + [w]
            if curr and (len(trial) > 3 or len(wrap_text_px(" ".join(trial), font, 900)) > 2):
                groups.append(curr)
                curr = [w]
            else:
                curr = trial
        if curr:
            groups.append(curr)
        return groups

    def _format_ass_time(self, seconds: float) -> str:
        cs_total = int(round(seconds * 100))
        hrs, rem = divmod(cs_total, 360000)
        mins, rem = divmod(rem, 6000)
        secs, cs = divmod(rem, 100)
        return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"

    def _build_karaoke_ass_file(self, events: List[Dict[str, Any]], output_ass_path: Path):
        """편집 툴(Premiere/CapCut 등)용 ASS 사이드카 자막. 색상: &HAABBGGRR"""
        ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Apple SD Gothic Neo,72,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,3,2,80,80,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = []
        for ev in events:
            parts = []
            for i, w in enumerate(ev["words"]):
                clean = w.replace("{", "").replace("}", "")
                parts.append(f"{{\\c&H0000FFFF&}}{clean}{{\\r}}" if i == ev["active"] else clean)
            lines.append(f"Dialogue: 0,{self._format_ass_time(ev['start'])},{self._format_ass_time(ev['end'])},Default,,0,0,0,,{' '.join(parts)}")
        output_ass_path.write_text(ass_header + "\n".join(lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # 3. 영상 트랙 (씬별: 첨부 동영상 구간 / 이미지 모션 / 브랜드 배경)
    # ------------------------------------------------------------------
    def _generate_vertical_background(self, output_path: str):
        """에셋이 없는 씬에 쓰는 브랜드 배경"""
        W, H = self.WIDTH, self.HEIGHT
        c = self.kit.colors
        img = Image.new("RGB", (W, H), "#0F172A")
        draw = ImageDraw.Draw(img)
        top, bottom = _rgb(c.primary), (15, 23, 42)
        for y in range(H):
            t = y / H
            draw.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
        deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d2 = ImageDraw.Draw(deco)
        d2.ellipse([-260, -200, 520, 580], fill=_rgb(c.secondary) + (60,))
        d2.ellipse([620, 1180, 1400, 1960], fill=_rgb(c.secondary) + (50,))
        d2.ellipse([700, 300, 1100, 700], fill=_rgb(c.accent) + (25,))
        img = Image.alpha_composite(img.convert("RGBA"), deco).convert("RGB")
        img.save(output_path, "PNG")

    def _vertical_frame(self, src: Image.Image) -> Image.Image:
        """임의 비율 이미지를 9:16으로: 세로에 가까우면 꽉 채워 자르고, 가로 사진은 흐린 배경 위에 원본 전체를 배치"""
        W, H = self.WIDTH, self.HEIGHT
        src = src.convert("RGB")
        if src.width / src.height <= 0.75:
            return ImageOps.fit(src, (W, H), method=Image.LANCZOS, centering=(0.5, 0.45))
        bg = ImageOps.fit(src, (W, H), method=Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
        bg = Image.blend(bg, Image.new("RGB", (W, H), "#0F172A"), 0.35)
        fg = src.copy()
        fg.thumbnail((W, H), Image.LANCZOS)
        if fg.width < W:
            fg = fg.resize((W, int(fg.height * W / fg.width)), Image.LANCZOS)
        bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
        return bg

    # 씬 순서대로 돌아가며 쓰는 카메라 움직임 / 장면 전환 (같은 효과가 연속되지 않도록)
    MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_up", "pan_left", "diag"]
    TRANSITIONS = ["zoomin", "smoothleft", "circleopen", "slideup", "fadewhite", "smoothup", "radial"]
    TRANSITION_SEC = 0.4

    async def _build_video_track(self, sb: EditableStoryboard, timeline: List[Dict[str, Any]], work_dir: str, bg_path: str):
        """씬별 세그먼트를 만들고 장면 전환(xfade)으로 이어 붙인 무음 영상 트랙 1개를 반환.

        전환 구간은 씬 경계를 중심으로 앞뒤 씬이 겹치도록 세그먼트를 조금씩 길게 만들어,
        전체 길이와 씬 경계 시각이 내레이션 오디오와 프레임 단위로 일치하도록 한다.
        """
        fps = self.FPS
        n = len(timeline)
        half = max(1, round(self.TRANSITION_SEC * fps / 2))
        segments, flags = [], []
        for i, item in enumerate(timeline):
            b, e = round(item["start"] * fps), round(item["end"] * fps)
            lead = half if i > 0 else 0
            tail = half if i < n - 1 else 0
            frames = max(1, (e + tail) - (b - lead))
            seg = os.path.join(work_dir, f"seg_{i:02d}.mp4")
            scene = item["scene"]
            asset: Optional[MediaAsset] = sb.asset(scene.asset_id)
            clip_start = scene.clip_start
            override = (self.options.video_overrides or {}).get(sb.shorts_scenes.index(scene))
            if override is not None and os.path.exists(override.path):
                asset, clip_start = override, 0.0  # AI 영상으로 이 장면 배경만 교체
            used_media = False
            if asset and asset.kind == "video" and os.path.exists(asset.path):
                try:
                    await self._video_segment(asset, clip_start - lead / fps, frames, seg, punch=(i == 0))
                    used_media = True
                except RuntimeError as ex:
                    self.last_warnings.append(f"씬 {i + 1} 영상 처리 실패 → 배경 대체")
                    logging.getLogger(__name__).warning(f"{ex}")
            elif asset and asset.kind == "image" and os.path.exists(asset.path):
                still = os.path.join(work_dir, f"still_{i:02d}.png")
                with Image.open(asset.path) as im:
                    await asyncio.to_thread(lambda: self._vertical_frame(ImageOps.exif_transpose(im)).save(still))
                await self._still_segment(still, frames, seg, "punch" if i == 0 else self.MOTIONS[i % len(self.MOTIONS)])
                used_media = True
            if not used_media:
                await self._still_segment(bg_path, frames, seg, "punch" if i == 0 else "zoom_in")
            segments.append((seg, frames))
            flags.append(used_media)

        track = os.path.join(work_dir, "video_track.mp4")
        if n == 1:
            os.replace(segments[0][0], track)
            return track, flags

        # xfade 체인: 각 전환은 다음 씬 세그먼트가 시작되는 시점(= 씬 경계 - 전환길이/2)에 시작
        inputs, chains = [], []
        for i, (seg, _) in enumerate(segments):
            inputs += ["-i", seg]
            chains.append(f"[{i}:v]fps={fps},settb=AVTB,format=yuv420p[s{i}]")
        prev, out_frames = "s0", segments[0][1]
        dur = 2 * half / fps
        for i in range(1, n):
            offset = (out_frames - 2 * half) / fps
            label = f"x{i}"
            trans = self.TRANSITIONS[(i - 1) % len(self.TRANSITIONS)]
            chains.append(f"[{prev}][s{i}]xfade=transition={trans}:duration={dur:.4f}:offset={offset:.4f}[{label}]")
            out_frames += segments[i][1] - 2 * half
            prev = label
        cmd = [ffmpeg_tools.ffmpeg(), "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains), "-map", f"[{prev}]",
               "-frames:v", str(out_frames), *ffmpeg_tools.h264_args("high", "veryfast"), "-r", str(fps), track]
        try:
            await self._run(cmd, "장면 전환 합성 실패")
        except RuntimeError as ex:
            # 전환 합성이 실패해도 영상은 만들어지도록 겹침 없이 단순 연결 (전환만 생략)
            logging.getLogger(__name__).warning(f"{ex} → 전환 없이 연결")
            self.last_warnings.append("장면 전환 효과 생략")
            trimmed = []
            for i, (seg, frames) in enumerate(segments):
                lead = half if i > 0 else 0
                keep = frames - lead - (half if i < n - 1 else 0)
                t_seg = os.path.join(work_dir, f"trim_{i:02d}.mp4")
                await self._run([ffmpeg_tools.ffmpeg(), "-y", "-v", "error", "-i", seg, "-vf", f"trim=start_frame={lead}:end_frame={lead + keep},setpts=PTS-STARTPTS",
                                 *ffmpeg_tools.h264_args("high", "veryfast"), t_seg], "세그먼트 정리 실패")
                trimmed.append(t_seg)
            concat = os.path.join(work_dir, "video.ffconcat")
            with open(concat, "w", encoding="utf-8") as f:
                f.write("ffconcat version 1.0\n" + "".join(f"file '{os.path.basename(x)}'\n" for x in trimmed))
            await self._run([ffmpeg_tools.ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", concat, "-c", "copy", track], "영상 연결 실패")
        return track, flags

    async def _video_segment(self, asset: MediaAsset, clip_start: float, frames: int, out: str, punch: bool = False):
        W, H, fps = self.WIDTH, self.HEIGHT, self.FPS
        need = frames / fps
        start = max(0.0, min(clip_start, max(0.0, asset.duration - 0.5)))
        loop = start + need > asset.duration
        if asset.width / max(1, asset.height) <= 0.75:
            vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        else:
            # 가로 영상: 흐린 확대 배경 + 원본 전체 (블러 패딩)
            vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                  f"boxblur=24:3,eq=brightness=-0.12[bg];[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
        if punch:
            # 오프닝: 처음 0.5초 동안 확대 상태에서 빠르게 제자리로 (펀치 줌)
            pz = f"if(lt(t\\,0.5)\\,1.18-0.36*t\\,1)"
            vf += f",scale=w='trunc(iw*{pz}/2)*2':h='trunc(ih*{pz}/2)*2':eval=frame,crop={W}:{H}"
        cmd = [ffmpeg_tools.ffmpeg(), "-y", "-v", "error"]
        if loop:
            cmd += ["-stream_loop", "-1"]  # 클립이 씬보다 짧으면 반복
        cmd += ["-ss", f"{start:.2f}", "-i", asset.path,
                "-filter_complex", f"[0:v]{vf},fps={fps},setsar=1,format=yuv420p[v]", "-map", "[v]", "-an",
                "-frames:v", str(frames), *ffmpeg_tools.h264_args("high", "veryfast"), out]
        await self._run(cmd, f"{asset.id} 영상 세그먼트 생성 실패")

    def _motion_expr(self, motion: str, frames: int) -> Tuple[str, str, str]:
        """zoompan용 (zoom, x, y) 식. on = 출력 프레임 번호"""
        N = max(1, frames - 1)
        cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        p = f"(on/{N})"
        if motion == "punch":
            P = min(15, N)  # 0.5초
            z = f"if(lt(on\\,{P})\\,1.28-0.20*on/{P}\\,1.08+0.05*(on-{P})/{max(1, N - P)})"
            return z, cx, cy
        if motion == "zoom_out":
            return f"1.14-0.12*{p}", cx, cy
        if motion == "pan_right":
            return "1.15", f"(iw-iw/zoom)*{p}", cy
        if motion == "pan_left":
            return "1.15", f"(iw-iw/zoom)*(1-{p})", cy
        if motion == "pan_up":
            return "1.15", cx, f"(ih-ih/zoom)*(1-{p})"
        if motion == "diag":
            return f"1.08+0.08*{p}", f"(iw-iw/zoom)*{p}", f"(ih-ih/zoom)*{p}"
        return f"1.02+0.12*{p}", cx, cy  # zoom_in

    async def _still_segment(self, image_path: str, frames: int, out: str, motion: str = "zoom_in"):
        """정지 이미지 → 카메라 무브(줌인/줌아웃/팬/대각선/펀치) 세그먼트"""
        W, H, fps = self.WIDTH, self.HEIGHT, self.FPS
        z, x, y = self._motion_expr(motion, frames)
        # 큰 해상도에서 움직여야 팬/줌의 정수 좌표 떨림이 줄어듦
        vf = (f"scale={int(W * 1.5)}:{int(H * 1.5)},"
              f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={fps},"
              "setsar=1,format=yuv420p")
        cmd = [ffmpeg_tools.ffmpeg(), "-y", "-v", "error", "-i", image_path, "-vf", vf, "-frames:v", str(frames),
               *ffmpeg_tools.h264_args("high", "veryfast"), out]
        await self._run(cmd, "이미지 모션 세그먼트 생성 실패")

    # ------------------------------------------------------------------
    # 4. 오버레이 (타이틀·씬 문구·자막·CTA)
    # ------------------------------------------------------------------
    def _static_layer(self, title: str) -> Image.Image:
        """영상 위에 얹히는 고정 요소: 상·하단 가독성 그라데이션, 로고·타이틀, CTA 바"""
        W, H = self.WIDTH, self.HEIGHT
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for y in range(0, 560):
            d.line([(0, y), (W, y)], fill=(0, 15, 45, int(200 * (1 - y / 560) ** 1.3)))
        for y in range(1280, H):
            d.line([(0, y), (W, y)], fill=(0, 10, 30, int(215 * ((y - 1280) / (H - 1280)) ** 0.9)))

        kit, el, c = self.kit, self.elements, self.kit.colors
        if el is None or el.logo != "none":
            if kit.logo_path:  # 로고 이미지: 흰 배경판 위에
                with Image.open(kit.logo_path) as im:
                    logo = im.convert("RGBA")
                lh = 56
                lw = min(320, int(logo.width * lh / max(1, logo.height)))
                logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
                plate = Image.new("RGBA", (lw + 28, logo.height + 20), (255, 255, 255, 235))
                layer.paste(plate, (80, 132 - plate.height // 2), plate)
                layer.alpha_composite(logo, (94, 132 - logo.height // 2))
            else:
                f_logo = display_font(30, kit.brand_name)
                lw = int(f_logo.getlength(kit.brand_name)) + 48
                d.rounded_rectangle([80, 100, 80 + lw, 164], radius=14, fill=c.primary, outline=c.secondary, width=2)
                d.text((80 + lw // 2, 132), kit.brand_name, font=f_logo, fill="#FFFFFF", anchor="mm")
        if kit.tagline:
            f_tag = korean_font(26, "semibold")
            tag = kit.tagline
            while f_tag.getlength(tag) > 560 and len(tag) > 4:
                tag = tag[:-2].rstrip() + "…"
            d.text((W - 80, 132), tag, font=f_tag, fill="#E2E8F0", anchor="rm")
        f_title = display_font(46, title)
        y = 200
        for line in wrap_text_px(title, f_title, W - 160)[:2]:
            d.text((80, y), line, font=f_title, fill="#FFFFFF", stroke_width=3, stroke_fill=(0, 20, 60, 200))
            y += 58

        parts = []
        if (el is None or el.show_phone) and kit.phone:
            parts.append(f"상담 {kit.phone}")
        if (el is None or el.show_homepage) and kit.homepage:
            parts.append(kit.homepage_short)
        if el is not None and el.show_sns and kit.sns_handle:
            parts.append(kit.sns_handle)
        if parts:
            cta = "  |  ".join(parts)
            size = 36
            while display_font(size, cta).getlength(cta) > W - 220 and size > 22:
                size -= 2
            d.rounded_rectangle([80, 1720, W - 80, 1840], radius=20, fill=c.secondary)
            d.text((W // 2, 1780), cta, font=display_font(size, cta), fill="#FFFFFF", anchor="mm")
        return layer

    INTRO_SEC = 0.9      # 씬 문구 등장 애니메이션 길이
    INTRO_STEP = 1 / 20  # 애니메이션 프레임 간격 (20fps로 그려도 충분히 부드러움)
    NUMBER_RE = re.compile(r"(?<![\d\-.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\d\-])")

    def _scene_base_layer(self, scene: ShortsScene, index: int, total: int, has_media: bool) -> Image.Image:
        """씬마다 고정인 요소: 구간 라벨, 씬 번호, (에셋 없는 씬) 어두운 카드"""
        W = self.WIDTH
        layer = Image.new("RGBA", (W, self.HEIGHT), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        label = self.SECTION_LABELS.get(scene.section_type, "핵심 포인트")
        f_label = display_font(28, label)
        lw = int(f_label.getlength(label)) + 48
        if has_media:
            d.rounded_rectangle([80, 340, 80 + lw, 394], radius=27, fill=self.kit.colors.accent)
            d.text((80 + lw / 2, 367), label, font=f_label, fill="#0F172A", anchor="mm")
            d.text((W - 80, 367), f"{index + 1} / {total}", font=korean_font(28, "semibold"), fill="#E2E8F0", anchor="rm")
        else:
            d.rounded_rectangle((80, 450, W - 80, 1300), radius=32, fill=(15, 23, 42, 205), outline=(51, 65, 85, 255), width=2)
            d.rounded_rectangle([130, 500, 130 + lw, 556], radius=28, fill=self.kit.colors.accent)
            d.text((130 + lw / 2, 528), label, font=f_label, fill="#0F172A", anchor="mm")
            d.text((W - 130, 528), f"{index + 1} / {total}", font=korean_font(28, "semibold"), fill="#94A3B8", anchor="rm")
        return layer

    def _count_up(self, text: str, frac: float) -> str:
        """문구 속 숫자를 0 → 원래 값으로 증가시키며 표시 (전화번호·소수점 자리수·천단위 쉼표 유지)"""
        def repl(m):
            int_part, dec_part = m.group(1), m.group(2) or ""
            value = float(int_part.replace(",", "") + dec_part)
            cur = value * frac
            decimals = len(dec_part) - 1 if dec_part else 0
            out = f"{cur:,.{decimals}f}" if "," in int_part else f"{cur:.{decimals}f}"
            return out
        return self.NUMBER_RE.sub(repl, text)

    # ------------------------------------------------------------------
    # 문구 스타일 분기: basic(팝업) / kinetic(키네틱 타이포)
    # ------------------------------------------------------------------
    def _anim_len(self, scene: ShortsScene, has_media: bool, title: str) -> float:
        if self.options.caption_style != "kinetic":
            return self.INTRO_SEC
        if self._big_numbers(scene):
            return 1.6
        n = len((scene.display_caption or "").split())
        return min(2.6, 0.08 + 0.09 * max(0, n - 1) + 0.3 + 0.5)

    def _scene_caption(self, scene: ShortsScene, has_media: bool, title: str, t_rel: float) -> Optional[Image.Image]:
        if self.options.caption_style == "kinetic":
            return self._kinetic_layer(scene, has_media, title, t_rel)
        return self._caption_layer(scene, has_media, title, t_rel / self.INTRO_SEC)

    @staticmethod
    def _ease_out(p: float) -> float:
        p = max(0.0, min(1.0, p))
        return 1 - (1 - p) ** 3

    # 순서·기간·날짜처럼 '한 덩어리로 읽혀야 하는' 표현 (카운트업하지 않고 그대로 보여 줌)
    COMPOSITE_RE = re.compile(r"\d+\s*박\s*\d+\s*일|\d+\s*번째|\d+\s*월\s*\d+\s*일|\d+\s*[~\-]\s*\d+\s*(?:박|일|분|시간)")
    COUNT_UNIT_RE = re.compile(r"\d\s*(?:%|퍼센트|원|명|점|배|억|만|천|개|곳|분|시간|위|건|회|kg|km)")

    @classmethod
    def _count_ok(cls, token: str) -> bool:
        """성과·수량 숫자(%, 원, 명, 점 …)만 0에서 올라가는 카운트업 대상. 순서(번째)·기간(박·일)·날짜는 제외"""
        return bool(cls.COUNT_UNIT_RE.search(token)) and not cls.COMPOSITE_RE.search(token)

    def _big_numbers(self, scene: ShortsScene) -> List[str]:
        """'대형 숫자 장면' 대상. 마무리 씬은 제외. 2박3일·3번째 같은 표현은 한 덩어리로, 전화번호는 제외"""
        if scene.section_type == "conclusion":
            return []
        m = self.COMPOSITE_RE.search(scene.display_caption or "")
        if m:
            return [m.group(0).strip()]
        nums = [w for w in (scene.emphasis_words or [])
                if re.search(r"\d", w) and not re.fullmatch(r"\d{4}-\d{4}", w.strip())][:2]
        if len(nums) == 2 and not all(self._count_ok(n) for n in nums):
            nums = nums[:1]  # 두 숫자를 화살표로 잇는 '전 → 후' 연출은 둘 다 수량일 때만
        return nums

    def _word_image(self, text: str, size: int, color: str) -> Image.Image:
        key = (text, size, color)
        cache = self.__dict__.setdefault("_word_cache", {})
        if key not in cache:
            font = display_font(size, text)
            stroke = max(3, size // 14)
            l, t, r, b = font.getbbox(text, stroke_width=stroke)
            img = Image.new("RGBA", (r - l + 4, b - t + 4), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((2 - l, 2 - t), text, font=font, fill=color, stroke_width=stroke, stroke_fill="#000000")
            cache[key] = (img, t - 2)  # (이미지, 글꼴 기준선 위쪽에서의 세로 오프셋)
        return cache[key]

    def _is_emphasis(self, token: str, scene: ShortsScene) -> bool:
        core = token.strip(".,!?·…\"'()")
        return any(core and (core in w or w in core) for w in (scene.emphasis_words or []) if w.strip())

    def _kinetic_layer(self, scene: ShortsScene, has_media: bool, title: str, t: float) -> Optional[Image.Image]:
        caption = scene.display_caption or ""
        if not caption:
            return None
        # 오프닝 문구가 상단 타이틀과 같으면(키네틱 모드) 화면 중앙에 크게 보여 주는 임팩트 장면으로 사용
        center = has_media and re.sub(r"\W", "", caption) == re.sub(r"\W", "", title)
        if center and scene.section_type != "hook":
            return None
        if self._big_numbers(scene):
            return self._big_number_layer(scene, t)

        W = self.WIDTH
        layer = Image.new("RGBA", (W, self.HEIGHT), (0, 0, 0, 0))
        base = 84 if center else (62 if has_media else 74)
        tokens = caption.split()
        sizes = [int(base * 1.8) if self._is_emphasis(tok, scene) else base for tok in tokens]
        max_w = W - 160
        # 강조 단어가 한 줄 폭을 넘으면 그 단어만 축소
        for i, tok in enumerate(tokens):
            while display_font(sizes[i], tok).getlength(tok) > max_w and sizes[i] > base:
                sizes[i] -= 6

        # 크기가 섞인 단어들을 줄 단위로 배치 (기준선 정렬)
        lines: List[List[int]] = [[]]
        width = 0.0
        for i, tok in enumerate(tokens):
            ww = display_font(sizes[i], tok).getlength(tok)
            gap = display_font(base).getlength(" ")
            if lines[-1] and width + gap + ww > max_w:
                lines.append([])
                width = 0.0
            width += (gap if lines[-1] else 0) + ww
            lines[-1].append(i)
        lines = lines[:4]
        line_hs = [int(max(sizes[i] for i in ln) * 1.18) for ln in lines]
        block_h = sum(line_hs)
        if center:
            y0 = 900 - block_h // 2
        else:
            y0 = 420 if has_media else (450 + 110 + 1300) // 2 - block_h // 2
        gap = display_font(base).getlength(" ")

        d = ImageDraw.Draw(layer)
        if has_media:
            # 문구 뒤 반투명 배경 (영상 위에서도 읽히도록), 첫 단어와 함께 서서히 나타남
            a = int(150 * min(1.0, t / 0.3))
            d.rounded_rectangle([56, y0 - 24, W - 56, y0 + block_h + 24], radius=26, fill=(5, 12, 35, a))

        word_idx = 0
        y = y0
        for ln, lh in zip(lines, line_hs):
            line_w = sum(display_font(sizes[i], tokens[i]).getlength(tokens[i]) for i in ln) + gap * (len(ln) - 1)
            x = 80.0 if has_media and not center else (W - line_w) / 2
            baseline = y + int(lh * 0.82)
            clip_bottom = y + lh + 6
            for i in ln:
                emph = self._is_emphasis(tokens[i], scene)
                img, top_off = self._word_image(tokens[i], sizes[i], "#FFD400" if emph else "#FFFFFF")
                start = 0.08 + 0.09 * word_idx
                p = (t - start) / 0.3
                word_idx += 1
                font = display_font(sizes[i], tokens[i])
                ascent = font.getmetrics()[0]
                final_y = int(baseline - ascent + top_off)
                ww = font.getlength(tokens[i])
                if emph:
                    # 형광펜: 단어가 나타난 뒤 왼쪽→오른쪽으로 칠해짐
                    mp = self._ease_out((t - start - 0.25) / 0.25)
                    if mp > 0:
                        hb_top = baseline - int(sizes[i] * 0.30)
                        d.rectangle([x - 6, hb_top, x - 6 + (ww + 12) * mp, baseline + int(sizes[i] * 0.10)],
                                    fill=(37, 99, 235, 210))
                if p > 0:
                    e = self._ease_out(p)
                    slam = center or scene.section_type == "hook"
                    dy = 0 if slam else int((1 - e) * lh * 0.95)
                    piece = img
                    if slam and p < 1.0:
                        # 오프닝은 큰 글자가 쾅 하고 내려앉듯 줄어들며 안착
                        k = 1 + 0.55 * (1 - e)
                        piece = img.resize((int(img.width * k), int(img.height * k)), Image.LANCZOS)
                    elif emph and 0 < p < 1.8:
                        # 강조 단어는 등장 직후 살짝 커졌다 돌아오는 팝
                        pop = 1 + 0.14 * max(0.0, 1 - abs(p - 1.1) / 0.6)
                        if pop > 1.001:
                            piece = img.resize((int(img.width * pop), int(img.height * pop)), Image.LANCZOS)
                    px = int(x - (piece.width - img.width) / 2)
                    py = final_y + dy - (piece.height - img.height) // 2
                    visible = clip_bottom - py
                    if visible > 0:
                        crop = piece.crop((0, 0, piece.width, min(piece.height, visible)))
                        if p < 0.4:
                            crop.putalpha(crop.getchannel("A").point(lambda v, f=p / 0.4: int(v * f)))
                        layer.alpha_composite(crop, (max(0, px), max(0, py)))
                x += ww + gap
            y += lh
        return layer

    def _big_number_layer(self, scene: ShortsScene, t: float) -> Image.Image:
        """대형 숫자 장면: 중앙 패널 + 작은 설명 + 거대한 숫자(카운트업), 숫자가 2개면 사이에 화살표"""
        W = self.WIDTH
        layer = Image.new("RGBA", (W, self.HEIGHT), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        nums = self._big_numbers(scene)
        appear = self._ease_out(t / 0.25)
        panel = (60, 560, W - 60, 1320)
        d.rounded_rectangle(panel, radius=36, fill=(5, 12, 35, int(205 * appear)))

        # 위쪽 작은 설명 (문구 전체). 큰 숫자와 같은 말이면 중복이므로 생략
        caption = scene.display_caption or ""
        dup = re.sub(r"\W", "", caption) == re.sub(r"\W", "", nums[0])
        small = display_font(44, caption)
        sy = panel[1] + 60 if not dup else panel[1] + 20
        for line in ([] if dup else wrap_text_px(caption, small, W - 220)[:2]):
            img, _ = self._word_image(line, 44, "#E2E8F0")
            if appear > 0:
                piece = img.copy()
                piece.putalpha(piece.getchannel("A").point(lambda v: int(v * appear)))
                layer.alpha_composite(piece, ((W - img.width) // 2, sy))
            sy += 60

        count = self._ease_out((t - 0.25) / 0.9)
        rows = []
        if len(nums) == 2:
            rows = [(nums[0], 120, "#CBD5E1", 0.25), ("↓", 90, "#FFD400", 0.55), (nums[1], 170, "#FFD400", 0.7)]
        else:
            rows = [(nums[0], 190, "#FFD400", 0.25)]
        total_h = sum(int(sz * 1.15) for _, sz, _, _ in rows)
        y = (sy + panel[3]) // 2 - total_h // 2
        for text, size, color, start in rows:
            if text != "↓" and self._count_ok(text):
                text = self._count_up(text, count) if count < 1 else text
            while display_font(size, text).getlength(text) > W - 220 and size > 60:
                size -= 8
            img, _ = self._word_image(text, size, color)
            p = (t - start) / 0.35
            if p > 0:
                e = self._ease_out(p)
                scale = 0.6 + 0.4 * e + 0.08 * max(0.0, 1 - abs(p - 1.0) / 0.5)
                piece = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
                if p < 0.5:
                    piece.putalpha(piece.getchannel("A").point(lambda v, f=p / 0.5: int(v * f)))
                cx, cy = W // 2, y + int(size * 1.15) // 2
                layer.alpha_composite(piece, (cx - piece.width // 2, max(0, cy - piece.height // 2)))
                if text != "↓" and not self._count_ok(text):
                    # 그대로 보여 주는 표현(2박3일 등): 글자 아래로 노란 밑줄이 좌→우로 그어짐
                    mp = self._ease_out((t - start - 0.3) / 0.35)
                    if mp > 0:
                        bw = int(img.width * 0.9)
                        d.rounded_rectangle([cx - bw // 2, cy + img.height // 2 + 6, cx - bw // 2 + int(bw * mp), cy + img.height // 2 + 20],
                                            radius=7, fill=(255, 212, 0, 230))
            y += int(size * 1.15)
        return layer

    def _caption_layer(self, scene: ShortsScene, has_media: bool, title: str, progress: float) -> Optional[Image.Image]:
        """씬 핵심 문구. progress<1 이면 팝업(확대+바운스) + 페이드인 + 아래→위 이동 + 숫자 카운트업"""
        caption = scene.display_caption or ""
        if not caption or (has_media and re.sub(r"\W", "", caption) == re.sub(r"\W", "", title)):
            return None  # 오프닝 문구가 상단 타이틀과 같으면 중복 표시 생략
        W = self.WIDTH
        ease = 1 - (1 - min(1.0, progress)) ** 3
        text = caption if progress >= 1 else self._count_up(caption, ease)
        layer = Image.new("RGBA", (W, self.HEIGHT), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        if has_media:
            font = display_font(58, caption)
            y = 420
            lines = wrap_text_px(text, font, W - 160)[:2]
            for line in lines:
                d.text((80, y), line, font=font, fill="#FFFFFF", stroke_width=5, stroke_fill="#000000")
                y += 72
        else:
            box = (80, 450, W - 80, 1300)
            size = 76
            while True:
                font = display_font(size, caption)
                final_lines = wrap_text_px(caption, font, box[2] - box[0] - 120)
                if len(final_lines) <= 4 or size <= 48:
                    break
                size -= 4
            lines = wrap_text_px(text, font, box[2] - box[0] - 120)[:4]
            lh = int(text_height(font) * 1.25)
            y = (box[1] + 110 + box[3]) // 2 - (lh * len(final_lines[:4])) // 2
            for line in lines:
                d.text((W // 2, y), line, font=font, fill="#FFFFFF", anchor="ma")
                y += lh
        if progress >= 1:
            return layer

        # 팝업 애니메이션: 0.7배 → 1.06배(오버슈트) → 1배, 투명 → 불투명, 40px 아래 → 제자리
        p = min(1.0, progress / 0.55)
        c1, c3 = 1.70158, 2.70158
        back = 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2  # easeOutBack
        scale = 0.7 + 0.3 * back
        alpha = min(1.0, progress / 0.25)
        dy = int(40 * (1 - min(1.0, p)))
        bbox = layer.getbbox()
        if not bbox:
            return layer
        piece = layer.crop(bbox)
        nw, nh = max(1, int(piece.width * scale)), max(1, int(piece.height * scale))
        piece = piece.resize((nw, nh), Image.LANCZOS)
        if alpha < 1:
            piece.putalpha(piece.getchannel("A").point(lambda a: int(a * alpha)))
        out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        out.paste(piece, (int(cx - nw / 2), int(cy - nh / 2 + dy)), piece)
        return out

    def _subtitle_layer(self, words: List[str], active: int) -> Image.Image:
        """노래방식 자막: 현재 발화 단어는 노란색 + 약간 크게, 나머지는 흰색 (검은 외곽선)"""
        W = self.WIDTH
        layer = Image.new("RGBA", (W, self.HEIGHT), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        font = korean_font(72, "bold")
        font_active = korean_font(82, "bold")
        space = font.getlength(" ")
        width_of = lambda i: (font_active if i == active else font).getlength(words[i])
        lines: List[List[int]] = [[]]
        width = 0.0
        for i in range(len(words)):
            ww = width_of(i)
            if lines[-1] and width + space + ww > 900:
                lines.append([])
                width = 0.0
            width += (space if lines[-1] else 0) + ww
            lines[-1].append(i)
        lh = int(text_height(font) * 1.2)
        ascent = font.getmetrics()[0]
        y = 1560 - (lh * len(lines)) // 2
        for line in lines:
            line_w = sum(width_of(i) for i in line) + space * (len(line) - 1)
            x = (W - line_w) / 2
            for i in line:
                is_active = i == active
                d.text((x, y + ascent), words[i], font=font_active if is_active else font, anchor="ls",
                       fill="#FFD400" if is_active else "#FFFFFF", stroke_width=6, stroke_fill="#000000")
                x += width_of(i) + space
            y += lh
        return layer

    def _render_overlay_sequence(self, title: str, timeline: List[Dict[str, Any]], events: List[Dict[str, Any]],
                                 total: float, work_dir: str, media_flags: List[bool]) -> str:
        """시점별 오버레이 PNG + FFmpeg concat 목록(지속시간 포함) 작성.

        자막 단어가 바뀌는 시점과 씬 문구 등장 애니메이션 프레임 시점을 합쳐 구간을 나누고,
        각 구간에 맞는 화면(고정 요소 + 씬 라벨 + 문구 애니메이션 + 자막)을 한 장씩 그린다.
        """
        static = self._static_layer(title)
        starts = [item["start"] for item in timeline]
        base_cache: Dict[int, Image.Image] = {}
        caption_final: Dict[int, Optional[Image.Image]] = {}
        sub_cache: Dict[int, Image.Image] = {}

        anim_lens = [self._anim_len(item["scene"], media_flags[i], title) for i, item in enumerate(timeline)]
        times = {0.0}
        for s0, length in zip(starts, anim_lens):
            for k in range(int(round(length / self.INTRO_STEP)) + 1):
                times.add(round(s0 + k * self.INTRO_STEP, 3))
        for ev in events:
            times.add(round(ev["start"], 3))
        points = sorted(t for t in times if t < total - 0.01)

        def scene_at(t: float) -> int:
            idx = 0
            for i, s0 in enumerate(starts):
                if s0 <= t + 1e-6:
                    idx = i
            return idx

        ev_i = 0
        entries: List[Tuple[str, float]] = []
        for n, t in enumerate(points):
            nxt = points[n + 1] if n + 1 < len(points) else total
            dur = nxt - t
            if dur <= 0.001:
                continue
            si = scene_at(t)
            while ev_i + 1 < len(events) and events[ev_i + 1]["start"] <= t + 1e-6:
                ev_i += 1
            ev = events[ev_i] if events and events[ev_i]["start"] <= t + 1e-6 < events[ev_i]["end"] + 1e-6 else None

            if si not in base_cache:
                base_cache[si] = Image.alpha_composite(
                    static, self._scene_base_layer(timeline[si]["scene"], si, len(timeline), media_flags[si]))
            frame = base_cache[si]
            t_rel = t - starts[si]
            if t_rel >= anim_lens[si]:
                if si not in caption_final:
                    caption_final[si] = self._scene_caption(timeline[si]["scene"], media_flags[si], title, anim_lens[si] + 1)
                cap = caption_final[si]
            else:
                cap = self._scene_caption(timeline[si]["scene"], media_flags[si], title, t_rel)
            if cap is not None:
                frame = Image.alpha_composite(frame, cap)
            if ev is not None:
                if ev_i not in sub_cache:
                    sub_cache[ev_i] = self._subtitle_layer(ev["words"], ev["active"])
                frame = Image.alpha_composite(frame, sub_cache[ev_i])
            path = os.path.join(work_dir, f"ov_{n:05d}.png")
            frame.save(path, "PNG", compress_level=1)
            entries.append((path, dur))

        concat_path = os.path.join(work_dir, "overlay.ffconcat")
        with open(concat_path, "w", encoding="utf-8") as f:
            f.write("ffconcat version 1.0\n")
            for path, dur in entries:
                f.write(f"file '{os.path.basename(path)}'\nduration {dur:.3f}\n")
            f.write(f"file '{os.path.basename(entries[-1][0])}'\n")  # concat 데뮤서 규칙: 마지막 파일 반복
        return concat_path

    # ------------------------------------------------------------------
    # 5. 최종 인코딩
    # ------------------------------------------------------------------
    async def _run(self, cmd: List[str], error_message: str) -> None:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                    **ffmpeg_tools.no_window())
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            tail = stderr.decode(errors="ignore").strip().splitlines()[-3:]
            raise RuntimeError(f"{error_message}: {' | '.join(tail)}")

    async def _run_ffmpeg_encode(self, video_track: str, overlay_concat: str, audio_path: str, output_mp4: str, duration: float):
        dur = f"{duration:.3f}"
        filter_complex = (
            f"[1:v]fps={self.FPS},format=rgba[ov];"
            f"[0:v][ov]overlay=0:0:eof_action=repeat[base];"
            # 상단 진행바: 반투명 트랙 위로 노란 막대가 영상 길이에 맞춰 채워짐
            f"[base]drawbox=x=0:y=0:w=iw:h=10:color=black@0.35:t=fill[bt];"
            f"[3:v]format=rgba[bar];"
            f"[bt][bar]overlay=x='-w+w*t/{dur}':y=0:eof_action=pass,format=yuv420p[v]"
        )
        tmp_out = output_mp4 + ".part.mp4"
        cmd = [
            ffmpeg_tools.ffmpeg(), "-y", "-v", "error",
            "-i", video_track,
            "-f", "concat", "-safe", "0", "-i", overlay_concat,
            "-i", audio_path,
            "-f", "lavfi", "-i", f"color=c=0xFFD400:s={self.WIDTH}x10:r={self.FPS}:d={dur}",
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "2:a",
            *ffmpeg_tools.h264_args("good", "veryfast"), "-r", str(self.FPS),
            "-c:a", "aac", "-b:a", "192k",
            "-t", dur,
            "-movflags", "+faststart",
            tmp_out,
        ]
        await self._run(cmd, "FFmpeg 인코딩 실패")
        if await self._get_audio_duration(tmp_out) <= 0:
            raise RuntimeError("FFmpeg 출력 파일이 비어 있습니다.")
        os.replace(tmp_out, output_mp4)
