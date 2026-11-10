"""Minimal shared state for cross-view handoffs and app-wide settings.

Streamlit's `st.session_state["wb_campaign_id"]` implicitly threads a
selected campaign id from the News Curation page to the Workbench page —
any page can read/write it, so the coupling isn't visible at either call
site. Flet has no such implicit global. This is the explicit stand-in: one
instance created in flet_app/main.py and passed to every view's `build()`
call, so a future news_curation_view can set
`state.pending_workbench_campaign_id` and a future workbench_view can read
and clear it on load.

`font_scale` + `request_rerender` back the ⚙️ 설정 화면의 글자 크기 조정 기능.
Views are built fresh from `core.repo` state every time a nav destination is
selected (see flet_app/main.py's `show()`), so "apply the new scale" is just
"rebuild the current view and the page theme" — `request_rerender` is that
callback, wired up by main.py once the page/rail exist.

`navigate_to_workbench` lets a view other than the workbench itself trigger
the nav-rail switch programmatically — e.g. news_curation_view's "뉴스 기반
콘텐츠" cards jumping straight to a specific campaign in the workbench,
instead of only handing off data and making the marketer find the campaign
in the dropdown themselves.

`editing_brand_kit_id` remembers which kit the 🧵 브랜드 킷 screen was
editing, so switching screens and coming back doesn't jump to the default kit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from flet_app.theme import DEFAULT_FONT_SCALE

# core.repo.get_app_state/set_app_state 키 — main.py(초기 로드)와
# settings_view.py(저장) 양쪽이 같은 문자열을 써야 하므로 여기 하나에 둔다.
FONT_SCALE_STATE_KEY = "ui_font_scale"


@dataclass
class AppState:
    pending_workbench_campaign_id: str | None = None
    # 지금 작업 중인 글 — 워크벤치·카드·쇼츠가 같이 쓴다. 메뉴를 옮겨도 같은 글이 열리게(화면마다 다른 글이 열리던 문제).
    current_campaign_id: str | None = None
    # 지금 보고 있는 메뉴(main.py가 바꿈). 백그라운드 작업이 끝났을 때 사용자를 다른 화면으로 끌고 가지 않게 확인하는 데 쓴다.
    current_view: str = ""
    # 메뉴를 떠나기 전에 부르는 함수(저장 안 한 수정 보호) — 화면이 만들 때 넣고, main.py가 메뉴를 바꾸기 전에 부른다.
    before_leave: Optional[Callable[[Callable[[], None]], None]] = None
    # 화면을 다시 그려도 남아 있어야 하는 완료 안내 {글 id: 문구} — 한 번 보여 준 뒤 지운다.
    notices: dict = None

    def __post_init__(self):
        if self.notices is None:
            self.notices = {}
    font_scale: float = DEFAULT_FONT_SCALE
    request_rerender: Optional[Callable[[], None]] = None
    navigate_to_workbench: Optional[Callable[[], None]] = None
    # 🃏 카드·쇼츠 화면: 열 글 id를 넣고 navigate_to_studio()를 부르면 그 글로 열린다
    studio_campaign_id: Optional[str] = None
    navigate_to_studio: Optional[Callable[[], None]] = None
    navigate_to_library: Optional[Callable[[], None]] = None   # 📚 보관함으로
    editing_brand_kit_id: Optional[int] = None
    # (뉴스 큐레이션은 M0에서 뺐음 — 다시 넣을 때 쓸 자리) 그 화면에서 고른 킷.
    news_brand_kit_id: Optional[int] = None
