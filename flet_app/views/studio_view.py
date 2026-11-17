"""🃏 카드·쇼츠 스튜디오 — 워크벤치(글)와 따로 쓰는 화면. 그림을 크게 보면서 만들고 고칩니다.

왼쪽은 **미리보기**(큰 카드 + 넘겨 보기 + 저장), 오른쪽은 **순서대로 따라 하는 단계**입니다.
  1 만들기  — 카드 종류·디자인만 고르고 [카드 만들기] 한 번(기획+그리기). 사진·AI·원고는 '고급'에 접어 둠.
  2 다듬기  — 왼쪽에서 고른 카드 한 장의 문구·사진을 고치고 [적용]하면 그 카드만 다시 그립니다.
  3 쇼츠    — [대본 만들기] → 확인 → [쇼츠 영상 만들기](음성 비용 확인 창).
긴 작업(기획·그리기·AI 이미지·영상)은 진행 창을 띄워 앱이 멈춘 것처럼 보이지 않게 합니다.
로직은 outputs.plan_for_campaign / card_studio.render_* / images / shorts_script 를 그대로 씁니다(화면만 새로).
"""
from __future__ import annotations

import os
import shutil

import flet as ft

from flet_app.save_dialog import is_web, save_bytes, zip_files

from cards.schema import CARD_ASPECT_LABELS, CARD_ASPECTS
from cards import bgm, card_types, design_templates, edit as card_edit, ffmpeg_tools, images, preview, shorts_ed, shorts_script, tts
from cards.paths import EXPORTS_DIR
from core import repo, storage

from flet_app import outputs
from flet_app.components.collapsible import collapsible
from flet_app.state import AppState
from flet_app.theme import BRAND_COLORS, fs
from flet_app.dialogs import confirm
from flet_app.views.card_studio import (
    _asset_label, _assets_of, _existing_paths, blog_only_extras, clip_note, load_storyboard, move_to_card_only, open_folder, render_one,
    render_storyboard,
    save_storyboard, stale_cards, sync_assets,
)
from flet_app.views.card_types_view import _src
from flet_app.views.shorts_studio import (
    MOTION_OPTIONS, TEXT_MOTION_OPTIONS, TRANSITION_OPTIONS, describe_voice_estimate, estimate_voice, render_video, voice_note,
)
from flet_app.views.workbench_view import _label

PHOTO_TYPES = images.PHOTO_TYPES

def _u(control) -> None:
    try:
        control.update()
    except RuntimeError:  # 아직 화면에 붙기 전(시험에서 직접 부를 때)
        pass

def _section(title: str, step: str, *controls: ft.Control) -> ft.Container:
    return ft.Container(
        content=ft.Column([ft.Text(f"{step}  {title}", weight=ft.FontWeight.BOLD, size=14), *controls], spacing=8),
        border=ft.Border.all(1, "#1F000000"), border_radius=10, padding=14, bgcolor="#FFFFFF",
    )

def build(page: ft.Page, state: AppState) -> ft.Control:
    scale = state.font_scale
    S: dict = {"cid": None, "sb": None, "idx": 0, "paths": [], "report": None}

    # ------------------------------------------------------------------ 위쪽: 글 고르기 · 알림
    selector = ft.Dropdown(expand=True, label="카드·쇼츠를 만들 글", dense=True)
    status = ft.Text("", size=fs(12, scale))
    left_box, right_box = ft.Container(), ft.Container(expand=True)

    def say(msg: str, ok: bool = True) -> None:
        status.value = msg
        status.color = "#1B6E3C" if ok else "#B3261E"
        _u(status)

    def run_job(title: str, job, ok_message: str | None = None, after=None) -> None:
        """진행 창을 띄우고 백그라운드로 job(step)을 돌린 뒤 결과를 상단에 알립니다. job은 결과 문구를 돌려줍니다."""
        step = ft.Text("준비 중…", size=fs(12, scale))
        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text(title),
            content=ft.Column([ft.Row([ft.ProgressRing(width=22, height=22, stroke_width=3), step], spacing=12),
                               ft.Text("끝날 때까지 창을 닫지 말고 기다려 주세요.", size=fs(11, scale),
                                       color=BRAND_COLORS["text_muted"])], tight=True, spacing=10),
        ))

        def progress(msg: str) -> None:
            step.value = msg
            _u(step)

        def _work() -> None:
            ok, msg = True, ok_message or ""
            try:
                with repo.usage_scope(S["cid"]):
                    msg = job(progress) or msg
            except Exception as exc:  # noqa: BLE001 — 스레드에서 조용히 사라지지 않게 화면에 보인다
                ok, msg = False, f"❌ {exc}"
            page.pop_dialog()
            reload_state()
            draw()
            say(msg, ok)
            if ok and after:
                after()

        page.run_thread(_work)

    # ------------------------------------------------------------------ 상태 읽기·쓰기
    def reload_state() -> None:
        campaign = repo.get_campaign(S["cid"]) or {}
        S["campaign"] = campaign
        S["sb"] = load_storyboard(campaign)
        if S["sb"] is not None:
            sync_assets(S["sb"], campaign)
            S["paths"] = _existing_paths(S["cid"], S["sb"])
            S["idx"] = max(0, min(S["idx"], len(S["sb"].card_slides) - 1))
        else:
            S["paths"], S["idx"] = [], 0

    def source_note() -> str:
        c = S.get("campaign") or {}
        if (source_field.value or "").strip():
            return "원고: 아래 '고급 설정'에 직접 넣은 글을 씁니다."
        if (c.get("content") or "").strip():
            return "원고: 이 글의 블로그 본문을 씁니다."
        if (c.get("memo") or "").strip():
            return "원고: 이 글의 메모를 씁니다(블로그 본문이 아직 없어요)."
        return "⚠️ 원고가 없습니다. 워크벤치에서 메모를 쓰거나 '고급 설정'에 글을 넣으세요."

    # ------------------------------------------------------------------ 1단계: 만들기 (한 번 만들고 계속 재사용하는 컨트롤)
    types = card_types.available()
    packs = {p["id"]: p for p in types}
    first_multi = next((p["id"] for p in types if p["id"] != outputs.ONE_CARD_TYPE), types[0]["id"] if types else None)
    type_dd = ft.Dropdown(label="카드 종류", width=300, dense=True, value=first_multi,
                          options=[ft.DropdownOption(key=p["id"], text=p["name"]) for p in types if p["id"] != outputs.ONE_CARD_TYPE])
    design_dd = ft.Dropdown(label="디자인", width=300, dense=True,
                            options=[ft.DropdownOption(key=d.id, text=d.name) for d in design_templates.choices()])
    count_dd = ft.Dropdown(label="카드 장수", width=170, dense=True)
    aspect_dd = ft.Dropdown(label="카드 크기", width=300, dense=True, value="4:5",
                            options=[ft.DropdownOption(key=k, text=v) for k, v in CARD_ASPECT_LABELS.items()])
    aspect_note = ft.Text("", size=fs(10, scale), color=BRAND_COLORS["text_muted"])

    def move_extras(e: ft.Event) -> None:
        n = move_to_card_only(S["cid"], list(extras_box.data or []))
        reload_state()
        draw()
        say(f"✅ 사진 {n}장을 카드 전용으로 옮겼습니다. 이제 네이버 게시에는 붙지 않습니다(카드에서는 그대로 쓰입니다).")

    extras_text = ft.Text("", size=fs(11, scale), color="#8A6D3B", expand=True)
    extras_box = ft.Container(
        content=ft.Row([extras_text, ft.FilledButton("카드 전용으로 옮기기", on_click=move_extras)], spacing=8),
        bgcolor="#FFF6E5", padding=8, border_radius=8, visible=False)
    palette_dd = ft.Dropdown(label="배색 (브랜드 컬러)", width=300, dense=True, value="",
                             options=[ft.DropdownOption(key="", text="브랜드 기본 (선택한 브랜드 킷 색)")]
                             + [ft.DropdownOption(key=k, text=v["name"]) for k, v in design_templates.BRAND_PALETTES.items()])
    type_hint = ft.Text("", size=fs(11, scale), color=BRAND_COLORS["text_muted"])
    mode_dd = ft.Dropdown(label="이미지", width=330, dense=True, value="own_first",
                          options=[ft.DropdownOption(key=k, text=v) for k, v in images.IMAGE_MODES.items()])
    ai_switch = ft.Switch(label="AI로 카드 기획 (끄면 AI 호출 없이 문장을 나눠 담습니다)", value=outputs.has_ai_planner())
    source_field = ft.TextField(label="카드로 만들 원고 (비우면 블로그 본문, 없으면 메모)", multiline=True, min_lines=3, max_lines=8)
    photo_note = ft.Text("", size=fs(11, scale), color=BRAND_COLORS["text_muted"])
    note = ft.Text("", size=fs(11, scale), color=BRAND_COLORS["text_muted"])

    def follows_aspect() -> bool:
        return design_templates.get(design_dd.value or design_templates.DEFAULT_ID).layout in ("tri", "ed", "rp")

    def refresh_photo_note() -> None:
        """사진을 올렸는데 카드에 안 들어가는 이유(디자인·종류별 사진 칸 수)를 미리 알려 준다."""
        have = len(_assets_of(S.get("campaign") or {}))
        if not have:
            photo_note.value = "올린 사진 없음 (블로그 글과 같이 씁니다)"
        else:
            pack = packs.get(outputs.ONE_CARD_TYPE if count_dd.value == "1" else type_dd.value) or {}
            n = int(count_dd.value or 0) or None
            seq = (card_types.free_sequence(pack, n) if (pack and n) else card_types.expand_sequence(pack, None)) if pack else []
            design = design_templates.get(design_templates.with_palette(design_dd.value, palette_dd.value) or design_templates.DEFAULT_ID)
            slots = sum(1 for s in seq if s["archetype"] in images.PHOTO_TYPES and design.uses_photo(s["archetype"]))
            cp = S.get("campaign") or {}
            photo_note.value = (f"쓸 수 있는 사진 {have}장(블로그 {len(cp.get('storage_file_paths') or [])} + 카드 전용 {len(cp.get('card_photo_paths') or [])}) "
                                f"· 이 설정에서 사진이 들어가는 카드 {slots}장")
            if have > slots:
                photo_note.value += " — 나머지 사진은 ② 다듬기에서 카드마다 고르거나, 카드 장수를 늘려 보세요"
        extras = blog_only_extras(S.get("campaign") or {})
        extras_box.visible = bool(extras)
        extras_text.value = (f"⚠️ 블로그 사진 목록에 본문에 쓰이지 않은 사진이 {len(extras)}장 있습니다. 네이버 게시 때 글 맨 뒤에 붙을 수 있어요. "
                             "카드를 위해 올린 사진이라면 카드 전용으로 옮기세요.") if extras else ""
        extras_box.data = extras
        aspect_dd.disabled = not follows_aspect()
        aspect_note.value = "" if follows_aspect() else "카드 크기는 온자람 디자인·3단 디자인에서만 바꿀 수 있습니다(지금 디자인은 4:5로 그립니다)."
        for c in (photo_note, aspect_dd, aspect_note, extras_box):
            _u(c)

    def sync_type() -> None:
        pack = packs.get(type_dd.value)
        if pack:
            if not design_dd.value or S["sb"] is None:
                design_dd.value = pack.get("layout_default") or design_dd.value
            type_hint.value = f"{pack.get('desc', '')} — {pack.get('fit', '')}"
        # 이전 디자인은 설정에서 켰을 때만 목록에 — 이미 그 디자인으로 만든 글을 열었으면 그 디자인은 남긴다.
        design_dd.options = [ft.DropdownOption(key=d.id, text=d.name)
                             for d in design_templates.choices(keep=[design_dd.value])]
        sync_count()
        for c in (design_dd, type_hint, type_dd, count_dd):
            _u(c)
        refresh_photo_note()

    def sync_count() -> None:
        """장수 선택지: 1장(한 장 카드) + 이 종류가 허용하는 범위. 이미 만든 카드가 있으면 그 장수를 고른 채로 둡니다."""
        pack = packs.get(type_dd.value) or {}
        keys = [str(n) for n in range(1, card_types.MAX_FREE_COUNT + 1)]      # 어떤 종류든 1~8장
        count_dd.options = [ft.DropdownOption(key=k, text="1장 (한 장 카드)" if k == "1" else f"{k}장") for k in keys]
        if count_dd.value not in keys:
            count_dd.value = str(card_types.default_count(pack) if pack else 5)

    def on_type_change(e: ft.Event) -> None:
        pack = packs.get(type_dd.value) or {}
        design_dd.value = pack.get("layout_default") or design_dd.value
        sync_type()

    type_dd.on_select = on_type_change
    for dd in (design_dd, palette_dd, count_dd):
        dd.on_select = lambda e: refresh_photo_note()

    def on_preview(e: ft.Event) -> None:
        pack = packs.get(outputs.ONE_CARD_TYPE if count_dd.value == "1" else type_dd.value)
        if not pack:
            return
        chosen_design = design_templates.with_palette(design_dd.value, palette_dd.value)
        say("⏳ 미리보기를 그리는 중…")

        def _work() -> None:
            try:
                items = preview.render_type_preview(pack, chosen_design, aspect_dd.value if follows_aspect() else "4:5")
            except Exception as exc:  # noqa: BLE001
                say(f"❌ 미리보기를 만들지 못했습니다: {exc}", ok=False)
                return
            say("")
            page.show_dialog(ft.AlertDialog(
                title=ft.Text(f"미리보기 — {pack['name']} · {design_templates.get(chosen_design).name}"),
                content=ft.Container(width=760, content=ft.Column([
                    ft.Text("샘플 문구와 가짜 사진으로 그린 예시입니다.", size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
                    ft.Row([ft.Column([ft.Image(src=_src(path, 360), width=180, height=225, fit=ft.BoxFit.CONTAIN, border_radius=6),
                                       ft.Text(f"{i}. {preview.archetype_name(arche)}", size=fs(10, scale))],
                                      spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                            for i, (arche, path) in enumerate(items, 1)], scroll=ft.ScrollMode.AUTO, spacing=10),
                ], tight=True, spacing=8)),
                actions=[ft.TextButton("닫기", on_click=lambda e: page.pop_dialog())],
            ))

        page.run_thread(_work)

    async def on_pick_photos(e: ft.Event) -> None:
        files = await ft.FilePicker().pick_files(
            allow_multiple=True, with_data=True, file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["jpg", "jpeg", "png", "webp"],
        )
        if not files:
            return
        # 카드 전용 사진으로 저장한다 — 블로그 사진 목록에 넣으면 네이버 게시 때 글 뒤에 붙는다.
        current = repo.get_campaign(S["cid"]) or {}
        paths = list(current.get("card_photo_paths") or [])
        blog = set(current.get("storage_file_paths") or [])
        for f in files:
            if f.bytes:
                rel = storage.save_upload(f.bytes, f.name)
                if rel not in paths and rel not in blog:
                    paths.append(rel)
        repo.update_campaign(S["cid"], card_photo_paths=paths)
        reload_state()
        msg = f"✅ 카드용 사진을 올렸습니다(블로그 글에는 들어가지 않습니다). 카드에 쓸 수 있는 사진은 모두 {len(_assets_of(S['campaign']))}장입니다."
        if S["sb"] is not None:
            def user_placed(sb) -> int:
                return sum(1 for c in sb.card_slides if (sb.asset(c.asset_id) is not None and sb.asset(c.asset_id).source == "user"))
            before = user_placed(S["sb"])
            images.apply_mode(S["sb"])
            save_storyboard(S["cid"], S["sb"])
            added = user_placed(S["sb"]) - before
            msg += (f" 빈 사진 칸 {added}곳에 넣었습니다. [적용]이나 [모두 다시 그리기]로 반영하세요." if added else
                    " 카드의 사진 칸이 이미 채워져 있거나 이 디자인에는 더 넣을 칸이 없어 카드에는 넣지 못했습니다 — "
                    "② 다듬기의 '사진'에서 카드마다 고르세요.")
        draw()
        say(msg)

    VIDEO_NOTICE = ("동영상은 쇼츠의 사진 칸에 들어갑니다(원래 소리는 쓰지 않고 내레이션만 나옵니다).\n\n"
                    "올리기 전에 확인하세요.\n"
                    "· 내담자가 나오거나 내담자를 알아볼 수 있는 영상은 쓰지 않습니다.\n"
                    "· 얼굴·이름표·차량 번호판이 보이는 사람에게 게시 동의를 받았습니다.\n"
                    f"· 한 편은 {storage.MAX_VIDEO_MB}MB까지 올릴 수 있습니다.")

    async def pick_videos() -> None:
        web = bool(getattr(page, "web", False))        # 브라우저 실행은 파일 경로가 없어 내용을 받아야 한다
        files = await ft.FilePicker().pick_files(
            allow_multiple=True, with_data=web, file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=[e.lstrip(".") for e in sorted(storage.VIDEO_EXTS)],
        )
        if not files:
            return
        current = repo.get_campaign(S["cid"]) or {}
        paths = list(current.get("card_photo_paths") or [])
        added, problems = 0, []
        for f in files:
            src = getattr(f, "path", None)
            try:
                if src and os.path.isfile(src):
                    rel = storage.save_video(f.name, src_path=src)
                elif f.bytes:
                    rel = storage.save_video(f.name, raw=f.bytes)
                else:
                    problems.append(f"{f.name}: 파일을 읽지 못했습니다")
                    continue
            except storage.VideoTooLarge as exc:
                problems.append(f"{f.name}: {exc} — {storage.MAX_VIDEO_MB}MB를 넘습니다. 필요한 부분만 잘라서 올려 주세요")
                continue
            except OSError as exc:
                problems.append(f"{f.name}: 저장하지 못했습니다({type(exc).__name__})")
                continue
            if rel not in paths:
                paths.append(rel)
                added += 1
        if added:
            repo.update_campaign(S["cid"], card_photo_paths=paths)
            reload_state()
            if S["sb"] is not None:
                sync_assets(S["sb"], S["campaign"])
                save_storyboard(S["cid"], S["sb"])
        draw()
        msg = (f"✅ 동영상 {added}편을 올렸습니다. ③ 쇼츠의 대본에서 장면마다 고르거나 [올린 동영상을 장면에 이어 넣기]를 누르세요."
               if added else "새로 올린 동영상이 없습니다.")
        say(msg + "".join(f"\n⚠️ {p}" for p in problems), ok=bool(added) and not problems)

    def on_pick_videos(e: ft.Event) -> None:
        confirm(page, "쇼츠용 동영상 올리기", VIDEO_NOTICE, lambda: page.run_task(pick_videos), ok_label="확인하고 올리기", danger=False)

    def offer_ai_fill() -> None:
        """3단 카드의 가운데는 사진 칸입니다. 비어 있는 사진 칸이 있으면 바로 채울 방법을 묻습니다(AI는 비용 확인 후에만)."""
        sb = S["sb"]
        if sb is None:
            return
        empty = images.ai_targets(sb)
        if not empty:
            return
        est = images.estimate(sb)
        body = [ft.Text(f"사진을 넣을 칸이 {len(empty)}개 비어 있어 지금은 글씨만 보입니다. 가운데에 사진이 들어가게 할까요?")]
        actions = [ft.TextButton("나중에", on_click=lambda e: page.pop_dialog())]
        if est["model"] is not None:
            body.append(ft.Text(images.describe_estimate(est) + "\n장당 10~30초 걸립니다."))

            def go(e: ft.Event) -> None:
                page.pop_dialog()
                run_job("AI 이미지를 만드는 중입니다", lambda progress: ai_job(progress, None))
            actions.append(ft.FilledButton(f"AI 이미지 {est['count']}장으로 채우기", on_click=go))
        else:
            body.append(ft.Text("AI 이미지를 쓰려면 ⚙️ 설정 → 🤖 AI 연결·모델에서 'AI 이미지 생성 모델'을 지정하세요. 또는 [사진 올리기]로 내 사진을 넣으세요.",
                                size=fs(11, scale), color=BRAND_COLORS["text_muted"]))
        page.show_dialog(ft.AlertDialog(modal=True, title=ft.Text("가운데 사진 칸이 비어 있어요"),
                                        content=ft.Column(body, tight=True, spacing=8), actions=actions))

    def make_cards(e: ft.Event | None = None) -> None:
        def job(progress) -> str:
            progress("카드를 기획하는 중…")
            one = count_dd.value == "1"
            sb, report = outputs.plan_for_campaign(
                S["cid"], type_id=outputs.ONE_CARD_TYPE if one else type_dd.value,
                design_id=design_templates.with_palette(design_dd.value, palette_dd.value),
                aspect=aspect_dd.value if follows_aspect() else "4:5",
                use_ai=ai_switch.value, image_mode=mode_dd.value, source=source_field.value or None,
                count=None if one else int(count_dd.value or 0) or None,
            )
            progress("카드를 그리는 중…")
            paths = render_storyboard(S["cid"], sb)
            warn = list(report.get("warnings") or [])
            mine = [a for a in sb.assets if a.source == "user"]
            placed = sum(1 for c in sb.card_slides if (sb.asset(c.asset_id) is not None and sb.asset(c.asset_id).source == "user"))
            photo_msg = ""
            if len(mine) > placed and (sb.image_mode != "ai_first"):
                photo_msg = (f"\n📷 올린 사진 {len(mine)}장 중 {placed}장을 넣었습니다 — 이 디자인·카드 종류에서 사진이 들어가는 카드가 "
                             f"{len(images.photo_slot_indexes(sb))}장뿐입니다. 나머지 사진은 ② 다듬기의 '사진'에서 카드마다 골라 넣거나, "
                             "카드 장수를 늘려 보세요.")
            return f"✅ 카드 {len(paths)}장을 만들었습니다. 왼쪽에서 확인하고, 고칠 곳은 아래 ② 다듬기에서 고치세요." + \
                   (f" (⚠️ {len(warn)}건 확인 필요)" if warn else "") + photo_msg + clip_note(S["cid"])

        if S["sb"] is not None:
            def go(ev: ft.Event) -> None:
                page.pop_dialog()
                run_job("카드를 만드는 중입니다", job, after=offer_ai_fill)

            page.show_dialog(ft.AlertDialog(
                modal=True, title=ft.Text("카드를 새로 만들까요?"),
                content=ft.Text("지금 카드에서 고친 내용과 쇼츠 대본이 새로 만든 카드로 바뀝니다."),
                actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("새로 만들기", on_click=go)],
            ))
        else:
            run_job("카드를 만드는 중입니다", job, after=offer_ai_fill)

    make_button = ft.FilledButton("🃏 카드 만들기", icon=ft.Icons.AUTO_AWESOME, on_click=make_cards, height=44)
    section_a = _section("카드 만들기", "①", ft.Row([type_dd, design_dd, palette_dd, aspect_dd, ft.OutlinedButton("미리보기", icon=ft.Icons.IMAGE_OUTLINED, on_click=on_preview)],
                                                   spacing=8, wrap=True), aspect_note,
                         type_hint, extras_box, ft.Row([count_dd, ft.OutlinedButton("카드용 사진 올리기", icon=ft.Icons.ADD_PHOTO_ALTERNATE, on_click=on_pick_photos),
                                                         ft.OutlinedButton("쇼츠용 동영상 올리기", icon=ft.Icons.VIDEO_CALL, on_click=on_pick_videos),
                                            photo_note], spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                         *collapsible("⚙️ 고급 설정 (이미지 모드 · AI 기획 · 원고 직접 넣기)", ft.Column([mode_dd, ai_switch, source_field], spacing=8)),
                         make_button, note)

    # ------------------------------------------------------------------ 왼쪽: 큰 미리보기
    def select(i: int) -> None:
        apply_edits(save_only=True)
        S["idx"] = i
        draw()

    def draw_left() -> None:
        sb, paths = S["sb"], S["paths"]
        if sb is None:
            left_box.content = ft.Container(
                width=400, height=500, bgcolor="#F3F1EC", border_radius=12, alignment=ft.Alignment.CENTER,
                content=ft.Text("오른쪽 ①에서 [카드 만들기]를 누르면\n여기에 카드가 크게 보입니다.", text_align=ft.TextAlign.CENTER,
                                color=BRAND_COLORS["text_muted"], size=fs(12, scale)))
            return
        n, i = len(sb.card_slides), S["idx"]
        stale = set(stale_cards(sb))
        banner: list[ft.Control] = []
        if stale and paths:
            banner = [ft.Container(
                content=ft.Row([ft.Text(f"⚠️ 고친 뒤 다시 그리지 않은 카드가 {len(stale)}장 있습니다 — 그림이 옛 모습입니다.",
                                        size=fs(11, scale), color="#8A6D3B", expand=True),
                                ft.FilledButton("모두 다시 그리기", on_click=lambda e: redraw_all())], spacing=8),
                bgcolor="#FFF6E5", padding=8, border_radius=8)]
        big: ft.Control
        if paths and os.path.exists(paths[i]):
            big = ft.Image(src=_src(paths[i], 800), width=400, height=min(640, int(400 * CARD_ASPECTS.get(sb.aspect, 1350) / 1080)),
                           fit=ft.BoxFit.CONTAIN, border_radius=10)
        else:
            big = ft.Container(width=400, height=500, bgcolor="#F3F1EC", border_radius=12, alignment=ft.Alignment.CENTER,
                               content=ft.Text("아직 그리지 않았습니다.\n② 다듬기의 [적용]을 누르세요.", text_align=ft.TextAlign.CENTER))
        # 작은 그림은 한 줄에 모두 들어가게 크기를 맞춘다(카드 최대 8장 — 옆으로 넘기거나 줄을 바꾸면 아래 저장 버튼이 밀려 안 보임).
        count = len(paths) if paths else n
        tw = max(36, min(70, (404 - (count - 1) * 6) // max(1, count) - 6))
        th = int(tw * 88 / 70)

        def thumb(k: int, p: str) -> ft.Control:
            img = (ft.Image(src=_src(p, 160), width=tw, height=th, fit=ft.BoxFit.CONTAIN, border_radius=4) if p and os.path.exists(p)
                   else ft.Container(width=tw, height=th, bgcolor="#F3F1EC", border_radius=4))
            badge = ft.Container(ft.Text(str(k + 1), size=fs(10, scale), color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                                 bgcolor="#4A7C59" if k == i else "#99000000", border_radius=8,
                                 padding=ft.Padding.symmetric(horizontal=6, vertical=1), left=3, top=3)
            return ft.GestureDetector(on_tap=lambda e, k=k: select(k), mouse_cursor=ft.MouseCursor.CLICK, content=ft.Container(
                content=ft.Stack([img, badge], width=tw, height=th),
                border=ft.Border.all(3 if (k == i or k in stale) else 1, "#4A7C59" if k == i else ("#E0A030" if k in stale else "#1F000000")),
                border_radius=6, padding=1, tooltip=f"{k + 1}번 · {preview.archetype_name(sb.card_slides[k].slide_type)}" if k < n else None))

        thumbs = ft.Row([thumb(k, p) for k, p in enumerate(paths or [""] * n)], spacing=6, width=404)
        save_row: list[ft.Control] = []
        if paths:
            folder = os.path.dirname(paths[0])

            async def on_copy(e: ft.Event) -> None:
                if is_web(page):    # 브라우저에서는 폴더를 고를 수 없으므로 zip 한 파일로 내려받는다
                    name, _how = await save_bytes(page, zip_files(paths), f"{S['cid'][:6]}_cards.zip",
                                                  None, "카드 이미지 저장")
                    say(f"✅ 카드 {len(paths)}장을 zip으로 내려받았습니다(브라우저 다운로드 폴더).")
                    return
                dest = await ft.FilePicker().get_directory_path(dialog_title="카드 이미지를 저장할 폴더")
                if not dest:
                    return
                try:
                    for p_ in paths:
                        shutil.copy2(p_, os.path.join(dest, f"{S['cid'][:6]}_{os.path.basename(p_)}"))
                    say(f"✅ 카드 {len(paths)}장을 {dest} 에 저장했습니다.")
                except OSError as exc:
                    say(f"❌ 저장하지 못했습니다: {exc}", ok=False)

            save_row = [ft.Row([ft.FilledButton("폴더 열기", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e: open_folder(folder)),
                                ft.OutlinedButton("다른 곳에 저장…", icon=ft.Icons.DOWNLOAD, on_click=on_copy)], spacing=8, wrap=True),
                        ft.Text(f"PNG {len(paths)}장 · {folder}", size=fs(10, scale), color=BRAND_COLORS["text_muted"], selectable=True)]
        left_box.content = ft.Column([
            *banner,
            big,
            ft.Row([ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=lambda e: select(max(0, i - 1)), disabled=i == 0),
                    ft.Text(f"{i + 1} / {n} · {preview.archetype_name(sb.card_slides[i].slide_type)}", size=fs(12, scale)),
                    ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=lambda e: select(min(n - 1, i + 1)), disabled=i >= n - 1)],
                   alignment=ft.MainAxisAlignment.CENTER),
            thumbs, *save_row,
        ], spacing=8, width=410, scroll=ft.ScrollMode.AUTO)      # 창이 낮아도 아래 저장 버튼까지 내려 볼 수 있게

    # ------------------------------------------------------------------ 2단계: 다듬기
    edit_refs: dict = {}

    def apply_edits(save_only: bool = False) -> None:
        """지금 보이는 카드 칸의 값을 스토리보드에 넣고 저장합니다(다른 카드로 넘길 때도 잃지 않게)."""
        sb = S["sb"]
        if sb is None or not edit_refs:
            return
        slide = sb.card_slides[edit_refs["i"]]
        slide.lead_headline, slide.body_content, slide.takeaway = edit_refs["head"].value or "", edit_refs["text"].value or "", edit_refs["take"].value or ""
        if edit_refs.get("sv") is not None:
            slide.stat_value, slide.stat_label = edit_refs["sv"].value or "", edit_refs["sl"].value or ""
        if edit_refs.get("promo") is not None:
            slide.promo_badge = (edit_refs["promo"].value or "").strip()
            slide.qr_caption = (edit_refs["qr_cap"].value or "").strip()
        dd = edit_refs.get("photo")
        if dd is not None and dd.value != edit_refs["photo_initial"]:     # 바꾼 칸만 '직접 고름'으로 굳힌다
            if dd.value == "none":
                slide.asset_id, slide.asset_locked = None, True
            elif dd.value:
                slide.asset_id, slide.asset_locked = dd.value, True
            else:
                slide.asset_id, slide.asset_locked = None, False
            edit_refs["photo_initial"] = dd.value
        save_storyboard(S["cid"], sb)

    def redraw_all() -> None:
        apply_edits()
        run_job("카드를 다시 그리는 중입니다",
                lambda progress: f"✅ 카드 {len(render_storyboard(S['cid'], S['sb']))}장을 다시 그렸습니다." + clip_note(S["cid"]))

    def on_request(instruction: str) -> None:
        """말로 카드 한 장 고치기: 글 모델이 바꿀 칸만 돌려주고, 그림 요청이면 새 장면 설명을 넣은 뒤 비용 확인으로 이어간다."""
        if not instruction.strip():
            say("고칠 내용을 입력하세요.", ok=False)
            return
        apply_edits()
        i = S["idx"]
        S["pending_image"] = None

        def job(progress) -> str:
            progress("요청을 카드에 반영하는 중…")
            r = card_edit.edit_card(S["sb"], i, instruction, S["campaign"].get("brand_kit_id"))
            save_storyboard(S["cid"], S["sb"])
            names = {"lead_headline": "제목", "body_content": "내용", "takeaway": "아래 한 줄", "image_prompt": "그림 장면",
                     "style": "모양(색·글자 크기)"}
            if not r["changed"]:
                return "ℹ️ 바뀐 내용이 없습니다. 요청을 더 구체적으로 써 보세요."
            msg = f"✅ {i + 1}번 카드의 {', '.join(names[c] for c in r['changed'])}을(를) 바꿨습니다."
            if r.get("style_scope") == "all":
                progress("모든 카드를 다시 그리는 중…")
                render_storyboard(S["cid"], S["sb"])
            elif any(c != "image_prompt" for c in r["changed"]):
                progress("카드를 다시 그리는 중…")
                render_one(S["cid"], S["sb"], i)
            if "style" in r["changed"]:
                msg += "\n글자는 칸에 들어가는 크기까지만 커집니다(넘치면 자동으로 줄어듭니다)."
            if r["image_changed"]:
                S["pending_image"] = i
                msg += " 새 그림은 아래 확인 창에서 만들 수 있습니다."
            return msg + "".join(f"\n⚠️ {w}" for w in r["warnings"]) + clip_note(S["cid"], None if r.get("style_scope") == "all" else i)

        run_job("요청을 처리하는 중입니다", job, after=lambda: S.get("pending_image") is not None and confirm_ai([S["pending_image"]]))

    def on_apply(e: ft.Event) -> None:
        apply_edits()
        i = S["idx"]
        run_job(f"{i + 1}번 카드를 다시 그리는 중", lambda progress: (render_one(S["cid"], S["sb"], i), f"✅ {i + 1}번 카드를 다시 그렸습니다." + clip_note(S["cid"], i))[1])

    def confirm_ai(only: list[int] | None) -> None:
        sb = S["sb"]
        est = images.estimate(sb, only)

        def go(e: ft.Event) -> None:
            page.pop_dialog()
            apply_edits()
            run_job("AI 이미지를 만드는 중입니다", lambda progress: ai_job(progress, only))

        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("AI 이미지를 만들까요?"),
            content=ft.Text(images.describe_estimate(est) + "\n장당 10~30초 걸립니다. 실행하면 사용 기록에 남고 비용이 발생할 수 있습니다.\n"
                            "만든 뒤 카드 그림도 자동으로 다시 그립니다."),
            actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("만들기", on_click=go)],
        ))

    def ai_job(progress, only) -> str:
        sb = S["sb"]
        result = images.generate_missing(sb, os.path.join(EXPORTS_DIR, "cards", S["cid"], "assets"), progress=progress, only=only)
        save_storyboard(S["cid"], sb)
        msg = f"✅ AI 이미지 {result['made']}장을 만들어 카드에 넣었습니다."
        if result["made"]:
            progress("카드를 다시 그리는 중…")
            paths = render_storyboard(S["cid"], sb)
            msg += f" 카드 {len(paths)}장을 다시 그렸습니다."
        if result["failed"]:
            msg += f" (실패 {len(result['failed'])}장: {result['failed'][0][1]})"
        return msg

    async def on_pick_qr(e: ft.Event) -> None:
        """QR 코드 이미지 한 장을 이 카드(마지막 안내)에 붙입니다. 이미지는 그대로(재압축 없이) 이 글의 카드 폴더에 PNG로 저장합니다."""
        files = await ft.FilePicker().pick_files(allow_multiple=False, with_data=True, file_type=ft.FilePickerFileType.CUSTOM,
                                                allowed_extensions=["png", "jpg", "jpeg", "webp"])
        if not files or not files[0].bytes:
            return
        try:
            import io
            import time
            from PIL import Image
            im = Image.open(io.BytesIO(files[0].bytes))
            im.load()
            folder = os.path.join(EXPORTS_DIR, "cards", S["cid"], "assets")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"qr_{S['idx'] + 1}_{time.strftime('%H%M%S')}.png")
            im.save(path, "PNG")
        except Exception as exc:  # noqa: BLE001
            say(f"QR 이미지를 읽지 못했습니다: {exc}", ok=False)
            return
        apply_edits()
        S["sb"].card_slides[S["idx"]].qr_image = path
        save_storyboard(S["cid"], S["sb"])
        say("✅ QR 이미지를 붙였습니다. [적용]을 누르면 카드에 그려집니다.")
        draw()

    def on_clear_qr(e: ft.Event) -> None:
        apply_edits()
        S["sb"].card_slides[S["idx"]].qr_image = ""
        save_storyboard(S["cid"], S["sb"])
        draw()

    def section_b() -> ft.Control:
        sb, i = S["sb"], S["idx"]
        slide = sb.card_slides[i]
        head = ft.TextField(label="제목 (*강조*로 감싸면 눈에 띕니다)", value=slide.lead_headline, dense=True)
        text = ft.TextField(label="내용 (줄바꿈으로 항목 구분)", value=slide.body_content, multiline=True, min_lines=2, max_lines=6, dense=True)
        take = ft.TextField(label="아래 한 줄", value=slide.takeaway, dense=True)
        edit_refs.clear()
        edit_refs.update({"i": i, "head": head, "text": text, "take": take, "sv": None, "sl": None, "photo": None, "photo_initial": ""})
        extra: list[ft.Control] = []
        if slide.slide_type == "big_number":
            sv = ft.TextField(label="큰 숫자", value=slide.stat_value, width=160, dense=True)
            sl = ft.TextField(label="숫자 설명", value=slide.stat_label, expand=True, dense=True)
            edit_refs.update({"sv": sv, "sl": sl})
            extra.append(ft.Row([sv, sl], spacing=8))
        if slide.slide_type not in ("big_number", "comparison_table", "event_info"):
            is_slot = i in set(images.photo_slot_indexes(sb))
            value = "none" if (slide.asset_locked and not slide.asset_id) else (slide.asset_id or "")
            dd = ft.Dropdown(label="사진", dense=True, width=330, value=value,
                             options=[ft.DropdownOption(key="", text="(자동)"), ft.DropdownOption(key="none", text="사진 없음 (글만)")]
                             + [ft.DropdownOption(key=a.id, text=_asset_label(a)) for a in sb.assets])
            edit_refs.update({"photo": dd, "photo_initial": value})
            cur = sb.asset(slide.asset_id)
            ai_btn = ft.OutlinedButton("AI 이미지 다시 만들기" if cur and cur.source == "ai" else "이 칸을 AI 이미지로", icon=ft.Icons.AUTO_AWESOME,
                                       on_click=lambda e: confirm_ai([i]), disabled=images.estimate(sb, [i])["model"] is None)
            extra.append(ft.Row([dd, ai_btn], spacing=8, wrap=True))
            if not is_slot:
                extra.append(ft.Text("이 카드는 보통 사진 없이 가운데에 목록·안내를 그립니다. 사진을 고르면 그 목록 대신 사진이 들어갑니다.",
                                     size=fs(10, scale), color=BRAND_COLORS["text_muted"]))
        if slide.slide_type == "call_to_action":
            promo = ft.TextField(label="할인·혜택 배지 (예: 청년 5회기 할인 — 비우면 배지 없음)", value=slide.promo_badge, dense=True)
            qr_cap = ft.TextField(label="QR 옆 안내 문구 (비우면 기본 문구)", value=slide.qr_caption, dense=True)
            edit_refs.update({"promo": promo, "qr_cap": qr_cap})
            qr_ok = bool(slide.qr_image and os.path.exists(slide.qr_image))
            qr_row = ft.Row([
                ft.OutlinedButton("QR 이미지 바꾸기" if qr_ok else "QR 이미지 올리기", icon=ft.Icons.QR_CODE_2, on_click=on_pick_qr),
                *([ft.TextButton("QR 지우기", on_click=on_clear_qr)] if qr_ok else []),
                ft.Text("QR 이미지가 붙어 있습니다" if qr_ok else "QR이 필요할 때 만들어서 올리세요(없으면 QR 없이 그립니다)",
                        size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
            ], spacing=8, wrap=True)
            extra.extend([promo, qr_row, qr_cap])
            if design_templates.get(sb.design_id).layout not in ("oj", "ed", "rp"):
                extra.append(ft.Text("배지·QR은 온자람 디자인(에디토리얼·리포트)에서 그려집니다. 다른 디자인에서는 보이지 않습니다.",
                                     size=fs(10, scale), color=BRAND_COLORS["text_muted"]))
        req = ft.TextField(label="말로 고치기", helper="예: 제목을 더 짧게 / 이미지를 숲 느낌으로 / 배경을 연한 파란색으로 / 모든 카드 글자를 크게", multiline=True,
                           min_lines=1, max_lines=3, dense=True)
        req_btn = ft.FilledButton("요청 실행", icon=ft.Icons.AUTO_AWESOME, disabled=not outputs.has_ai_planner(),
                                  on_click=lambda e: on_request(req.value or ""))
        extra.append(ft.Column([req, ft.Row([req_btn, ft.Text("글 모델 1회 호출 · 이미지는 비용 확인 후에 만듭니다" if outputs.has_ai_planner()
                                                              else "AI 키와 글쓰기 모델이 있어야 합니다(설정)", size=fs(10, scale),
                                                              color=BRAND_COLORS["text_muted"])], spacing=8)], spacing=4))
        warns = [ft.Text(f"⚠️ {w}", size=fs(11, scale), color="#8A6D3B") for w in ((S.get("report") or {}).get("warnings") or sb.fact_check_log)]
        est = images.estimate(sb)
        bulk = ft.Row([ft.Text("🖼️ " + images.describe_estimate(est), size=fs(11, scale), expand=True),
                       *([ft.FilledButton(f"AI 이미지 {est['count']}장 한꺼번에", icon=ft.Icons.AUTO_AWESOME, on_click=lambda e: confirm_ai(None))]
                         if est["count"] and est["model"] else [])], spacing=8)
        return _section(f"{i + 1}번 카드 다듬기", "②", *warns, head, text, take, *extra,
                        ft.Row([ft.FilledButton("적용 (이 카드 다시 그리기)", icon=ft.Icons.CHECK, on_click=on_apply)]), ft.Divider(), bulk)

    # ------------------------------------------------------------------ 3단계: 쇼츠
    seconds_dd = ft.Dropdown(label="목표 길이", width=120, dense=True, value=str(outputs.default_shorts_seconds()),
                             options=[ft.DropdownOption(key=str(n), text=f"{n}초") for n in outputs.SHORTS_SECONDS])
    voice_dd = ft.Dropdown(label="목소리", width=300, dense=True, value="auto",
                           options=[ft.DropdownOption(key=v, text=l) for l, v in tts.VOICE_OPTIONS.items()])
    motion_dd = ft.Dropdown(label="사진 움직임", width=260, dense=True, value="dynamic",
                            options=[ft.DropdownOption(key=k, text=v) for k, v in MOTION_OPTIONS.items()])
    text_motion_dd = ft.Dropdown(label="글자 움직임", width=200, dense=True, value="slide",
                                 options=[ft.DropdownOption(key=k, text=v) for k, v in TEXT_MOTION_OPTIONS.items()])
    transition_dd = ft.Dropdown(label="장면 전환", width=220, dense=True, value="auto",
                                options=[ft.DropdownOption(key=k, text=v) for k, v in TRANSITION_OPTIONS.items()])
    short_ai = ft.Switch(label="AI로 내레이션 다듬기", value=False)
    LAYOUT_NOTE = {
        "typo": "카드 내용을 화면에 충실하게 담습니다: 제목·요약·본문·항목이 장면 시작에 차례로 나타난 뒤 멈춰서 읽을 수 있고(자막을 음성에 맞추지 않음), "
                "강조어에는 형광펜이 칠해집니다. 가로 영상·사진은 제목 아래 창에, 세로 영상·사진은 화면 가득, 미디어가 없으면 글자만으로 채웁니다. "
                "대본은 화면에 보이는 카드 내용을 빠짐없이 읽고, 그래도 화면 글자를 읽을 시간이 모자라면 그 장면을 최대 1초 늘립니다. '글자 움직임'을 '없음'으로 하면 글자가 처음부터 보입니다(장면 전환 효과는 쓰지 않음).",
        "band": "위 띠에 시리즈 이름과 제목, 가운데 영상 창, 아래 띠에 지금 읽는 문장(큰 자막)이 나옵니다. 올린 영상은 장면 순서대로 이어서 재생되고(없으면 사진이 확대·축소로 움직임), "
                "영상 전체가 보이도록 맞추고 양옆은 같은 영상을 흐리게 깝니다. 특정 장면만 다른 영상·사진을 쓰려면 아래 대본에서 고르세요. "
                "단계·체크·안내·숫자 장면은 아래 띠에 내용 패널이 음성에 맞춰 나타나고(자막은 생략), 비교표는 카드 모양입니다.",
        "full": "올린 영상(없으면 사진)을 화면 전체에 깔고 위에 시리즈 이름과 제목, 아래에 자막을 얹습니다. 단계·체크·안내·숫자 장면은 영상 위 반투명 패널로 나옵니다. 비교표는 카드 모양입니다.",
        "card": "예전 모양: 카드 디자인을 그대로 9:16으로 그리고 사진 칸 안에서만 사진·영상이 움직입니다. 목록 칸이 음성에 맞춰 하나씩 나타납니다.",
    }
    layout_dd = ft.Dropdown(label="쇼츠 모양", width=340, dense=True, value="typo",
                            options=[ft.DropdownOption(key="typo", text="글자 중심 (카드 내용 + 글자 움직임) — 권장"),
                                     ft.DropdownOption(key="band", text="영상 띠 모양 (위 제목·가운데 영상·아래 자막)"),
                                     ft.DropdownOption(key="full", text="영상 전체 화면 (영상 위에 글자)"),
                                     ft.DropdownOption(key="card", text="카드 모양 (예전, 텍스트 기반)")],
                            on_select=lambda e: (setattr(layout_note, "value", LAYOUT_NOTE[layout_dd.value or "typo"]), _u(layout_note)))
    layout_note = ft.Text("", size=fs(10, scale), color=BRAND_COLORS["text_muted"])
    speed_dd = ft.Dropdown(label="동영상 재생 속도", width=250, dense=True, value="auto",
                           options=[ft.DropdownOption(key="auto", text="자동 (짧으면 천천히)"), ft.DropdownOption(key="0.5", text="0.5배 (느리게)"),
                                    ft.DropdownOption(key="0.75", text="0.75배"), ft.DropdownOption(key="1", text="1배 (보통)"),
                                    ft.DropdownOption(key="1.5", text="1.5배"), ft.DropdownOption(key="2", text="2배 (빠르게)")])
    music_now = outputs.default_music()
    music_dd = ft.Dropdown(label="배경 음악", width=300, dense=True, value=music_now["track"],
                           options=[ft.DropdownOption(key="", text="음악 없음")] + [ft.DropdownOption(key=t["id"], text=bgm.label(t)) for t in bgm.tracks()],
                           tooltip="말하는 동안에는 음악이 자동으로 작아집니다. 음원 추가·기본값은 설정 → 📣 생성 채널.")
    music_vol_dd = ft.Dropdown(label="음악 크기", width=140, dense=True, value=music_now["volume"],
                               options=[ft.DropdownOption(key=k, text=v) for k, v in bgm.VOLUME_LABELS.items()])
    scene_refs: list = []

    def apply_scenes(mark_fresh: bool = True) -> None:
        """대본 칸의 값을 저장. mark_fresh=False(메뉴를 떠날 때 자동 저장)면 '카드가 바뀌었다' 표시는 그대로 둔다."""
        sb = S["sb"]
        if sb is None:
            return
        for scene, cap, nar, media_dd, start_tf in scene_refs:
            scene.display_caption, scene.narration_script = cap.value or "", nar.value or ""
            scene.asset_id = media_dd.value or None
            try:
                scene.clip_start = max(0.0, float(start_tf.value or 0.0))
            except ValueError:
                scene.clip_start = 0.0
            scene.duration_seconds = max(shorts_script.MIN_SCENE_SEC, round(len(scene.narration_script) / shorts_script.CHARS_PER_SEC, 1))
        if scene_refs:
            if mark_fresh:
                sb.shorts_source_hash = shorts_script.card_hash(sb)
            save_storyboard(S["cid"], sb)

    def on_video_relay(e: ft.Event) -> None:
        sb = S["sb"]
        if sb is None:
            return
        apply_scenes(mark_fresh=False)
        sync_assets(sb, S["campaign"])
        count = shorts_ed.assign_video_relay(sb, overwrite=True)
        if not count:
            say("올린 동영상이 없습니다. ① 카드 만들기의 [쇼츠용 동영상 올리기]로 먼저 올려 주세요.", ok=False)
            return
        save_storyboard(S["cid"], sb)
        draw()
        say(f"✅ 올린 동영상을 {count}장면에 순서대로 이어 넣었습니다(장면 길이만큼씩 이어서). 대본에서 장면별 시작 초를 고칠 수 있습니다.")

    def on_script(e: ft.Event) -> None:
        apply_edits()

        def job(progress) -> str:
            progress("쇼츠 대본을 만드는 중…")
            scenes, report = shorts_script.convert(S["sb"], S["campaign"].get("brand_kit_id"), int(seconds_dd.value), use_llm=short_ai.value,
                                                   follow_screen=(layout_dd.value or "typo") == "typo")
            shorts_script.apply_to_storyboard(S["sb"], scenes)
            save_storyboard(S["cid"], S["sb"])
            S["report"] = report
            return f"✅ 대본 {len(scenes)}장면을 만들었습니다. 내용을 확인하고 [쇼츠 영상 만들기]를 누르세요." + \
                   "".join(f"\n⚠️ {w}" for w in report.get("warnings") or [])

        run_job("쇼츠 대본을 만드는 중입니다", job)

    def on_video(e: ft.Event) -> None:
        apply_scenes()
        est = estimate_voice(S["sb"])

        def go(ev: ft.Event) -> None:
            page.pop_dialog()

            def job(progress) -> str:

                async def cb(pct: float, msg: str) -> None:
                    progress(msg)
                result = render_video(S["cid"], S["sb"], voice_dd.value, "tri", progress=cb, photo_motion=motion_dd.value,
                                      text_motion=text_motion_dd.value, transition=transition_dd.value, video_layout=layout_dd.value or "typo", video_speed=speed_dd.value or "auto",
                                      music=music_dd.value or "", music_volume=music_vol_dd.value or "mid")
                return f"✅ 쇼츠 영상을 만들었습니다: {result}"

            run_job("쇼츠 영상을 만드는 중입니다 (수 분 걸릴 수 있어요)", job)

        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("쇼츠 영상을 만들까요?"),
            content=ft.Text(voice_note(voice_dd.value, est) + ("" if voice_dd.value == "silent" else "\n음성 합성은 사용 기록에 남고 비용이 발생할 수 있습니다.")),
            actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("만들기", on_click=go)],
        ))

    def section_c() -> ft.Control:
        sb = S["sb"]
        scene_refs.clear()
        items: list[ft.Control] = []
        if shorts_script.is_stale(sb):
            items.append(ft.Text("⚠️ 카드가 바뀌었습니다. [카드에서 대본 만들기]로 다시 만드세요.", size=fs(11, scale), color="#8A6D3B"))
        if not ffmpeg_tools.available():
            items.append(ft.Text("⚠️ FFmpeg를 찾을 수 없어 영상을 만들 수 없습니다.", size=fs(11, scale), color="#B3261E"))
        items.append(ft.Row([seconds_dd, voice_dd, motion_dd, text_motion_dd, transition_dd], spacing=8, wrap=True))
        if design_templates.native_shorts(design_templates.get(sb.design_id or design_templates.DEFAULT_ID).layout):
            items.append(ft.Row([layout_dd, speed_dd], wrap=True))
            layout_note.value = LAYOUT_NOTE[layout_dd.value or "typo"]
            items.append(layout_note)
        items.append(ft.Row([music_dd, music_vol_dd], spacing=8, wrap=True))
        items.append(ft.Row([short_ai], wrap=True))
        videos = [a for a in sb.assets if a.kind == "video"]
        native = design_templates.native_shorts(design_templates.get(sb.design_id or design_templates.DEFAULT_ID).layout)
        top_btns = [ft.FilledButton("카드에서 대본 만들기", icon=ft.Icons.AUTO_AWESOME, on_click=on_script)]
        if videos and sb.shorts_scenes:
            top_btns.append(ft.OutlinedButton("올린 동영상을 장면에 이어 넣기", icon=ft.Icons.THEATERS, on_click=on_video_relay,
                                              tooltip="동영상 한 편을 1장면(0초~)·2장면(이어서)…처럼 모든 장면의 사진 칸에 차례로 넣습니다."))
        items.append(ft.Row(top_btns, spacing=8, wrap=True))
        if videos:
            items.append(ft.Text(f"🎬 올린 동영상 {len(videos)}편 — 원래 소리는 쓰지 않습니다. 대본을 다시 만들면 장면별 미디어 지정은 지워집니다."
                                 + ("" if native else " 지금 디자인은 사진 칸에 영상을 넣지 못합니다(온자람 에디토리얼·리포트 디자인에서 됩니다)."),
                                 size=fs(10, scale), color=BRAND_COLORS["text_muted"]))
        if sb.shorts_scenes:
            asset_opts = [ft.DropdownOption(key="", text="(자동: 올린 동영상 → 없으면 카드 사진)")] + [
                ft.DropdownOption(key=a.id, text=_asset_label(a)) for a in sb.assets]
            rows = []
            for k, scene in enumerate(sb.shorts_scenes):
                cap = ft.TextField(label=f"{k + 1}장면 · 화면 문구(30자)", value=scene.display_caption, dense=True)
                nar = ft.TextField(label="내레이션 (소리 내어 읽습니다)", value=scene.narration_script, multiline=True, min_lines=2, max_lines=5, dense=True)
                picked = scene.asset_id if (scene.asset_id and sb.asset(scene.asset_id)) else ""
                media_dd = ft.Dropdown(label="이 장면의 사진·동영상", width=300, dense=True, value=picked, options=asset_opts)
                start_tf = ft.TextField(label="동영상 시작(초)", width=130, dense=True, value=f"{float(scene.clip_start or 0.0):g}")
                scene_refs.append((scene, cap, nar, media_dd, start_tf))
                rows += [cap, nar, ft.Row([media_dd, start_tf], spacing=8, wrap=True), ft.Divider(height=6)]
            items += collapsible(f"📝 대본 {len(sb.shorts_scenes)}장면 보기·고치기 (장면별 사진·동영상)", ft.Column(rows, spacing=6))
            items.append(ft.Text("🔊 " + describe_voice_estimate(estimate_voice(sb)), size=fs(11, scale)))
            current = (repo.get_campaign(S["cid"]) or {}).get("shorts_video_path")
            btns = [ft.FilledButton("쇼츠 영상 만들기", icon=ft.Icons.MOVIE, on_click=on_video, disabled=not ffmpeg_tools.available())]
            if current and os.path.exists(current):
                btns.append(ft.OutlinedButton("영상 폴더 열기", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e: open_folder(os.path.dirname(current))))
            items.append(ft.Row(btns, spacing=8, wrap=True))
            if current and os.path.exists(current):
                items.append(ft.Text(f"만들어 둔 영상: {current}", size=fs(10, scale), color=BRAND_COLORS["text_muted"], selectable=True))
        return _section("쇼츠 영상", "③", *items)

    # ------------------------------------------------------------------ 그리기
    def draw() -> None:
        note.value = source_note()
        from_sb = S.pop("sync_from_sb", False) and S["sb"] is not None
        if from_sb:    # 글을 처음 열었을 때만 이미 만든 카드의 설정을 고른 채로 보여 준다(그 뒤에는 사용자가 고른 값을 지키지 않고 덮어쓰지 않는다)
            sb = S["sb"]
            if sb.card_format in packs:
                type_dd.value = sb.card_format
            design_dd.value, palette_dd.value = design_templates.split_id(sb.design_id)[0], design_templates.split_id(sb.design_id)[1]
            aspect_dd.value = sb.aspect if sb.aspect in CARD_ASPECTS else "4:5"
        sync_type()
        if from_sb and str(len(S["sb"].card_slides)) in [o.key for o in count_dd.options]:
            count_dd.value = str(len(S["sb"].card_slides))
        refresh_photo_note()
        draw_left()
        right_box.content = ft.Column([section_a] + ([section_b(), section_c()] if S["sb"] is not None else []),
                                      spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)
        for c in (left_box, right_box, photo_note, note):
            _u(c)

    # ------------------------------------------------------------------ 글 고르기
    def refresh_selector(preferred: str | None) -> None:
        campaigns = repo.recent_campaigns(15, include=preferred or selector.value)   # 최근 글만(게시 완료 글도 뒤쪽에 포함) — 나머지는 📚 보관함
        selector.options = [ft.DropdownOption(key=c["id"], text=_label(c)) for c in campaigns]
        ids = [c["id"] for c in campaigns]
        pick = preferred if preferred in ids else next((c["id"] for c in campaigns if c.get("card_storyboard")), ids[0] if ids else None)
        selector.value = pick
        if pick:
            S["cid"] = pick
            state.current_campaign_id = pick
            S["sync_from_sb"] = True
            reload_state()
            draw()

    def on_pick(e: ft.Event) -> None:
        apply_edits(save_only=True)
        S["cid"], S["idx"] = selector.value, 0
        state.current_campaign_id = selector.value
        S["report"] = None
        S["sync_from_sb"] = True
        reload_state()
        draw()

    selector.on_select = on_pick

    def before_leave(proceed) -> None:
        """다른 메뉴로 가기 전에 ② 다듬기·쇼츠 대본 칸의 수정을 조용히 저장한다([적용]을 안 눌러도 잃지 않게)."""
        try:
            apply_edits(save_only=True)
            apply_scenes(mark_fresh=False)
        except Exception as exc:  # noqa: BLE001
            print(f"[studio] 떠나기 전 저장 실패: {exc}")
        proceed()

    state.before_leave = before_leave
    preferred = state.studio_campaign_id or state.current_campaign_id
    state.studio_campaign_id = None
    refresh_selector(preferred)
    if not S["cid"]:
        return ft.Column([ft.Text("🃏 카드·쇼츠", size=fs(24, scale), weight=ft.FontWeight.BOLD),
                          ft.Text("만들 글이 없습니다. 워크벤치에서 [➕ 새 콘텐츠]로 메모를 쓰고 오세요.", color=BRAND_COLORS["text_muted"])])

    return ft.Column([
        ft.Row([ft.Text("🃏 카드·쇼츠", size=fs(24, scale), weight=ft.FontWeight.BOLD), selector,
                ft.OutlinedButton("📚 보관함", on_click=lambda e: state.navigate_to_library() if state.navigate_to_library else None,
                                  tooltip="최근 15개만 목록에 보입니다. 더 많은 글은 보관함에서 검색하세요")], spacing=16),
        status,
        ft.Row([left_box, right_box], expand=True, vertical_alignment=ft.CrossAxisAlignment.START, spacing=16),
    ], expand=True, spacing=8)
