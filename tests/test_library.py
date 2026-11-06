"""📚 보관함 — 검색·필터·보관·라벨·용량 정리·화면."""
import os
from datetime import datetime, timedelta

import flet as ft
import pytest

from core import library, repo
from core.brand_seed import seed_if_empty
from flet_app.state import AppState


@pytest.fixture
def posts():
    seed_if_empty()
    out = {}
    out["a"] = repo.insert_campaign(source_type="manual", status="draft", memo="청년 마음돌봄 특강")["id"]
    repo.update_campaign(out["a"], title="청년 마음돌봄 특강 안내", content="본문 가나다", brand_kit_name="공감·회복 (B2C)")
    out["b"] = repo.insert_campaign(source_type="manual", status="draft", memo="기관 EAP")["id"]
    repo.update_campaign(out["b"], title="기관 EAP 프로그램", brand_kit_name="전문·신뢰 (B2B·B2G)")
    out["c"] = repo.insert_campaign(source_type="manual", status="draft", memo="수면 팁")["id"]
    repo.update_campaign(out["c"], title="수면 습관 3가지", content="잠들기 전 화면 멀리하기")
    repo.mark_published(out["c"], "https://blog.naver.com/x/9")
    return out


def test_search_filters_sort_and_paging(posts):
    rows, total = repo.search_campaigns(query="마음돌봄")
    assert [c["id"] for c in rows] == [posts["a"]] and total == 1
    assert repo.search_campaigns(query="화면 멀리")[1] == 1                       # 본문도 검색
    assert repo.search_campaigns(status="published")[1] == 1
    assert repo.search_campaigns(kit="전문·신뢰 (B2B·B2G)")[0][0]["id"] == posts["b"]
    assert repo.search_campaigns(has="blog")[1] == 2 and repo.search_campaigns(has="cards")[1] == 0
    rows, total = repo.search_campaigns(sort="title", limit=2, offset=0)
    assert total == 3 and len(rows) == 2
    assert repo.search_campaigns(sort="title", limit=2, offset=2)[0][0]["title"] is not None


def test_archive_hides_from_work_lists_but_keeps_data_and_can_restore(posts):
    assert repo.set_archived([posts["b"]], True) == 1
    assert posts["b"] not in [c["id"] for c in repo.list_campaigns()]              # 작업 목록·대시보드에서 빠진다
    assert posts["b"] not in [c["id"] for c in repo.recent_campaigns(15)]
    assert repo.campaign_status_counts().get("draft") == 1
    assert repo.get_campaign(posts["b"])["title"] == "기관 EAP 프로그램"            # 데이터는 그대로
    assert repo.search_campaigns(archived="yes")[0][0]["id"] == posts["b"]
    assert repo.search_campaigns(archived="all")[1] == 3
    repo.set_archived([posts["b"]], False)
    assert posts["b"] in [c["id"] for c in repo.list_campaigns()]


def test_recent_campaigns_limits_and_keeps_the_opened_one(posts):
    ids = [repo.insert_campaign(source_type="manual", status="draft", memo=f"m{i}")["id"] for i in range(20)]
    recent = repo.recent_campaigns(5)
    assert len(recent) == 5
    old = posts["c"]                                    # 게시 완료 글은 뒤쪽이라 5개 안에 안 든다
    assert old not in [c["id"] for c in repo.recent_campaigns(5)]
    assert old in [c["id"] for c in repo.recent_campaigns(5, include=old)]          # 열려 있는 글은 항상 포함


def test_labels_clean_and_filter(posts):
    assert repo.set_labels(posts["a"], [" 11월  특강 ", "청년", "청년", '"x"', ""]) == ["11월 특강", "청년", "x"]
    assert repo.all_labels() == ["11월 특강", "x", "청년"]
    assert repo.search_campaigns(label="청년")[0][0]["id"] == posts["a"] and repo.search_campaigns(label="없음")[1] == 0


def test_purge_frees_only_rebuildable_files_and_never_ai_images(posts, tmp_path):
    from core.db import DATA_DIR
    cid = posts["a"]
    card_dir = DATA_DIR / "exports" / "cards" / cid / "20261106-000000"
    ai_dir = DATA_DIR / "exports" / "cards" / cid / "assets" / "ai"
    video = DATA_DIR / "exports" / "shorts" / cid / "final_shorts.mp4"
    for d in (card_dir, ai_dir, video.parent):
        d.mkdir(parents=True)
    (card_dir / "slide_01.png").write_bytes(b"x" * 1000)
    (ai_dir / "G1.jpg").write_bytes(b"y" * 2000)
    video.write_bytes(b"z" * 5000)
    repo.update_campaign(cid, card_export_dir=str(card_dir), shorts_video_path=str(video))
    u = library.disk_usage(repo.get_campaign(cid))
    assert (u["cards"], u["ai_images"], u["video"]) == (1000, 2000, 5000)
    assert library.purge(cid, cards=True, video=False) == 1000
    c = repo.get_campaign(cid)
    assert c["card_export_dir"] is None and not card_dir.exists() and c["shorts_video_path"] == str(video) and video.exists()
    assert library.purge(cid, cards=False, video=True) == 5000 and not video.exists()
    assert (ai_dir / "G1.jpg").exists()                                              # 돈 낸 AI 이미지는 그대로
    assert repo.get_campaign(cid)["title"] == "청년 마음돌봄 특강 안내"                # 글도 그대로


def test_bulk_archive_candidates_are_published_over_30_days_ago(posts):
    assert library.published_older_than(30) == []
    old = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")
    repo.update_campaign(posts["c"], published_at=old)
    assert [c["id"] for c in library.published_older_than(30)] == [posts["c"]]


def test_library_view_builds_filters_and_acts(posts):
    from flet_app.views import library_view
    state = AppState()
    opened = []
    state.navigate_to_workbench = lambda: opened.append("work")
    state.navigate_to_studio = lambda: opened.append("studio")
    page = type("P", (), {"web": True, "__getattr__": lambda self, n: (lambda *a, **k: None)})()
    root = library_view.build(page, state)

    def collect(control, kind, out=None):
        out = [] if out is None else out
        if isinstance(control, kind):
            out.append(control)
        for attr in ("content", "controls", "items", "actions"):
            child = getattr(control, attr, None)
            for c in (child if isinstance(child, list) else [child]):
                if isinstance(c, ft.BaseControl):
                    collect(c, kind, out)
        return out

    buttons = collect(root, ft.TextButton)
    assert any("🃏 카드·쇼츠" == b.content for b in buttons)
    next(b for b in buttons if b.content == "✍️ 워크벤치").on_click(None)
    assert opened == ["work"] and state.pending_workbench_campaign_id in posts.values()
    assert any("🔗 네이버 글" == b.content for b in buttons)                          # 게시한 글에만
    assert len(collect(root, ft.PopupMenuButton)) == 3


def test_naver_links_use_direct_url_buttons_not_launch_handlers(posts):
    """핸들러에서 launch_url을 부르면 브라우저가 팝업으로 보고 막을 수 있다 — 링크는 url= 속성으로 직접 열게 한다."""
    from flet_app.views import dashboard_view, library_view
    page = type("P", (), {"web": True, "__getattr__": lambda self, n: (lambda *a, **k: None)})()

    def collect(control, kind, out=None):
        out = [] if out is None else out
        if isinstance(control, kind):
            out.append(control)
        for attr in ("content", "controls", "items", "actions"):
            child = getattr(control, attr, None)
            for c in (child if isinstance(child, list) else [child]):
                if isinstance(c, ft.BaseControl):
                    collect(c, kind, out)
        return out

    lib = library_view.build(page, AppState())
    link = next(b for b in collect(lib, ft.TextButton) if b.content == "🔗 네이버 글")
    assert link.url == "https://blog.naver.com/x/9" and link.on_click is None
    board = dashboard_view.build(page, AppState())
    cards = [c for c in collect(board, ft.Container) if getattr(c, "url", None) == "https://blog.naver.com/x/9"]
    assert cards and cards[0].on_click is None
