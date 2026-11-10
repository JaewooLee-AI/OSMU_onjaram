"""🃏 카드뉴스 탭 — 글(워크벤치의 본문 또는 메모)에서 카드뉴스를 기획하고 한 장씩 고쳐 PNG로 그립니다.

- 카드 종류(cards/card_types.py 팩)·장수·디자인을 고릅니다. 종류와 디자인은 데이터라 늘릴 수 있습니다.
- 글에 올려 둔 사진은 카드에 먼저 배치됩니다(AI 이미지 호출 없음). AI 이미지 생성은 다음 단계(M3)입니다.
- AI 기획은 기본 글쓰기 모델 슬롯을 쓰고, 키가 없거나 실패하면 규칙 기반으로 문장을 배분합니다.
- 기획 결과(스토리보드)는 글(campaigns.card_storyboard)에 저장되고, 그림은 데이터 폴더 exports/cards/<글 ID>/<시각>/ 에 저장됩니다.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import time

import flet as ft

from flet_app.save_dialog import is_web, save_bytes, zip_files

from cards import card_types, design_templates, images, preview
from cards.card_renderer import CardNewsRendererService
from cards.director import plan_cards
from cards.paths import EXPORTS_DIR
from cards.schema import BrandElements, EditableStoryboard, MediaAsset
from core import repo, storage

from flet_app.theme import BRAND_COLORS, fs
from flet_app.views.card_types_view import _src


_RENDER_DIR_RE = re.compile(r"^\d{8}-\d{6}(-r)?$")


def _u(control) -> None:
    """화면에 붙어 있을 때만 갱신한다(시험에서 핸들러를 직접 부를 때는 아직 붙기 전)."""
    try:
        control.update()
    except RuntimeError:
        pass


def open_folder(path: str) -> None:
    """파일 탐색기(Windows)·Finder(macOS)로 폴더를 엽니다."""
    import subprocess
    import sys
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


def card_photo_list(campaign: dict) -> list[str]:
    """카드·쇼츠가 쓸 사진: 블로그 사진 + 카드 전용 사진(중복 없이, 블로그 사진 먼저)."""
    out: list[str] = []
    for rel in list(campaign.get("storage_file_paths") or []) + list(campaign.get("card_photo_paths") or []):
        if rel not in out:
            out.append(rel)
    return out


def blog_only_extras(campaign: dict) -> list[str]:
    """블로그 사진 목록에 있지만 본문에 안 쓰인 사진 — 네이버 게시 때 글 뒤에 붙는다(카드 때문에 올렸다면 카드 전용으로 옮겨야 함)."""
    from ai_workers.photo_placement import IMAGE_TAG_RE
    content = campaign.get("content") or ""
    if not content.strip():
        return []
    used = {m.group(1).strip() for m in IMAGE_TAG_RE.finditer(content)}
    return [p for p in (campaign.get("storage_file_paths") or []) if p not in used]


def move_to_card_only(campaign_id: str, paths: list[str]) -> int:
    """블로그 사진 목록에서 빼서 카드 전용 사진으로 옮긴다(파일은 지우지 않는다). 옮긴 장수를 돌려준다."""
    campaign = repo.get_campaign(campaign_id) or {}
    blog = list(campaign.get("storage_file_paths") or [])
    card = list(campaign.get("card_photo_paths") or [])
    moved = [p for p in paths if p in blog]
    repo.update_campaign(campaign_id, storage_file_paths=[p for p in blog if p not in moved],
                         card_photo_paths=card + [p for p in moved if p not in card])
    return len(moved)


def _assets_of(campaign: dict) -> list[MediaAsset]:
    """글에 올려 둔 사진(블로그 + 카드 전용) → 카드에 쓸 에셋."""
    out = []
    for i, rel in enumerate(card_photo_list(campaign), 1):
        path = str(storage.abs_path(rel))
        if os.path.exists(path):
            out.append(MediaAsset(id=f"A{i}", kind="image", path=path, original_name=os.path.basename(rel)))
    return out


def sync_assets(sb: EditableStoryboard, campaign: dict) -> None:
    """글에 올려 둔 사진 목록과 스토리보드의 '내 사진'을 맞춥니다. 같은 파일은 번호(A1…)를 유지하고, 새 사진은 추가하고,
    지워진 사진을 쓰던 카드는 비웁니다. 카드에 이미 고른 사진·AI 이미지는 건드리지 않습니다."""
    current = {a.path: a for a in _assets_of(campaign)}
    known = {a.path: a for a in sb.assets if a.source == "user"}
    used = {int(a.id[1:]) for a in sb.assets if a.id.startswith("A") and a.id[1:].isdigit()}
    keep = [a for a in sb.assets if a.source != "user" or a.path in current]
    for path, asset in current.items():
        if path in known:
            continue
        n = max(used, default=0) + 1
        used.add(n)
        keep.append(asset.model_copy(update={"id": f"A{n}"}))
    gone = {a.id for a in sb.assets} - {a.id for a in keep}
    sb.assets = keep
    for slide in sb.card_slides:
        if slide.asset_id in gone:
            slide.asset_id = None


def _asset_label(asset: MediaAsset) -> str:
    kind = "내 사진" if asset.source == "user" else "AI 이미지"
    return f"{kind} {asset.id}" + (f" · {asset.original_name}" if asset.original_name else "")


def load_storyboard(campaign: dict) -> EditableStoryboard | None:
    raw = campaign.get("card_storyboard")
    if not raw:
        return None
    try:
        return EditableStoryboard.model_validate(raw)
    except Exception:  # noqa: BLE001 — 예전 형식이면 새로 기획하게 한다
        return None


def save_storyboard(campaign_id: str, sb: EditableStoryboard) -> None:
    repo.update_campaign(campaign_id, card_storyboard=sb.model_dump(mode="json"))


def slide_fingerprint(sb: EditableStoryboard, index: int) -> str:
    """카드 한 장의 그림에 영향을 주는 값의 지문(문구·사진·디자인). 그린 뒤 바뀌었는지 알아보는 데 쓴다."""
    import hashlib
    import json
    c = sb.card_slides[index]
    asset = sb.asset(c.asset_id)
    parts = [sb.design_id, c.slide_type, c.lead_headline, c.body_content, c.takeaway, c.stat_value, c.stat_label,
             c.asset_id, asset.path if asset else "", c.text_position, c.comparison_table, c.style, sb.aspect, c.qr_image, c.qr_caption, c.promo_badge]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str).encode()).hexdigest()[:12]


def stale_cards(sb: EditableStoryboard) -> list[int]:
    """그린 뒤 바뀌어서 그림이 옛 내용인 카드 번호(0부터)."""
    return [i for i in range(len(sb.card_slides))
            if i >= len(sb.render_hashes) or sb.render_hashes[i] != slide_fingerprint(sb, i)]


def render_storyboard(campaign_id: str, sb: EditableStoryboard) -> list[str]:
    """카드를 PNG로 그립니다. 이전 렌더링 폴더는 지우고 새 폴더(시각)에 씁니다(그림 캐시 문제 방지)."""
    base = os.path.join(EXPORTS_DIR, "cards", campaign_id)
    out = os.path.join(base, time.strftime("%Y%m%d-%H%M%S"))
    paths = asyncio.run(CardNewsRendererService(export_dir=out).render_all_slides(sb))
    for name in os.listdir(base):
        old = os.path.join(base, name)
        # 이전 렌더링 폴더(시각 이름)만 지운다 — AI 이미지가 있는 assets/ 등 다른 폴더는 절대 지우지 않는다.
        if old != out and os.path.isdir(old) and _RENDER_DIR_RE.match(name):
            shutil.rmtree(old, ignore_errors=True)
    sb.render_hashes = [slide_fingerprint(sb, i) for i in range(len(sb.card_slides))]
    repo.update_campaign(campaign_id, card_export_dir=out, card_storyboard=sb.model_dump(mode="json"))
    return paths


def render_one(campaign_id: str, sb: EditableStoryboard, index: int) -> list[str]:
    """카드 한 장만 다시 그립니다. 기존 렌더링 폴더를 새 폴더로 복사한 뒤 그 장만 덮어씁니다(그림 캐시 문제 방지).
    이전에 그린 결과가 없으면 전체를 그립니다."""
    campaign = repo.get_campaign(campaign_id) or {}
    old = campaign.get("card_export_dir")
    expected = [os.path.join(old, f"slide_{i + 1:02d}.png") for i in range(len(sb.card_slides))] if old else []
    if not old or not all(os.path.exists(p) for p in expected):
        return render_storyboard(campaign_id, sb)
    base = os.path.dirname(old)
    out = os.path.join(base, time.strftime("%Y%m%d-%H%M%S") + "-r")
    shutil.copytree(old, out)
    asyncio.run(CardNewsRendererService(export_dir=out).render_slide(sb, index))
    shutil.rmtree(old, ignore_errors=True)
    hashes = list(sb.render_hashes) + [""] * (len(sb.card_slides) - len(sb.render_hashes))
    hashes[index] = slide_fingerprint(sb, index)
    sb.render_hashes = hashes
    repo.update_campaign(campaign_id, card_export_dir=out, card_storyboard=sb.model_dump(mode="json"))
    return [os.path.join(out, f"slide_{i + 1:02d}.png") for i in range(len(sb.card_slides))]


def build_card_tab(page: ft.Page, campaign: dict, scale: float, reload=None) -> ft.Control:
    """(앱 화면에서는 쓰지 않음 — 🃏 카드·쇼츠 스튜디오가 대신함) 예전 카드뉴스 탭. 시험이 기획·편집·AI 이미지 로직을 이 화면으로 확인하고 있어 남겨 둠."""
    campaign_id = campaign["id"]
    sb = load_storyboard(campaign)
    state = {"sb": sb, "report": None}
    status = ft.Text("", size=fs(12, scale))
    spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
    body = ft.Column(spacing=10)

    types = card_types.available()
    designs = design_templates.choices(keep=[sb.design_id if sb else None])
    packs_by_id = {p["id"]: p for p in types}
    current_type = (sb.card_format if sb and sb.card_format in packs_by_id else (types[0]["id"] if types else None))
    type_dd = ft.Dropdown(label="카드 종류", width=300, dense=True, value=current_type,
                          options=[ft.DropdownOption(key=p["id"], text=p["name"]) for p in types])
    count_dd = ft.Dropdown(label="장수", width=100, dense=True)
    design_dd = ft.Dropdown(label="디자인", width=360, dense=True,
                            value=(sb.design_id if sb else None),
                            options=[ft.DropdownOption(key=d.id, text=d.name) for d in designs])
    type_hint = ft.Text("", size=fs(11, scale), color=BRAND_COLORS["text_muted"])
    mode_dd = ft.Dropdown(
        label="이미지", width=330, dense=True, value=(sb.image_mode if sb else "own_first"),
        options=[ft.DropdownOption(key=k, text=v) for k, v in images.IMAGE_MODES.items()],
        tooltip="내 사진만 쓰면 AI 이미지 비용이 들지 않습니다.",
    )
    photo_note = ft.Text("", size=fs(11, scale), color=BRAND_COLORS["text_muted"])
    has_ai = any(r.get("is_active") for r in repo.list_llm_settings()) and repo.resolve_slot_model("text") is not None
    ai_switch = ft.Switch(label="AI로 기획 (끄면 AI 호출 없이 원고 문장을 나눠 담습니다)", value=has_ai)
    source_field = ft.TextField(
        label="카드로 만들 원고 (비우면 글 본문, 없으면 메모를 씁니다)", multiline=True, min_lines=3, max_lines=8,
        value="", expand=True,
    )

    # 결과 문구는 맨 위 한 곳에만 뜨면 스크롤해서 내려가 있는 사용자가 못 본다 — 버튼 가까이(AI 상자·저장 줄)에도 같은 문구를 보인다.
    status_ai = ft.Text("", size=fs(12, scale))
    status_bottom = ft.Text("", size=fs(12, scale))

    def say(msg: str, ok: bool = True) -> None:
        for t in (status, status_ai, status_bottom):
            t.value = msg
            t.color = "#1B6E3C" if ok else "#B3261E"
            _u(t)

    def sync_type_controls() -> None:
        pack = packs_by_id.get(type_dd.value)
        if not pack:
            return
        c = pack.get("count") or {}
        lo, hi = int(c.get("min", 1)), int(c.get("max", 8))
        keep = count_dd.value if count_dd.value and lo <= int(count_dd.value) <= hi else str(card_types.default_count(pack))
        count_dd.options = [ft.DropdownOption(key=str(n), text=f"{n}장") for n in range(lo, hi + 1)]
        count_dd.value = keep
        if not design_dd.value or (state["sb"] is None):
            design_dd.value = pack.get("layout_default") or designs[0].id
        type_hint.value = f"{pack.get('desc', '')} — {pack.get('fit', '')}"

    sync_type_controls()
    if sb:
        count_dd.value = str(len(sb.card_slides))
        sync_assets(sb, campaign)       # 글에 올린 사진이 바뀌었을 수 있다
    photo_note.value = f"올린 사진 {len(_assets_of(campaign))}장 (블로그 글과 같이 씁니다)"

    def on_type_change(e: ft.Event) -> None:
        # 기획 결과는 그대로 두고, 다음 기획부터 새 종류·디자인 기본값을 쓴다
        design_dd.value = (packs_by_id.get(type_dd.value) or {}).get("layout_default") or design_dd.value
        sync_type_controls()
        for c in (count_dd, design_dd, type_hint):
            _u(c)

    type_dd.on_select = on_type_change

    def on_preview(e: ft.Event) -> None:
        """고른 종류+디자인이 어떻게 나오는지 샘플 카드로 보여 줍니다(AI 호출 없음)."""
        pack, design_id = packs_by_id.get(type_dd.value), design_dd.value
        if not pack:
            return
        say("⏳ 미리보기를 그리는 중…")

        def _work() -> None:
            try:
                items = preview.render_type_preview(pack, design_id)
            except Exception as exc:  # noqa: BLE001
                say(f"❌ 미리보기를 만들지 못했습니다: {exc}", ok=False)
                return
            say("")
            page.show_dialog(ft.AlertDialog(
                title=ft.Text(f"미리보기 — {pack['name']} · {design_templates.get(design_id).name}"),
                content=ft.Container(width=760, content=ft.Column([
                    ft.Text("샘플 문구와 가짜 사진으로 그린 예시입니다. 실제 카드는 원고와 올린 사진으로 만들어집니다.",
                            size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
                    ft.Row([ft.Column([ft.Image(src=_src(path, 360), width=180, height=225, fit=ft.BoxFit.CONTAIN, border_radius=6),
                                       ft.Text(f"{i}. {preview.archetype_name(arche)}", size=fs(10, scale))],
                                      spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                            for i, (arche, path) in enumerate(items, 1)], scroll=ft.ScrollMode.AUTO, spacing=10),
                ], tight=True, spacing=8)),
                actions=[ft.TextButton("닫기", on_click=lambda e: page.pop_dialog())],
            ))

        page.run_thread(_work)

    def on_mode_change(e: ft.Event) -> None:
        if state["sb"] is not None:
            state["sb"].image_mode = mode_dd.value
            images.apply_mode(state["sb"])
            save_storyboard(campaign_id, state["sb"])
            draw_preview()
            _u(body)

    mode_dd.on_select = on_mode_change

    async def on_pick_photos(e: ft.Event) -> None:
        files = await ft.FilePicker().pick_files(
            allow_multiple=True, with_data=True, file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["jpg", "jpeg", "png", "webp"],
        )
        if not files:
            return
        paths = list((repo.get_campaign(campaign_id) or {}).get("storage_file_paths") or [])
        for f in files:
            if f.bytes:
                rel = storage.save_upload(f.bytes, f.name)
                if rel not in paths:
                    paths.append(rel)
        repo.update_campaign(campaign_id, storage_file_paths=paths)
        fresh = repo.get_campaign(campaign_id) or {}
        if state["sb"] is not None:
            sync_assets(state["sb"], fresh)
            images.apply_mode(state["sb"])
            save_storyboard(campaign_id, state["sb"])
            draw_preview()
            _u(body)
        photo_note.value = f"사진 {len(_assets_of(fresh))}장 (블로그 글과 같이 씁니다)"
        _u(photo_note)

    def source_text() -> str:
        return (source_field.value or campaign.get("content") or campaign.get("memo") or "").strip()

    def template_button_click(e: ft.Event) -> None:
        pack = packs_by_id.get(type_dd.value)
        if pack:
            source_field.value = card_types.template_text(pack)
            _u(source_field)

    def draw_preview() -> None:
        """기획 결과(카드별 편집 칸)와 그림 미리보기를 다시 그립니다."""
        sb = state["sb"]
        body.controls = []
        if sb is None:
            body.controls.append(ft.Text("아직 카드가 없습니다. 위에서 종류를 고르고 [카드 기획하기]를 누르세요.",
                                         size=fs(12, scale), color=BRAND_COLORS["text_muted"]))
            return
        for w in (state["report"] or {}).get("warnings") or sb.fact_check_log:
            body.controls.append(ft.Container(content=ft.Text(f"⚠️ {w}", size=fs(11, scale), color="#8A6D3B"),
                                              bgcolor="#FFF6E5", padding=8, border_radius=6))
        refs: list[tuple] = []
        photo_refs: list[tuple] = []
        photo_slots = set(images.photo_slot_indexes(sb))
        est = images.estimate(sb)
        body.controls.append(ft.Container(
            content=ft.Column([
                ft.Text("🖼️ " + images.describe_estimate(est), size=fs(12, scale)),
                ft.Row([
                    ft.FilledButton(f"AI 이미지 {est['count']}장 만들기", icon=ft.Icons.AUTO_AWESOME,
                                    on_click=lambda e: confirm_ai(est), disabled=est["count"] == 0 or est["model"] is None),
                    ft.OutlinedButton("사진 자동 배치", icon=ft.Icons.PHOTO_LIBRARY, on_click=lambda e: auto_place()),
                ], spacing=8, wrap=True),
                *([ft.Text("버튼이 꺼져 있는 이유: 'AI 이미지 생성' 모델이 지정되지 않았습니다(⚙️ 설정 → 🤖 AI 연결·모델).",
                           size=fs(10, scale), color="#B3261E")] if est["count"] and est["model"] is None else []),
                status_ai,
            ], spacing=6),
            bgcolor="#F3F1EC", padding=10, border_radius=8,
        ))
        for i, slide in enumerate(sb.card_slides):
            head = ft.TextField(label=f"{i + 1}장 · {slide.slide_type} — 제목 (*강조*)", value=slide.lead_headline, dense=True)
            text = ft.TextField(label="내용 (줄바꿈으로 항목 구분)", value=slide.body_content, multiline=True, min_lines=2, max_lines=6, dense=True)
            take = ft.TextField(label="아래 한 줄", value=slide.takeaway, dense=True)
            extra = []
            if slide.slide_type == "big_number":
                sv = ft.TextField(label="큰 숫자", value=slide.stat_value, width=160, dense=True)
                sl = ft.TextField(label="숫자 설명", value=slide.stat_label, expand=True, dense=True)
                extra = [ft.Row([sv, sl], spacing=8)]
                refs.append((slide, head, text, take, sv, sl))
            else:
                refs.append((slide, head, text, take, None, None))
            photo_dd = None
            if i in photo_slots:
                value = "none" if (slide.asset_locked and not slide.asset_id) else (slide.asset_id or "")
                photo_dd = ft.Dropdown(
                    label="사진", dense=True, width=340, value=value,
                    options=[ft.DropdownOption(key="", text="(자동 — 이미지 모드에 따름)"),
                             ft.DropdownOption(key="none", text="사진 없음 (글·인포그래픽만)")]
                    + [ft.DropdownOption(key=a.id, text=_asset_label(a)) for a in sb.assets],
                )
                photo_refs.append((slide, photo_dd, value))
                extra.append(ft.Row([
                    photo_dd,
                    ft.OutlinedButton("AI 이미지 다시 만들기" if (slide.asset_id and (sb.asset(slide.asset_id) or MediaAsset(id="", kind="image", path="")).source == "ai")
                                      else "이 칸을 AI 이미지로", icon=ft.Icons.AUTO_AWESOME,
                                      on_click=lambda e, idx=i: confirm_ai(images.estimate(sb, [idx]), [idx]),
                                      disabled=images.estimate(sb, [i])["model"] is None),
                ], spacing=8, wrap=True))

            def on_one(e: ft.Event, idx=i) -> None:
                on_save(e)
                run_in_background(f"🎨 {idx + 1}번 카드를 다시 그리는 중…", lambda: do_render_one(idx))

            body.controls.append(ft.Container(
                content=ft.Column([head, text, take, *extra,
                                   ft.TextButton("이 카드만 다시 그리기", icon=ft.Icons.REFRESH, on_click=on_one)], spacing=6),
                border=ft.Border.all(1, "#14000000"), border_radius=8, padding=10,
            ))

        def apply_photo_choices() -> None:
            for slide, dd, initial in photo_refs:
                if dd.value == initial:          # 바꾸지 않은 칸은 건드리지 않는다(자동 배치된 사진을 '직접 고름'으로 굳히지 않게)
                    continue
                if dd.value == "none":
                    slide.asset_id, slide.asset_locked = None, True
                elif dd.value:
                    slide.asset_id, slide.asset_locked = dd.value, True
                else:                            # '자동'으로 바꾸면 사진을 비우고 직접 고른 표시를 푼다(AI 이미지는 다시 만들 수 있음)
                    slide.asset_id, slide.asset_locked = None, False

        def auto_place() -> None:
            apply_photo_choices()
            images.apply_mode(sb)
            save_storyboard(campaign_id, sb)
            draw_preview()
            _u(body)
            say("사진을 자동 배치했습니다.")

        def confirm_ai(est: dict, only: list[int] | None = None) -> None:
            def go(e: ft.Event) -> None:
                page.pop_dialog()
                apply_photo_choices()
                start_ai(only)

            page.show_dialog(ft.AlertDialog(
                modal=True, title=ft.Text("AI 이미지를 만들까요?"),
                content=ft.Text(images.describe_estimate(est) + "\n장당 10~30초 걸립니다. 실행하면 사용 기록에 남고 비용이 발생할 수 있습니다."
                                "\n만든 뒤 카드 그림도 자동으로 다시 그립니다."),
                actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("만들기", on_click=go)],
            ))

        def start_ai(only: list[int] | None) -> None:
            """AI 이미지를 만드는 동안 진행 창을 띄우고(앱이 멈춘 것처럼 보이지 않게), 끝나면 카드까지 다시 그린다."""
            step = ft.Text("준비 중…", size=fs(12, scale))
            page.show_dialog(ft.AlertDialog(
                modal=True, title=ft.Text("AI 이미지를 만드는 중입니다"),
                content=ft.Column([ft.Row([ft.ProgressRing(width=22, height=22, stroke_width=3), step], spacing=12),
                                   ft.Text("창을 닫지 말고 기다려 주세요. 끝나면 카드까지 자동으로 다시 그립니다.",
                                           size=fs(11, scale), color=BRAND_COLORS["text_muted"])], tight=True, spacing=10),
            ))

            def progress(msg: str) -> None:
                step.value = msg
                _u(step)

            def _work() -> None:
                ok = True
                try:
                    with repo.usage_scope(campaign_id):
                        folder = os.path.join(EXPORTS_DIR, "cards", campaign_id, "assets")
                        result = images.generate_missing(sb, folder, progress=progress, only=only)
                        save_storyboard(campaign_id, sb)
                        msg = f"✅ AI 이미지 {result['made']}장을 만들어 카드에 넣었습니다."
                        if result["made"]:
                            step.value = "카드를 다시 그리는 중…"
                            _u(step)
                            state["paths"] = render_storyboard(campaign_id, sb)
                            msg += f" 카드 {len(state['paths'])}장을 다시 그렸습니다."
                        if result["failed"]:
                            ok = False
                            msg += f" (실패 {len(result['failed'])}장: {result['failed'][0][1]})"
                except Exception as exc:  # noqa: BLE001 — 스레드에서 조용히 사라지지 않게 화면에 보인다
                    msg, ok = f"❌ {exc}", False
                page.pop_dialog()
                draw_preview()
                _u(body)
                say(msg, ok)

            page.run_thread(_work)

        def on_save(e: ft.Event) -> None:
            apply_photo_choices()
            for slide, head, text, take, sv, sl in refs:
                slide.lead_headline, slide.body_content, slide.takeaway = head.value or "", text.value or "", take.value or ""
                if sv is not None:
                    slide.stat_value, slide.stat_label = sv.value or "", sl.value or ""
            save_storyboard(campaign_id, sb)
            say("✅ 카드 내용을 저장했습니다. [카드 그리기]로 다시 그리세요.")

        def on_render(e: ft.Event) -> None:
            on_save(e)
            run_in_background("🎨 카드를 그리는 중…", do_render)

        def do_render_one(idx: int) -> str:
            state["paths"] = render_one(campaign_id, sb, idx)
            return f"✅ {idx + 1}번 카드를 다시 그렸습니다."

        def do_render() -> str:
            paths = render_storyboard(campaign_id, sb)
            state["paths"] = paths
            return f"✅ 카드 {len(paths)}장을 그렸습니다."

        body.controls.append(ft.Row([
            ft.OutlinedButton("카드 내용 저장", icon=ft.Icons.SAVE, on_click=on_save),
            ft.FilledButton("카드 그리기", icon=ft.Icons.IMAGE, on_click=on_render),
        ], spacing=8))
        body.controls.append(status_bottom)
        paths = state.get("paths") or _existing_paths(campaign_id, sb)
        if paths:
            folder = os.path.dirname(paths[0])

            async def on_copy(e: ft.Event) -> None:
                if is_web(page):    # 브라우저에서는 폴더를 고를 수 없으므로 zip 한 파일로 내려받는다
                    name, _how = await save_bytes(page, zip_files(paths), f"{campaign_id[:6]}_cards.zip",
                                                  None, "카드 이미지 저장")
                    say(f"✅ 카드 {len(paths)}장을 zip으로 내려받았습니다(브라우저 다운로드 폴더).")
                    return
                dest = await ft.FilePicker().get_directory_path(dialog_title="카드 이미지를 저장할 폴더")
                if not dest:
                    return
                try:
                    for p_ in paths:
                        shutil.copy2(p_, os.path.join(dest, f"{campaign_id[:6]}_{os.path.basename(p_)}"))
                    say(f"✅ 카드 {len(paths)}장을 {dest} 에 저장했습니다.")
                except OSError as exc:
                    say(f"❌ 저장하지 못했습니다: {exc}", ok=False)

            body.controls.append(ft.Row([
                ft.FilledButton("폴더 열기", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e: open_folder(folder)),
                ft.OutlinedButton("다른 곳에 저장…", icon=ft.Icons.DOWNLOAD, on_click=on_copy),
            ], spacing=8, wrap=True))
            body.controls.append(ft.Text(f"카드 {len(paths)}장이 이 폴더에 PNG로 저장되어 있습니다: {folder}", size=fs(10, scale),
                                         color=BRAND_COLORS["text_muted"], selectable=True))
            body.controls.append(ft.Row(
                [ft.Image(src=_src(p_, 540), width=270, height=337, fit=ft.BoxFit.CONTAIN, border_radius=6) for p_ in paths],
                scroll=ft.ScrollMode.AUTO, spacing=8,
            ))

    def run_in_background(message: str, job) -> None:
        spinner.visible = True
        _u(spinner)
        say(message)

        def _work() -> None:
            try:
                with repo.usage_scope(campaign_id):
                    result = job()
                draw_preview()
                _u(body)
                say(result)
            except Exception as exc:  # noqa: BLE001 — 스레드에서 조용히 사라지지 않게 화면에 보인다
                say(f"❌ {exc}", ok=False)
            finally:
                spinner.visible = False
                _u(spinner)

        page.run_thread(_work)

    def on_plan(e: ft.Event) -> None:
        text = source_text()
        if not text:
            say("원고가 비어 있습니다. 글 본문이나 메모를 먼저 쓰거나 위 칸에 원고를 넣으세요.", ok=False)
            return
        if card_types.has_placeholder(text):
            say("작성 틀의 【 】 칸이 남아 있습니다. 채우거나 그 줄을 지우세요.", ok=False)
            return
        kit_id = campaign.get("brand_kit_id")

        def do_plan() -> str:
            new_sb, report = plan_cards(
                text, type_dd.value, kit_id=kit_id, count=int(count_dd.value or 0) or None, design_id=design_dd.value,
                use_llm=ai_switch.value, assets=_assets_of(campaign), elements=BrandElements(), image_mode=mode_dd.value,
            )
            state["sb"], state["report"], state["paths"] = new_sb, report, None
            save_storyboard(campaign_id, new_sb)
            engine = "AI 기획" if report["engine"].startswith("llm") else "규칙 기반"
            return f"✅ {engine}으로 카드 {len(new_sb.card_slides)}장을 만들었습니다. 내용을 확인하고 [카드 그리기]를 누르세요."

        run_in_background("🧠 카드를 기획하는 중…", do_plan)

    draw_preview()
    return ft.Column(
        [
            ft.Row([type_dd, count_dd, design_dd, ft.OutlinedButton("미리보기", icon=ft.Icons.IMAGE_OUTLINED, on_click=on_preview)],
                   spacing=8, wrap=True),
            type_hint,
            ft.Row([ai_switch, ft.TextButton("이 종류의 작성 틀 넣기", on_click=template_button_click)], wrap=True),
            ft.Row([mode_dd, ft.OutlinedButton("사진 올리기", icon=ft.Icons.ADD_PHOTO_ALTERNATE, on_click=on_pick_photos), photo_note],
                   spacing=8, wrap=True),
            source_field,
            ft.Row([ft.FilledButton("카드 기획하기", icon=ft.Icons.AUTO_AWESOME, on_click=on_plan), spinner, status], spacing=10),
            ft.Divider(),
            body,
        ],
        spacing=8, scroll=ft.ScrollMode.AUTO,
    )


def _existing_paths(campaign_id: str, sb: EditableStoryboard) -> list[str]:
    """저장된 렌더링 폴더에 있는 카드 그림(앱을 다시 열었을 때 미리보기용)."""
    campaign = repo.get_campaign(campaign_id) or {}
    folder = campaign.get("card_export_dir")
    if not folder or not os.path.isdir(folder):
        return []
    paths = [os.path.join(folder, f"slide_{i + 1:02d}.png") for i in range(len(sb.card_slides))]
    return paths if all(os.path.exists(p) for p in paths) else []
