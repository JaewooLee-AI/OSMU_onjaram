"""Toggle-button-plus-container pattern — the Flet stand-in for Streamlit's
`st.expander`.

Used three times already (brand kit's title history, settings' advanced
options and API key guides) with the same hand-rolled shape; pulled out here
before a fourth (workbench) copy makes it worth doing.

`button=True` draws the toggle as an outlined button with an open/close arrow
(for toggles users must find, e.g. the shorts script editor).
"""
from __future__ import annotations

import flet as ft


def collapsible(label: str, content: ft.Control, initially_open: bool = False, button: bool = False) -> list[ft.Control]:
    box = ft.Container(
        visible=initially_open,
        padding=ft.Padding.only(top=8, bottom=8),
        content=content,
    )
    arrow = lambda: ft.Icons.EXPAND_LESS if box.visible else ft.Icons.EXPAND_MORE  # noqa: E731

    def toggle(e: ft.Event) -> None:
        box.visible = not box.visible
        if button:
            btn.icon = arrow()
            btn.update()
        box.update()

    if button:
        btn = ft.OutlinedButton(label, icon=arrow(), on_click=toggle)
        return [btn, box]
    return [ft.TextButton(label, on_click=toggle), box]
