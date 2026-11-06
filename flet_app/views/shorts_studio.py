"""🎬 쇼츠 영상 탭 — 확정한 카드(🃏 카드뉴스 탭)에서 쇼츠 대본을 만들고 내레이션을 붙여 MP4(1080x1920)로 만듭니다.

- 대본은 카드 순서·사진을 그대로 따릅니다(새 AI 이미지 없음). AI 변환은 선택이고, 끄면 규칙 기반(AI 호출 0원)입니다.
- 화면은 카드와 같은 3단 템플릿(위 제목·가운데 사진/인포그래픽·아래 소속)을 9:16으로 그립니다.
- 음성은 설정의 '음성 내레이션' 슬롯 모델(Gemini TTS)을 쓰고, 없거나 실패하면 무료 음성으로 대체한다고 화면에 알립니다.
  음성 호출은 사용 기록에 남고, 모델 등록에 초당 단가가 있으면 실행 전에 예상 금액을 보여 줍니다.
- FFmpeg가 필요합니다(Windows 설치 프로그램에 동봉, 소스 실행은 PATH). 없으면 이 탭이 안내합니다.
"""
from __future__ import annotations

import asyncio
import os

import flet as ft

from cards import ffmpeg_tools, shorts_script, tts
from cards.paths import EXPORTS_DIR
from cards.shorts_renderer import ShortsOptions, ShortsRendererService
from core import repo

from flet_app.theme import BRAND_COLORS, fs
from flet_app.views.card_studio import load_storyboard, save_storyboard, sync_assets


def _u(control) -> None:
    try:
        control.update()
    except RuntimeError:
        pass


def estimate_voice(sb) -> dict:
    """음성 합성 예상: 대본 글자 수 → 초 → (등록 단가가 있으면) 금액."""
    chars = sum(len((s.narration_script or "").strip()) for s in sb.shorts_scenes)
    seconds = chars / shorts_script.CHARS_PER_SEC
    model = repo.resolve_slot_model("tts")
    per = model.get("per_second") if model else None
    return {"chars": chars, "seconds": seconds, "model": model, "per_second": per,
            "usd": (seconds * per) if per is not None else None}


def describe_voice_estimate(est: dict) -> str:
    head = f"대본 {est['chars']}자 · 약 {est['seconds']:.0f}초"
    if est["model"] is None:
        return f"{head} · '음성 내레이션' 모델이 없어 무료 음성(gTTS)으로 만듭니다(품질 낮음)."
    if est["usd"] is None:
        return f"{head} · 음성 모델 {est['model']['display_name']} · 단가 미등록(모델 등록에서 초당 단가를 입력하면 예상 금액이 보입니다)"
    return f"{head} · 음성 모델 {est['model']['display_name']} · 예상 ${est['usd']:.3f}"


MOTION_OPTIONS = {
    "none": "움직임 없음 (정지 화면)",
    "zoom_in": "사진 천천히 확대",
    "zoom_out": "사진 천천히 축소",
    "alternate": "확대·축소 번갈아",
}


def render_video(campaign_id: str, sb, voice: str, frame_style: str, progress=None, tts_call=None,
                 photo_motion: str = "none") -> str:
    """쇼츠 MP4를 만들어 경로를 글에 저장합니다(이전 파일은 새 파일로 교체)."""
    out_dir = os.path.join(EXPORTS_DIR, "shorts", campaign_id)
    os.makedirs(out_dir, exist_ok=True)
    renderer = ShortsRendererService(export_dir=out_dir)
    path = asyncio.run(renderer.render_shorts_video(
        sb, progress_callback=progress, options=ShortsOptions(frame_style=frame_style, voice=voice, tts_call=tts_call, photo_motion=photo_motion)))
    repo.update_campaign(campaign_id, shorts_video_path=path)
    return path + (("\n⚠️ " + " / ".join(renderer.last_warnings)) if renderer.last_warnings else "")


def build_shorts_tab(page: ft.Page, campaign: dict, scale: float, reload=None) -> ft.Control:
    campaign_id = campaign["id"]
    sb = load_storyboard(campaign)
    if sb is None:
        return ft.Text("먼저 🃏 카드뉴스 탭에서 카드를 기획하세요. 쇼츠는 그 카드에서 만들어집니다.",
                       size=fs(12, scale), color=BRAND_COLORS["text_muted"])
    sync_assets(sb, campaign)
    state = {"sb": sb}
    status = ft.Text("", size=fs(12, scale))
    spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
    body = ft.Column(spacing=8)
    seconds_dd = ft.Dropdown(label="목표 길이", width=130, dense=True, value="45",
                             options=[ft.DropdownOption(key=str(n), text=f"{n}초") for n in (20, 30, 45, 60)])
    motion_dd = ft.Dropdown(label="사진 움직임", width=240, dense=True, value="none",
                            options=[ft.DropdownOption(key=k, text=v) for k, v in MOTION_OPTIONS.items()],
                            tooltip="가운데 사진 칸만 움직이고 위·아래 글자는 그대로입니다. 사진이 없는 장면은 정지 화면입니다. AI 호출·추가 비용은 없습니다.")
    ai_switch = ft.Switch(label="AI로 내레이션 다듬기 (끄면 AI 호출 없이 카드 문장을 이어 붙입니다)", value=False)
    voice_dd = ft.Dropdown(label="목소리", width=330, dense=True, value="auto",
                           options=[ft.DropdownOption(key=v, text=l) for l, v in tts.VOICE_OPTIONS.items()])
    ffmpeg_note = ft.Text("" if ffmpeg_tools.available() else
                          "⚠️ FFmpeg를 찾을 수 없어 영상을 만들 수 없습니다(설치 프로그램으로 설치했다면 재설치, 소스 실행이면 PATH 확인).",
                          size=fs(11, scale), color="#B3261E")

    def say(msg: str, ok: bool = True) -> None:
        status.value = msg
        status.color = "#1B6E3C" if ok else "#B3261E"
        _u(status)

    def run_in_background(message: str, job) -> None:
        spinner.visible = True
        _u(spinner)
        say(message)

        def _work() -> None:
            try:
                with repo.usage_scope(campaign_id):
                    result = job()
                draw()
                _u(body)
                say(result)
            except Exception as exc:  # noqa: BLE001 — 스레드에서 조용히 사라지지 않게 화면에 보인다
                say(f"❌ {exc}", ok=False)
            finally:
                spinner.visible = False
                _u(spinner)

        page.run_thread(_work)

    def on_convert(e: ft.Event) -> None:
        def job() -> str:
            scenes, report = shorts_script.convert(state["sb"], campaign.get("brand_kit_id"), int(seconds_dd.value), use_llm=ai_switch.value)
            shorts_script.apply_to_storyboard(state["sb"], scenes)
            save_storyboard(campaign_id, state["sb"])
            state["report"] = report
            engine = "AI" if report["engine"] == "llm" else "규칙 기반"
            return f"✅ {engine}으로 장면 {len(scenes)}개를 만들었습니다. 내용을 확인하고 [쇼츠 영상 만들기]를 누르세요."

        run_in_background("🧠 대본을 만드는 중…", job)

    def draw() -> None:
        sb = state["sb"]
        body.controls = []
        if shorts_script.is_stale(sb):
            body.controls.append(ft.Container(
                content=ft.Text("⚠️ 카드가 바뀌었습니다. 대본이 예전 카드 기준이라 [카드에서 대본 만들기]로 다시 만드세요.",
                                size=fs(11, scale), color="#8A6D3B"), bgcolor="#FFF6E5", padding=8, border_radius=6))
        for w in (state.get("report") or {}).get("warnings") or []:
            body.controls.append(ft.Container(content=ft.Text(f"⚠️ {w}", size=fs(11, scale), color="#8A6D3B"),
                                              bgcolor="#FFF6E5", padding=8, border_radius=6))
        if not sb.shorts_scenes:
            body.controls.append(ft.Text("아직 대본이 없습니다. 위에서 [카드에서 대본 만들기]를 누르세요.",
                                         size=fs(12, scale), color=BRAND_COLORS["text_muted"]))
            return
        refs = []
        for i, scene in enumerate(sb.shorts_scenes):
            cap = ft.TextField(label=f"{i + 1}장면 · {scene.section_type} — 화면 문구(30자)", value=scene.display_caption, dense=True)
            nar = ft.TextField(label="내레이션 (이 글을 소리 내어 읽습니다)", value=scene.narration_script, multiline=True,
                               min_lines=2, max_lines=6, dense=True)
            refs.append((scene, cap, nar))
            body.controls.append(ft.Container(content=ft.Column([cap, nar], spacing=6), border=ft.Border.all(1, "#14000000"),
                                              border_radius=8, padding=10))

        def apply_edits() -> None:
            for scene, cap, nar in refs:
                scene.display_caption, scene.narration_script = cap.value or "", nar.value or ""
                scene.duration_seconds = max(shorts_script.MIN_SCENE_SEC, round(len(scene.narration_script) / shorts_script.CHARS_PER_SEC, 1))
            state["sb"].shorts_source_hash = shorts_script.card_hash(state["sb"])
            save_storyboard(campaign_id, state["sb"])

        def on_save(e: ft.Event) -> None:
            apply_edits()
            say("✅ 대본을 저장했습니다.")

        def on_render(e: ft.Event) -> None:
            apply_edits()
            est = estimate_voice(state["sb"])

            def go(ev: ft.Event) -> None:
                page.pop_dialog()
                run_in_background("🎬 쇼츠 영상을 만드는 중… (수 분 걸릴 수 있습니다)", do_render)

            page.show_dialog(ft.AlertDialog(
                modal=True, title=ft.Text("쇼츠 영상을 만들까요?"),
                content=ft.Text(describe_voice_estimate(est) + "\n음성 합성은 사용 기록에 남고 비용이 발생할 수 있습니다."),
                actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("만들기", on_click=go)],
            ))

        def do_render() -> str:
            async def progress(pct: float, msg: str) -> None:
                say(f"🎬 {msg}")

            result = render_video(campaign_id, state["sb"], voice_dd.value, "tri", progress=progress, photo_motion=motion_dd.value)
            return f"✅ 쇼츠 영상을 만들었습니다: {result}"

        est = estimate_voice(sb)
        body.controls.append(ft.Text("🔊 " + describe_voice_estimate(est), size=fs(12, scale)))
        body.controls.append(ft.Row([
            ft.OutlinedButton("대본 저장", icon=ft.Icons.SAVE, on_click=on_save),
            ft.FilledButton("쇼츠 영상 만들기", icon=ft.Icons.MOVIE, on_click=on_render, disabled=not ffmpeg_tools.available()),
        ], spacing=8))
        current = (repo.get_campaign(campaign_id) or {}).get("shorts_video_path")
        if current and os.path.exists(current):
            body.controls.append(ft.Text(f"저장된 영상: {current}", size=fs(11, scale), color=BRAND_COLORS["text_muted"]))

    draw()
    return ft.Column([
        ft.Row([seconds_dd, voice_dd, motion_dd], spacing=8, wrap=True),
        ft.Row([ai_switch], wrap=True),
        ffmpeg_note,
        ft.Row([ft.FilledButton("카드에서 대본 만들기", icon=ft.Icons.AUTO_AWESOME, on_click=on_convert), spinner, status], spacing=10),
        ft.Divider(),
        body,
    ], spacing=8, scroll=ft.ScrollMode.AUTO)
