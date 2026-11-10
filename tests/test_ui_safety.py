"""화면 안전장치: 삭제·덮어쓰기 확인 창, 화면 간 '지금 글' 공유, 생성 완료 안내, 저장 안 한 수정 보호."""
from __future__ import annotations

import flet as ft
import pytest

from core import repo
from core.brand_seed import seed_if_empty
from flet_app.state import AppState
from tests.test_views_build import FakePage, page_context  # noqa: F401 — 가짜 페이지 문맥 fixture 재사용


class RecPage(FakePage):
    """띄운 확인 창을 기록하는 가짜 페이지."""

    def __init__(self):
        self.dialogs = []

    def show_dialog(self, d):
        self.dialogs.append(d)

    def pop_dialog(self):
        pass


def _all(control, out=None, seen=None):
    out = [] if out is None else out
    seen = seen if seen is not None else set()
    if control is None or id(control) in seen:
        return out
    seen.add(id(control))
    out.append(control)
    for attr in ("content", "controls", "tabs", "actions", "title"):
        child = getattr(control, attr, None)
        for c in (child if isinstance(child, list) else [child]):
            if isinstance(c, ft.BaseControl):
                _all(c, out, seen)
    return out


def _button(root, text):
    for c in _all(root):
        if isinstance(c, (ft.FilledButton, ft.OutlinedButton, ft.TextButton)) and text in str(getattr(c, "content", "") or ""):
            return c
    raise AssertionError(f"버튼 없음: {text}")


def _click(btn):
    btn.on_click(None)


@pytest.fixture
def camps():
    seed_if_empty()
    a = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="첫 글 메모")
    b = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="둘째 글 메모")
    repo.update_campaign(b["id"], status="draft", title="둘째 글", content="본문입니다.")
    return a, b


def test_delete_dialog_offers_archive_and_delete(camps):
    from flet_app.dialogs import confirm_delete_campaign
    a, b = camps
    page, done = RecPage(), []
    confirm_delete_campaign(page, repo.get_campaign(a["id"]), lambda: done.append(1))
    _click(_button(page.dialogs[-1], "보관"))
    assert repo.get_campaign(a["id"])["archived"] and done          # 보관: 지우지 않음
    confirm_delete_campaign(page, repo.get_campaign(b["id"]), lambda: done.append(2))
    assert repo.get_campaign(b["id"]) is not None                   # 창만 띄우고 아직 안 지움
    _click(_button(page.dialogs[-1], "삭제"))
    assert repo.get_campaign(b["id"]) is None


def test_workbench_trash_icon_asks_first(camps):
    from flet_app.views import workbench_view
    a, b = camps
    page = RecPage()
    root = workbench_view.build(page, AppState(pending_workbench_campaign_id=b["id"]))
    trash = next(c for c in _all(root) if isinstance(c, ft.IconButton) and c.icon == ft.Icons.DELETE_OUTLINE)
    trash.on_click(None)
    assert page.dialogs and repo.get_campaign(b["id"]) is not None


def test_screens_share_the_current_post(camps):
    from flet_app.views import workbench_view
    a, b = camps
    state = AppState(pending_workbench_campaign_id=b["id"])
    workbench_view.build(RecPage(), state)
    assert state.current_campaign_id == b["id"]
    # 메뉴를 옮겼다 돌아오면(지정 없음) 최근 글이 아니라 하던 글
    workbench_view.build(RecPage(), state)
    assert state.current_campaign_id == b["id"]


def test_generation_notice_shows_once_at_top(camps):
    from flet_app.views import workbench_view
    a, b = camps
    state = AppState(pending_workbench_campaign_id=b["id"])
    state.notices[b["id"]] = {"text": "✅ 만들었습니다: 블로그, 카드뉴스 5장", "cards": True}
    root = workbench_view.build(RecPage(), state)
    texts = [c.value for c in _all(root) if isinstance(c, ft.Text) and isinstance(c.value, str)]
    assert any("만들었습니다: 블로그" in t for t in texts)
    _button(root, "카드·쇼츠에서 보기")
    assert b["id"] not in state.notices                              # 한 번 보여 주면 지움


def test_regenerate_asks_before_overwriting(camps):
    from flet_app.views import workbench_view
    a, b = camps
    page = RecPage()
    root = workbench_view.build(page, AppState(pending_workbench_campaign_id=b["id"]))
    _click(_button(root, "블로그만 다시 만들기"))
    assert page.dialogs and "다시 만들" in str(page.dialogs[-1].title.value)


def test_unsaved_edits_are_offered_for_saving_before_leaving(camps):
    from flet_app.views import workbench_view
    a, b = camps
    page, state = RecPage(), AppState(pending_workbench_campaign_id=b["id"])
    workbench_view.build(page, state)
    went = []
    state.before_leave(lambda: went.append(1))
    assert went == [1] and not page.dialogs                          # 고친 것이 없으면 바로 이동
    name, dirty, save = next(g for g in page._wb_guards if g[0] == "블로그 본문·태그")
    body = next(c for c in _all(workbench_view.build(page, state)) if isinstance(c, ft.TextField) and c.value == "본문입니다.")
    body.value = "고친 본문입니다."
    state.before_leave(lambda: went.append(2))
    assert went == [1] and page.dialogs                              # 묻는 창
    _click(_button(page.dialogs[-1], "저장하고 이동"))
    assert went == [1, 2] and repo.get_campaign(b["id"])["content"] == "고친 본문입니다."


def test_display_title_never_shows_internal_id():
    from flet_app.theme import display_title
    assert display_title({"title": "제목"}) == "제목"
    assert display_title({"memo": "\n첫 줄 메모\n둘째"}) == "✎ 첫 줄 메모"
    assert display_title({"id": "5b6ce12dabc", "created_at": "2026-11-10 07:21:41"}) == "(제목 없음 · 2026-11-10)"
    assert display_title({"title": "가" * 50}, 10).endswith("…")


def test_cards_only_generation_updates_status(camps, monkeypatch):
    from flet_app import outputs
    a, b = camps
    seen = []
    real = outputs._make_cards

    def spy(cid, *args, **kw):
        seen.append(repo.get_campaign(cid)["status"])
        return real(cid, *args, **kw)
    monkeypatch.setattr(outputs, "_make_cards", spy)
    outputs.run_outputs(a["id"], ["cards"], use_ai=False)
    assert seen == ["processing"] and repo.get_campaign(a["id"])["status"] == "draft"
    # 실패하면 '실패'로 남는다(소재 대기로 숨지 않음)
    c = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="")
    with pytest.raises(ValueError):
        outputs.run_outputs(c["id"], ["cards"], use_ai=False)
    assert repo.get_campaign(c["id"])["status"] == "failed"
    # 이미 게시한 글은 카드를 다시 만들어도 상태를 되돌리지 않는다
    repo.mark_published(b["id"])
    outputs.run_outputs(b["id"], ["cards"], use_ai=False)
    assert repo.get_campaign(b["id"])["status"] == "published"


def test_default_shorts_length_is_shared(camps):
    from flet_app import outputs
    assert outputs.default_shorts_seconds() == 45
    outputs.save_default_shorts_seconds(30)
    assert outputs.default_shorts_seconds() == 30
    outputs.save_default_shorts_seconds(99)
    assert outputs.default_shorts_seconds() == 45


def test_reset_also_clears_exports(tmp_path, monkeypatch):
    import os
    from core import library
    from cards import paths
    monkeypatch.setattr(paths, "EXPORTS_DIR", str(tmp_path))
    os.makedirs(tmp_path / "cards" / "x")
    (tmp_path / "cards" / "x" / "card_01.png").write_bytes(b"1234")
    (tmp_path / "keep.txt").write_text("남김")
    assert library.exports_usage() == 4
    assert library.clear_exports() == 4 and not (tmp_path / "cards").exists() and (tmp_path / "keep.txt").exists()


def test_publish_checks_gate_the_queue(camps):
    from flet_app.views import workbench_view
    a, b = camps
    repo.update_campaign(b["id"], guardrail_report={"compliance_pass": False, "score": 60, "llm_issues": ["효과 단정"]})
    checks = workbench_view.publish_checks(repo.get_campaign(b["id"]))
    assert any(lv == "warn" and "검수" in t for lv, t in checks)
    page = RecPage()
    root = workbench_view.build(page, AppState(pending_workbench_campaign_id=b["id"]))
    texts = " ".join(c.value for c in _all(root) if isinstance(c, ft.Text) and isinstance(c.value, str))
    assert "게시 전 확인 — 고칠 것 1건" in texts
    queue = _button(root, "네이버 게시 대기열로")
    queue.on_click(None)
    assert page.dialogs and repo.get_campaign(b["id"])["status"] != "ready_to_publish"    # 묻고, 아직 안 넣음
    # 검수 통과 글은 바로 들어간다
    repo.update_campaign(b["id"], guardrail_report={"compliance_pass": True, "score": 95})
    assert not [1 for lv, _ in workbench_view.publish_checks(repo.get_campaign(b["id"])) if lv == "warn"]


def test_brand_kit_asks_before_losing_edits(camps):
    from flet_app.views import brand_kit_view
    page, state = RecPage(), AppState()
    root = brand_kit_view.build(page, state)
    went = []
    state.before_leave(lambda: went.append(1))
    assert went == [1] and not page.dialogs                          # 고친 것이 없으면 바로 이동
    persona = next(c for c in _all(root) if isinstance(c, ft.TextField) and c.label == "브랜드 페르소나")
    persona.value = (persona.value or "") + " 수정"
    state.before_leave(lambda: went.append(2))
    assert went == [1] and page.dialogs
    _click(_button(page.dialogs[-1], "저장하고 이동"))
    assert went == [1, 2] and repo.get_brand_kit(state.editing_brand_kit_id)["persona"].endswith(" 수정")
