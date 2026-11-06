"""📚 보관함 — 글이 수십·수백 개 쌓여도 찾고 정리할 수 있는 목록.

- 검색(제목·메모·본문) + 상태·보관 여부·브랜드 킷·라벨·내용(블로그/카드/쇼츠 있음) 필터 + 정렬 + 20개씩 쪽 나누기.
- 한 줄에서 바로 워크벤치·카드·쇼츠·네이버 글로 이동하고, 보관/되살리기·라벨·용량 정리·삭제를 한다.
- 보관은 삭제가 아니다(목록에서만 빠지고 보관함에서 되살린다). 용량 정리는 카드 PNG(다시 그릴 수 있음)와 쇼츠 영상 파일만 지우고,
  돈을 내고 만든 AI 이미지·사진·글은 지우지 않는다(core/library.py).
"""
from __future__ import annotations

import math
import os

import flet as ft

from core import library, repo

from flet_app.image_src import b64_src
from flet_app.state import AppState
from flet_app.theme import BRAND_COLORS, fs, status_chip

PAGE_SIZE = 20
_STATUS_OPTIONS = {"": "상태 전체", "active": "작업 중", "draft": "초안 완료", "published": "게시 완료", "failed": "실패"}
_ARCHIVE_OPTIONS = {"no": "보관 안 한 글", "yes": "보관한 글", "all": "전체"}
_HAS_OPTIONS = {"": "내용 전체", "blog": "블로그 있음", "cards": "카드 있음", "shorts": "쇼츠 영상 있음"}
_SORT_OPTIONS = {"new": "최근 만든 순", "old": "오래된 순", "published": "게시한 순", "title": "제목 순"}


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):,.1f} MB"


def build(page: ft.Page, state: AppState) -> ft.Control:
    scale = state.font_scale
    f = {"query": "", "status": "", "archived": "no", "kit": "", "label": "", "has": "", "sort": "new", "page": 0}
    list_box = ft.Column(spacing=6)
    pager = ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=8)
    summary = ft.Text("", size=fs(12, scale), color=BRAND_COLORS["text_muted"])
    status_line = ft.Text("", size=fs(12, scale))

    def _u(c) -> None:
        try:
            c.update()
        except RuntimeError:
            pass

    def say(msg: str, ok: bool = True) -> None:
        status_line.value = msg
        status_line.color = "#1B6E3C" if ok else "#B3261E"
        _u(status_line)

    # ------------------------------------------------------------------ 이동
    def open_work(c: dict) -> None:
        state.pending_workbench_campaign_id = c["id"]
        if state.navigate_to_workbench:
            state.navigate_to_workbench()

    def open_studio(c: dict) -> None:
        state.studio_campaign_id = c["id"]
        if state.navigate_to_studio:
            state.navigate_to_studio()

    # ------------------------------------------------------------------ 행 동작
    def archive(c: dict, on: bool) -> None:
        repo.set_archived([c["id"]], on)
        reload(f"{'📦 보관했습니다' if on else '↩️ 되살렸습니다'}: {(c.get('title') or '(제목 없음)')[:30]}")

    def edit_labels(c: dict) -> None:
        field = ft.TextField(label="라벨 (쉼표로 구분 — 예: 11월 특강, 청년)", value=", ".join(c.get("labels") or []), autofocus=True)
        existing = repo.all_labels()

        def ok(e: ft.Event) -> None:
            page.pop_dialog()
            repo.set_labels(c["id"], (field.value or "").replace("，", ",").split(","))
            reload("✅ 라벨을 저장했습니다.")

        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("라벨 편집"),
            content=ft.Column([field, ft.Text("쓰고 있는 라벨: " + (", ".join(existing) or "아직 없음"), size=fs(11, scale),
                                              color=BRAND_COLORS["text_muted"])], tight=True, spacing=8, width=420),
            actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("저장", on_click=ok)]))

    def purge_dialog(c: dict) -> None:
        u = library.disk_usage(c)
        cards = ft.Checkbox(label=f"카드 그림(PNG) 지우기 — {_mb(u['cards'])} · 언제든 다시 그릴 수 있습니다", value=u["cards"] > 0,
                            disabled=u["cards"] == 0)
        video = ft.Checkbox(label=f"쇼츠 영상 파일 지우기 — {_mb(u['video'])} · 다시 만들 수 있고, 음성은 캐시에 남아 음성 비용이 다시 들지 않습니다",
                            value=False, disabled=u["video"] == 0)

        def ok(e: ft.Event) -> None:
            page.pop_dialog()
            freed = library.purge(c["id"], cards=bool(cards.value), video=bool(video.value))
            reload(f"🧹 {_mb(freed)}를 정리했습니다.")

        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("용량 정리"),
            content=ft.Column([
                ft.Text(f"이 글의 용량: 카드 {_mb(u['cards'])} · 쇼츠 영상 {_mb(u['video'])} · AI 이미지 {_mb(u['ai_images'])} · 사진 {_mb(u['photos'])}",
                        size=fs(11, scale)),
                cards, video,
                ft.Text("글 본문·카드 문구·쇼츠 대본, 돈을 내고 만든 AI 이미지, 올린 사진은 지우지 않습니다.", size=fs(11, scale),
                        color=BRAND_COLORS["text_muted"]),
            ], tight=True, spacing=8, width=520),
            actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("정리하기", on_click=ok)]))

    def delete_dialog(c: dict) -> None:
        def ok(e: ft.Event) -> None:
            page.pop_dialog()
            repo.delete_campaign(c["id"])
            reload("🗑️ 삭제했습니다.")

        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("이 글을 삭제할까요?"),
            content=ft.Text(f"「{(c.get('title') or '(제목 없음)')[:40]}」을(를) 삭제하면 되돌릴 수 없습니다. 보관만 하려면 [보관]을 쓰세요."),
            actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()),
                     ft.FilledButton("삭제", on_click=ok, style=ft.ButtonStyle(bgcolor="#B3261E"))]))

    def bulk_archive(e: ft.Event) -> None:
        old = library.published_older_than(30)
        if not old:
            say("게시한 지 30일이 지난 글이 없습니다.")
            return

        def ok(ev: ft.Event) -> None:
            page.pop_dialog()
            n = repo.set_archived([c["id"] for c in old], True)
            reload(f"📦 게시 후 30일이 지난 글 {n}건을 보관했습니다(보관함의 '보관한 글'에서 되살릴 수 있습니다).")

        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("게시 후 30일 지난 글을 보관할까요?"),
            content=ft.Text(f"{len(old)}건이 목록에서 빠집니다. 삭제가 아니며 언제든 되살릴 수 있습니다."),
            actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()), ft.FilledButton("보관", on_click=ok)]))

    # ------------------------------------------------------------------ 목록
    def thumb(c: dict) -> ft.Control:
        folder = c.get("card_export_dir")
        path = os.path.join(folder, "slide_01.png") if folder else ""
        src = b64_src(path, 140) if path and os.path.exists(path) else None
        if src:
            return ft.Image(src=src, width=56, height=70, fit=ft.BoxFit.COVER, border_radius=6)
        return ft.Container(width=56, height=70, bgcolor="#F3F1EC", border_radius=6, alignment=ft.Alignment.CENTER,
                            content=ft.Text("✍️", size=20))

    def badge(text: str, on: bool = True) -> ft.Control:
        return ft.Container(content=ft.Text(text, size=fs(10, scale), color="#35593F" if on else "#9AA0A6"),
                            bgcolor="#E8F1EA" if on else "#F1F3F4", padding=ft.Padding.symmetric(horizontal=8, vertical=2), border_radius=10)

    def row(c: dict) -> ft.Control:
        sb = c.get("card_storyboard") or {}
        n_cards = len(sb.get("card_slides") or [])
        has_video = bool(c.get("shorts_video_path")) and os.path.exists(c["shorts_video_path"])
        title = c.get("title") or c.get("source_title") or (c.get("memo") or "")[:30] or "(제목 없음)"
        meta = f"{(c.get('created_at') or '')[:16]}" + (f" · 🧵 {c['brand_kit_name']}" if c.get("brand_kit_name") else "")
        if c.get("published_at"):
            meta += f" · 게시 {c['published_at'][:10]}"
        chips = [status_chip(c["status"], scale),
                 badge("블로그 ✅" if (c.get("content") or "").strip() else "블로그 —", bool((c.get("content") or "").strip())),
                 badge(f"카드 {n_cards}장" if n_cards else "카드 —", bool(n_cards)),
                 badge("쇼츠 ✅" if has_video else ("쇼츠 대본" if sb.get("shorts_scenes") else "쇼츠 —"), bool(has_video or sb.get("shorts_scenes"))),
                 *([badge("📦 보관됨")] if c.get("archived") else []),
                 *[badge(f"#{l}") for l in (c.get("labels") or [])]]
        menu = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, items=[
            ft.PopupMenuItem(content="📦 보관" if not c.get("archived") else "↩️ 되살리기", on_click=lambda e, c=c: archive(c, not c.get("archived"))),
            ft.PopupMenuItem(content="🏷️ 라벨 편집", on_click=lambda e, c=c: edit_labels(c)),
            ft.PopupMenuItem(content="🧹 용량 정리", on_click=lambda e, c=c: purge_dialog(c)),
            ft.PopupMenuItem(content="🗑️ 삭제", on_click=lambda e, c=c: delete_dialog(c)),
        ])
        actions = [ft.TextButton("✍️ 워크벤치", on_click=lambda e, c=c: open_work(c)),
                   ft.TextButton("🃏 카드·쇼츠", on_click=lambda e, c=c: open_studio(c))]
        if c.get("published_url"):
            # url=은 브라우저가 클릭 자체로 새 탭을 열어 팝업 차단에 걸리지 않는다(핸들러에서 launch_url을 부르면 막힐 수 있음).
            actions.append(ft.TextButton("🔗 네이버 글", url=c["published_url"]))
            # 브라우저가 새 탭을 막는 경우를 위해 주소 복사도 둔다(클릭 제스처 안에서 클라이언트가 직접 복사).
            try:
                actions.append(ft.IconButton(ft.Icons.COPY, icon_size=16, tooltip="네이버 글 주소 복사",
                                             action=ft.CopyToClipboard(c["published_url"])))
            except RuntimeError:   # 앱 밖(시험)에서는 복사 동작을 만들 수 없다
                pass
        return ft.Container(
            content=ft.Row([
                thumb(c),
                ft.Column([ft.Text(title, weight=ft.FontWeight.BOLD, size=fs(13, scale), max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                           ft.Text(meta, size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
                           ft.Row(chips, spacing=6, wrap=True)], spacing=3, expand=True),
                ft.Row([*actions, menu], spacing=0, wrap=True),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
            border=ft.Border.all(1, "#14000000"), border_radius=10, padding=10, bgcolor="#FFFFFF" if not c.get("archived") else "#F7F7F7")

    def reload(message: str | None = None, ok: bool = True) -> None:
        rows, total = repo.search_campaigns(f["query"], f["status"], f["archived"], f["kit"], f["label"], f["has"], f["sort"],
                                            PAGE_SIZE, f["page"] * PAGE_SIZE)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        if f["page"] >= pages:            # 필터로 줄어든 뒤 쪽 번호가 넘치면 마지막 쪽으로
            f["page"] = pages - 1
            return reload(message, ok)
        use = library.total_usage()
        summary.value = (f"조건에 맞는 글 {total:,}건 · 전체 용량 {_mb(sum(use.values()))} "
                         f"(카드 {_mb(use['cards'])} · 쇼츠 영상 {_mb(use['video'])} · AI 이미지 {_mb(use['ai_images'])} · 사진 {_mb(use['photos'])})")
        list_box.controls = [row(c) for c in rows] or [ft.Text("조건에 맞는 글이 없습니다.", color=BRAND_COLORS["text_muted"])]
        pager.controls = [
            ft.IconButton(ft.Icons.CHEVRON_LEFT, disabled=f["page"] == 0, on_click=lambda e: go(f["page"] - 1)),
            ft.Text(f"{f['page'] + 1} / {pages} 쪽", size=fs(12, scale)),
            ft.IconButton(ft.Icons.CHEVRON_RIGHT, disabled=f["page"] >= pages - 1, on_click=lambda e: go(f["page"] + 1)),
        ]
        for c in (list_box, pager, summary):
            _u(c)
        if message:
            say(message, ok)

    def go(p: int) -> None:
        f["page"] = max(0, p)
        reload()

    # ------------------------------------------------------------------ 필터
    def changed(key: str):
        def handler(e: ft.Event) -> None:
            f[key] = e.control.value or ""
            f["page"] = 0
            reload()
        return handler

    search = ft.TextField(label="검색 (제목·메모·본문)", width=280, dense=True, prefix_icon=ft.Icons.SEARCH, on_submit=changed("query"),
                          on_blur=changed("query"))

    def dd(key: str, label: str, options: dict, width: int = 150, value: str | None = None) -> ft.Dropdown:
        d = ft.Dropdown(label=label, width=width, dense=True, value=f[key] if value is None else value,
                        options=[ft.DropdownOption(key=k, text=v) for k, v in options.items()])
        d.on_select = changed(key)
        return d

    kit_options = {"": "킷 전체", **{n: n for n in repo.campaign_brand_kit_names()}}
    label_options = {"": "라벨 전체", **{n: f"#{n}" for n in repo.all_labels()}}
    filters = ft.Row([
        search, dd("status", "상태", _STATUS_OPTIONS), dd("archived", "보관", _ARCHIVE_OPTIONS, 160),
        dd("kit", "브랜드 킷", kit_options, 200), dd("label", "라벨", label_options, 150), dd("has", "내용", _HAS_OPTIONS),
        dd("sort", "정렬", _SORT_OPTIONS),
    ], spacing=8, wrap=True)

    reload()
    return ft.Column([
        ft.Text("📚 보관함", size=fs(24, scale), weight=ft.FontWeight.BOLD),
        ft.Text("만든 글을 검색하고 정리합니다. 끝난 글은 삭제하지 말고 보관하세요 — 목록에서만 빠지고 언제든 되살릴 수 있습니다.",
                size=fs(12, scale), color=BRAND_COLORS["text_muted"]),
        filters,
        ft.Row([ft.OutlinedButton("📦 게시 후 30일 지난 글 일괄 보관", on_click=bulk_archive), status_line], spacing=12, wrap=True),
        summary,
        ft.Container(content=ft.Column([list_box, pager], spacing=10, scroll=ft.ScrollMode.AUTO), expand=True),
    ], expand=True, spacing=8)
