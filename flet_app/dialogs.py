"""여러 화면이 같이 쓰는 확인 창.

되돌릴 수 없는 일(삭제·덮어쓰기)은 모두 이 창을 거칩니다 — 화면마다 확인 여부가 달랐던 것을 한곳으로 모았습니다.
"""
from __future__ import annotations

from typing import Callable, Optional

import flet as ft

DANGER = "#B3261E"


def confirm(page: ft.Page, title: str, message: str, on_ok: Callable[[], None], ok_label: str = "삭제",
            danger: bool = True, extra: Optional[ft.Control] = None) -> None:
    """확인 창. [취소]는 아무것도 하지 않고, [ok_label]을 누르면 창을 닫고 on_ok()를 부릅니다."""

    def ok(e: ft.Event) -> None:
        page.pop_dialog()
        on_ok()

    content = ft.Column([ft.Text(message)] + ([extra] if extra is not None else []), tight=True, spacing=10, width=480)
    page.show_dialog(ft.AlertDialog(
        modal=True, title=ft.Text(title), content=content,
        actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()),
                 ft.FilledButton(ok_label, on_click=ok, style=ft.ButtonStyle(bgcolor=DANGER) if danger else None)],
    ))


def confirm_delete_campaign(page: ft.Page, campaign: dict, on_done: Callable[[], None]) -> None:
    """글 삭제 확인. 보관(되돌릴 수 있음)을 먼저 권하고, 지울 때 그 글의 카드 그림·쇼츠 영상 파일도 같이 정리할지 고르게 합니다."""
    from core import library, repo

    from flet_app.theme import display_title
    title = display_title(campaign, 40)
    files = ft.Checkbox(label="이 글의 카드 그림·쇼츠 영상 파일도 지우기 (AI 이미지·올린 사진은 남김)", value=True)

    def archive() -> None:
        repo.set_archived([campaign["id"]], True)
        on_done()

    def delete() -> None:
        if files.value:
            try:
                library.purge(campaign["id"], cards=True, video=True)
            except Exception:  # noqa: BLE001 — 파일 정리가 실패해도 글 삭제는 한다
                pass
        repo.delete_campaign(campaign["id"])
        on_done()

    def ok(e: ft.Event) -> None:
        page.pop_dialog()
        delete()

    def keep(e: ft.Event) -> None:
        page.pop_dialog()
        archive()

    page.show_dialog(ft.AlertDialog(
        modal=True, title=ft.Text("이 글을 삭제할까요?"),
        content=ft.Column([
            ft.Text(f"「{title}」을(를) 삭제하면 되돌릴 수 없습니다. 목록에서만 치우려면 [보관]을 쓰세요(📚 보관함에서 다시 꺼낼 수 있음)."),
            files,
        ], tight=True, spacing=10, width=480),
        actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()),
                 ft.OutlinedButton("보관", on_click=keep),
                 ft.FilledButton("삭제", on_click=ok, style=ft.ButtonStyle(bgcolor=DANGER))],
    ))


def ask_save_before_leave(page: ft.Page, names: list, saves: list, proceed: Callable[[], None]) -> None:
    """저장하지 않은 수정이 있을 때: [저장하고 이동] [저장 안 하고 이동] [취소]. saves는 인자 없는 저장 함수 목록."""

    def save_and_go(e: ft.Event) -> None:
        page.pop_dialog()
        for save in saves:
            try:
                save()
            except Exception as exc:  # noqa: BLE001 — 저장은 DB에 먼저 쓰고 화면 표시만 실패하는 경우가 있다
                print(f"[dialogs] 떠나기 전 저장 중 화면 갱신 실패(저장은 됨): {exc}")
        proceed()

    def discard(e: ft.Event) -> None:
        page.pop_dialog()
        proceed()

    page.show_dialog(ft.AlertDialog(
        modal=True, title=ft.Text("저장하지 않은 수정이 있습니다"),
        content=ft.Text("고친 내용: " + ", ".join(names) + "\n저장하고 이동할까요?"),
        actions=[ft.TextButton("취소", on_click=lambda e: page.pop_dialog()),
                 ft.OutlinedButton("저장 안 하고 이동", on_click=discard),
                 ft.FilledButton("저장하고 이동", on_click=save_and_go)],
    ))

