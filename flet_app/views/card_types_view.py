"""⚙️ 설정 → 🃏 카드 종류·디자인 탭.

카드뉴스의 종류(장 구성·작성 틀·AI 지침)와 디자인(레이아웃·3단 비율·색)을 복제해서 고치고 새로 늘립니다.
코드를 고치지 않고 데이터(JSON)로 추가하는 구조입니다(cards/card_types.py, cards/design_templates.py).
내장 항목은 고칠 수 없고 [복제해서 수정]으로 사용자 항목을 만듭니다. 사용자 항목은 데이터 폴더에 저장됩니다.
"""
from __future__ import annotations

import os

import flet as ft

from cards import card_types, design_templates, preview

from flet_app.image_src import b64_src
from flet_app.theme import BRAND_COLORS, fs

_STATUS_LABELS = {"available": "사용", "draft": "초안(고급 목록에서만)", "hidden": "숨김"}


def _u(control) -> None:
    try:
        control.update()
    except RuntimeError:
        pass


def _src(path: str, width: int) -> str:
    """미리보기 PNG를 줄여 base64로(공통 도우미) — 못 읽으면 빈 문자열."""
    return b64_src(path, width) or ""


def build_card_types_tab(page: ft.Page, scale: float) -> ft.Control:
    box = ft.Container()
    status = ft.Text("", size=fs(12, scale))

    def say(msg: str, ok: bool = True) -> None:
        status.value = msg
        status.color = "#1B6E3C" if ok else "#B3261E"
        _u(status)

    def rebuild(message: str | None = None, ok: bool = True) -> None:
        box.content = _body()
        _u(box)
        if message:
            say(message, ok)


    # --- 미리보기 (샘플 문구·가짜 사진으로 실제 렌더러가 그린 카드) ---------------------
    def open_big(path: str, title: str) -> None:
        page.show_dialog(ft.AlertDialog(
            title=ft.Text(title), content=ft.Image(src=_src(path, 720), width=480, fit=ft.BoxFit.CONTAIN),
            actions=[ft.TextButton("닫기", on_click=lambda e: page.pop_dialog())],
        ))

    def make_preview(render, with_design_picker: str | None = None, base_design: str | None = None):
        """(미리보기 영역, 보이기/숨기기 핸들러). render(design_id|None) → [(원형, PNG 경로)].
        디자인 id에는 고른 브랜드 배색이 "디자인@배색" 형태로 붙어 들어옵니다."""
        strip = ft.Row(spacing=10, scroll=ft.ScrollMode.AUTO, vertical_alignment=ft.CrossAxisAlignment.START)
        note = ft.Text("", size=fs(10, scale), color=BRAND_COLORS["text_muted"])
        picker = None
        if with_design_picker is not None:
            picker = ft.Dropdown(label="미리볼 디자인", value=with_design_picker, dense=True, width=300,
                                 options=[ft.DropdownOption(key=d.id, text=d.name) for d in design_templates.list_all()])
        pal_picker = ft.Dropdown(label="배색 (브랜드 컬러)", value="", dense=True, width=300,
                                 options=[ft.DropdownOption(key="", text="브랜드 기본 (브랜드 킷 색)")]
                                 + [ft.DropdownOption(key=k, text=v["name"]) for k, v in design_templates.BRAND_PALETTES.items()])
        area = ft.Column([ft.Row([*([picker] if picker else []), pal_picker], spacing=8, wrap=True), note, strip], spacing=6, visible=False)

        def load(e=None) -> None:
            note.value = "⏳ 그리는 중…"
            strip.controls = []
            _u(area)

            def _work() -> None:
                try:
                    did = picker.value if picker else base_design
                    items = render(design_templates.with_palette(did, pal_picker.value) if did else None)
                except Exception as exc:  # noqa: BLE001 — 스레드에서 조용히 사라지지 않게
                    note.value = f"❌ 미리보기를 만들지 못했습니다: {exc}"
                    _u(area)
                    return
                note.value = "샘플 문구와 가짜 사진으로 그린 예시입니다. 카드를 누르면 크게 봅니다."
                strip.controls = [
                    ft.GestureDetector(
                        on_tap=lambda e, p=path, a=arche: open_big(p, preview.archetype_name(a)),
                        content=ft.Column([
                            ft.Image(src=_src(path, 300), width=150, height=188, fit=ft.BoxFit.CONTAIN, border_radius=6),
                            ft.Text(f"{i}. {preview.archetype_name(arche)}", size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
                        ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER))
                    for i, (arche, path) in enumerate(items, 1)
                ]
                _u(area)

            page.run_thread(_work)

        if picker:
            picker.on_select = load
        pal_picker.on_select = load

        def toggle(e: ft.Event) -> None:
            area.visible = not area.visible
            _u(area)
            if area.visible and not strip.controls:
                load()

        return area, toggle

    # --- 카드 종류 편집 -------------------------------------------------------
    def open_type_editor(pack: dict) -> None:
        name = ft.TextField(label="화면 이름", value=pack["name"], dense=True)
        desc = ft.TextField(label="한 줄 설명", value=pack.get("desc", ""), dense=True)
        fit = ft.TextField(label="어울리는 원고", value=pack.get("fit", ""), dense=True)
        state = ft.Dropdown(label="상태", value=pack.get("status", "available"), dense=True, width=240,
                            options=[ft.DropdownOption(key=k, text=v) for k, v in _STATUS_LABELS.items()])
        c = pack.get("count") or {}
        cmin = ft.TextField(label="최소 장수", value=str(c.get("min", 3)), width=110, dense=True)
        cdef = ft.TextField(label="기본 장수", value=str(c.get("default", 5)), width=110, dense=True)
        cmax = ft.TextField(label="최대 장수", value=str(c.get("max", 8)), width=110, dense=True)
        layout = ft.Dropdown(label="기본 디자인", value=pack.get("layout_default") or "tri-2-5-3", dense=True, width=360,
                             options=[ft.DropdownOption(key=d.id, text=d.name) for d in design_templates.list_all()])
        structure = ft.TextField(label="AI에게 줄 구성 지침", value=pack.get("llm_structure", ""), multiline=True,
                                 min_lines=3, max_lines=6, dense=True)
        template = ft.TextField(label="작성 틀 (【 】 칸을 채워 쓰는 원고 양식)", value=pack.get("template", ""),
                                multiline=True, min_lines=3, max_lines=8, dense=True)
        tips = ft.TextField(label="작성 팁 (한 줄에 하나)", value="\n".join(pack.get("tips") or []),
                            multiline=True, min_lines=2, max_lines=5, dense=True)
        seq_rows: list[tuple] = []
        seq_col = ft.Column(spacing=4)

        def add_row(slot: dict | None = None) -> None:
            slot = slot or {"archetype": "body", "hint": ""}
            arche = ft.Dropdown(value=slot["archetype"], dense=True, width=190,
                                options=[ft.DropdownOption(key=a, text=a) for a in card_types.VALID_ARCHETYPES])
            hint = ft.TextField(value=slot.get("hint", ""), hint_text="이 장에 쓸 내용 힌트", dense=True, expand=True)
            rep = ft.Checkbox(label="장수에 따라 늘림", value=bool(slot.get("repeat")))
            row = ft.Row([arche, hint, rep], spacing=6)
            seq_rows.append((arche, hint, rep, row))
            seq_col.controls.append(row)

        def remove_last(e: ft.Event) -> None:
            if len(seq_rows) > 1:
                seq_rows.pop()
                seq_col.controls.pop()
                _u(seq_col)

        for slot in pack["sequence"]:
            add_row(slot)
        error = ft.Text("", color="#B3261E", size=fs(12, scale))

        def on_save(e: ft.Event) -> None:
            try:
                new = {k: v for k, v in pack.items() if k not in ("source",)}
                new.update({
                    "name": name.value, "desc": desc.value, "fit": fit.value, "status": state.value,
                    "count": {"min": int(cmin.value), "default": int(cdef.value), "max": int(cmax.value)},
                    "layout_default": layout.value, "llm_structure": structure.value, "template": template.value,
                    "tips": [t.strip() for t in (tips.value or "").splitlines() if t.strip()],
                    "sequence": [{"archetype": a.value, "hint": h.value or "", **({"repeat": True} if r.value else {})}
                                 for a, h, r, _ in seq_rows],
                })
                card_types.save_custom(new)
            except (ValueError, card_types.CardTypeError) as exc:
                error.value = str(exc)
                _u(error)
                return
            page.pop_dialog()
            rebuild(f"✅ '{new['name']}'을(를) 저장했습니다.")

        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text(f"카드 종류 수정 — {pack['id']}"),
            content=ft.Container(width=720, content=ft.Column([
                name, desc, fit, ft.Row([state, cmin, cdef, cmax], spacing=8, wrap=True), layout,
                ft.Text("장 구성 (위에서 아래 순서 = 카드 순서)", size=fs(12, scale), weight=ft.FontWeight.BOLD),
                seq_col,
                ft.Row([ft.TextButton("＋ 장 추가", on_click=lambda e: (add_row(), _u(seq_col))),
                        ft.TextButton("－ 마지막 장 빼기", on_click=remove_last)]),
                structure, template, tips, error,
            ], spacing=8, tight=True, scroll=ft.ScrollMode.AUTO, height=560)),
            actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("저장", on_click=on_save)],
        ))

    def open_json(pack_id: str) -> None:
        page.show_dialog(ft.AlertDialog(
            title=ft.Text("JSON 내보내기 — 복사해서 다른 PC에 가져올 수 있습니다"),
            content=ft.TextField(value=card_types.export_json(pack_id), multiline=True, read_only=True,
                                 min_lines=10, max_lines=18, width=640),
            actions=[ft.TextButton("닫기", on_click=lambda e: page.pop_dialog())],
        ))

    def open_import(e: ft.Event) -> None:
        field = ft.TextField(label="카드 종류 JSON", multiline=True, min_lines=10, max_lines=18, width=640)
        error = ft.Text("", color="#B3261E", size=fs(12, scale))

        def on_ok(ev: ft.Event) -> None:
            try:
                pack = card_types.import_json(field.value or "")
            except card_types.CardTypeError as exc:
                error.value = str(exc)
                _u(error)
                return
            page.pop_dialog()
            rebuild(f"✅ '{pack['name']}'을(를) 가져왔습니다.")

        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("카드 종류 가져오기"), content=ft.Column([field, error], tight=True),
            actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("가져오기", on_click=on_ok)],
        ))

    def type_row(pack: dict, packs: dict) -> ft.Control:
        custom = pack.get("source") == "custom"

        def on_duplicate(e: ft.Event) -> None:
            base, n = f"my-{pack['id']}"[:36], 1
            new_id = base
            while new_id in packs:
                n += 1
                new_id = f"{base}-{n}"
            try:
                card_types.duplicate(pack["id"], new_id)
            except card_types.CardTypeError as exc:
                say(str(exc), ok=False)
                return
            rebuild("✅ 복제했습니다(초안 상태). ✏️ 수정에서 내용을 고치고 상태를 '사용'으로 바꾸세요.")

        def on_delete(e: ft.Event) -> None:
            card_types.delete_custom(pack["id"])
            shadowed = os.path.exists(os.path.join(card_types.BUILTIN_DIR, f"{pack['id']}.json"))
            rebuild(f"'{pack['name']}'을(를) 지웠습니다." + (" (같은 id의 내장 종류가 다시 보입니다)" if shadowed else ""))

        n_slides = len(pack["sequence"])
        pv_area, pv_toggle = make_preview(lambda design_id: preview.render_type_preview(pack, design_id),
                                          with_design_picker=pack.get("layout_default") or "tri-2-5-3")
        return ft.Container(
            content=ft.Column([ft.Row([
                ft.Column([
                    ft.Text(pack["name"], weight=ft.FontWeight.BOLD, size=fs(12, scale)),
                    ft.Text(f"{pack['id']} · {'내가 만든 것' if custom else '내장'} · {_STATUS_LABELS.get(pack.get('status', 'available'))}"
                            f" · {n_slides}칸 구성 · 장수 {pack['count']['min']}~{pack['count']['max']}",
                            size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
                    ft.Text(pack.get("desc", ""), size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
                ], spacing=1, expand=True),
                *([ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, tooltip="수정", on_click=lambda e: open_type_editor(pack))] if custom else []),
                ft.OutlinedButton("미리보기", icon=ft.Icons.IMAGE_OUTLINED, on_click=pv_toggle),
                ft.IconButton(icon=ft.Icons.COPY_OUTLINED, tooltip="복제해서 수정", on_click=on_duplicate),
                ft.IconButton(icon=ft.Icons.CODE, tooltip="JSON 내보내기", on_click=lambda e: open_json(pack["id"])),
                *([ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="지우기", on_click=on_delete)] if custom else []),
            ], vertical_alignment=ft.CrossAxisAlignment.START), pv_area], spacing=6),
            border=ft.Border.all(1, "#14000000"), border_radius=8, padding=10,
        )

    # --- 디자인 ------------------------------------------------------------------
    def open_design_editor(design: design_templates.DesignTemplate) -> None:
        name = ft.TextField(label="이름", value=design.name, dense=True)
        desc = ft.TextField(label="설명", value=design.description, dense=True, multiline=True, max_lines=3)
        radius = ft.TextField(label="모서리 둥글기(px)", value=str(design.radius), width=150, dense=True)
        ratio = ft.TextField(label="3단 비율 (위:가운데:아래)", value=":".join(str(x) for x in design.ratio), width=210, dense=True,
                             helper="예 2:5:3 (tri 레이아웃일 때)")
        theme = ft.Dropdown(label="3단 색", value=design.tri_theme, dense=True, width=180,
                            options=[ft.DropdownOption(key="light", text="밝은 배경"), ft.DropdownOption(key="dark", text="어두운 배경")])
        colors = {k: ft.TextField(label=label, value=design.colors.get(k, ""), width=140, dense=True, hint_text="#RRGGBB")
                  for k, label in (("primary", "주조색"), ("secondary", "보조색"), ("accent", "강조색"), ("background", "배경색"))}
        error = ft.Text("", color="#B3261E", size=fs(12, scale))

        def on_save(e: ft.Event) -> None:
            try:
                parts = [int(x) for x in ratio.value.replace(" ", "").split(":")]
                if len(parts) != 3 or min(parts) < 1:
                    raise ValueError("비율은 1 이상의 숫자 세 개여야 합니다. 예: 2:5:3")
                update = {"name": name.value.strip() or design.name, "description": desc.value or "", "radius": int(radius.value),
                          "ratio": parts, "tri_theme": theme.value,
                          "colors": {k: f.value.strip() for k, f in colors.items() if f.value.strip()}}
                for v in update["colors"].values():
                    if not (len(v) == 7 and v.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in v[1:])):
                        raise ValueError(f"색은 #RRGGBB 형식이어야 합니다: {v}")
                design_templates.save(design.model_copy(update=update))
            except ValueError as exc:
                error.value = str(exc)
                _u(error)
                return
            page.pop_dialog()
            rebuild("✅ 디자인을 저장했습니다.")

        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text(f"디자인 수정 — {design.id}"),
            content=ft.Container(width=640, content=ft.Column([
                name, desc, ft.Row([radius, ratio, theme], spacing=8, wrap=True),
                ft.Text("색 (비우면 브랜드 킷 색)", size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
                ft.Row(list(colors.values()), spacing=8, wrap=True), error,
            ], spacing=8, tight=True, scroll=ft.ScrollMode.AUTO)),
            actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("저장", on_click=on_save)],
        ))

    def design_row(design: design_templates.DesignTemplate) -> ft.Control:
        def on_duplicate(e: ft.Event) -> None:
            new_id = design_templates.unique_id(f"my-{design.id}")
            copy = design.model_copy(update={"id": new_id, "name": f"{design.name} (복사)", "builtin": False})
            try:
                design_templates.save(copy)
            except ValueError as exc:
                say(str(exc), ok=False)
                return
            rebuild("✅ 복제했습니다. ✏️ 수정에서 비율·색을 바꾸세요.")

        def on_delete(e: ft.Event) -> None:
            design_templates.delete(design.id)
            rebuild(f"'{design.name}'을(를) 지웠습니다.")

        extra = f" · 3단 {':'.join(str(x) for x in design.ratio)}" if design.layout == "tri" else ""
        pv_area, pv_toggle = make_preview(lambda did: preview.render_design_preview(did), base_design=design.id)
        return ft.Container(
            content=ft.Column([ft.Row([
                ft.Column([
                    ft.Text(design.name, weight=ft.FontWeight.BOLD, size=fs(12, scale)),
                    ft.Text(f"{design.id} · {'내장' if design.builtin else '내가 만든 것'} · {design.layout}{extra}",
                            size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
                ], spacing=1, expand=True),
                *([ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, tooltip="수정", on_click=lambda e: open_design_editor(design))]
                  if not design.builtin else []),
                ft.OutlinedButton("미리보기", icon=ft.Icons.IMAGE_OUTLINED, on_click=pv_toggle),
                ft.IconButton(icon=ft.Icons.COPY_OUTLINED, tooltip="복제해서 수정", on_click=on_duplicate),
                *([ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="지우기", on_click=on_delete)] if not design.builtin else []),
            ]), pv_area], spacing=6),
            border=ft.Border.all(1, "#14000000"), border_radius=8, padding=10,
        )

    def _body() -> ft.Control:
        packs, errors = card_types.load_all(include_hidden=True)
        return ft.Column([
            ft.Row([ft.Text("카드 종류", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
                    ft.OutlinedButton("JSON 가져오기", icon=ft.Icons.UPLOAD, on_click=open_import)],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Text("종류는 장 구성·작성 틀·AI 지침을 담은 데이터입니다. 내장 종류는 [복제해서 수정]으로 내 종류를 만들고, "
                    "상태를 '사용'으로 바꾸면 카드뉴스 탭의 종류 목록에 나옵니다.",
                    size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
            *[ft.Container(content=ft.Text(f"⚠️ {name}: {'; '.join(problems)}", size=fs(11, scale), color="#8A6D3B"),
                           bgcolor="#FFF6E5", padding=8, border_radius=6) for name, problems in errors.items()],
            *[type_row(p, packs) for p in packs.values()],
            ft.Divider(),
            ft.Text("디자인", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
            ft.Text("카드의 모양(레이아웃·3단 비율·색)입니다. 같은 3단 디자인을 카드와 쇼츠가 함께 씁니다.",
                    size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
            *[design_row(d) for d in design_templates.list_all()],
        ], spacing=8, scroll=ft.ScrollMode.AUTO)

    box.content = _body()
    return ft.Column([status, ft.Container(box, expand=True)], spacing=6, expand=True)
