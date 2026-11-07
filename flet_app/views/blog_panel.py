"""대시보드의 '📰 내 블로그 현황·제안' 패널.

공개 RSS(`core/blog_feed.py`)를 가져와 발행 공백, 시즌 주제 제안, 낡았을 수 있는 안내글을 보여 줍니다(키워드 조사는 설정 → 네이버 API).
시즌 주제의 [글 만들기]는 메모가 채워진 새 글을 만들어 워크벤치로 보냅니다.
"""
from __future__ import annotations

import flet as ft

from ai_workers import post_types
from core import blog_feed, blog_insight, repo

from flet_app.components.collapsible import collapsible
from flet_app.state import AppState
from flet_app.theme import BRAND_COLORS, fs


def build(page: ft.Page, scale: float, state: AppState, refresh) -> ft.Control:
    kit = repo.get_brand_kit()
    blog_id = (kit.get("naver_blog_id") or "").strip()
    feed = blog_feed.load()
    posts = feed["posts"]
    status = ft.Text("", size=fs(12, scale))
    muted = BRAND_COLORS["text_muted"]

    def on_fetch(e: ft.Event) -> None:
        status.value = "가져오는 중…"
        status.color = muted
        status.update()

        def work() -> None:
            try:
                got = blog_feed.fetch(blog_id)
                status.value = f"✅ 글 {len(got)}개를 가져왔습니다."
                status.color = "#1B6E3C"
                refresh(True)
            except Exception as exc:  # noqa: BLE001 — 네트워크·형식 오류는 그대로 안내
                status.value = f"❌ 가져오지 못했습니다: {exc}"
                status.color = "#B3261E"
                try:
                    status.update()
                except Exception:  # noqa: BLE001
                    pass

        page.run_thread(work)

    head = [
        ft.Text("📰 내 블로그 현황·제안", size=fs(14, scale), weight=ft.FontWeight.BOLD),
        ft.Row([
            ft.FilledButton("🔄 내 블로그 글 가져오기", on_click=on_fetch, disabled=not blog_id),
            ft.Text(f"blog.naver.com/{blog_id} 공개 RSS · 로그인 필요 없음" if blog_id else
                    "브랜드 킷에 네이버 블로그 ID를 먼저 입력하세요.", size=fs(11, scale), color=muted),
        ], spacing=10),
        status,
    ]
    if not posts:
        return ft.Container(content=ft.Column(head, spacing=6), bgcolor="#F4F6F4", padding=12, border_radius=8)

    gap = blog_feed.publishing_gap(posts)
    cats = ", ".join(f"{c} {n}" for c, n in blog_feed.categories(posts)[:6])
    rows: list[ft.Control] = [ft.Text(f"가져온 글 {len(posts)}개 · {feed['fetched_at']} · 카테고리: {cats}", size=fs(11, scale), color=muted)]
    if gap["last_days"] is not None:
        avg = f" (최근 1년 평균 {gap['avg_interval']}일 간격)" if gap["avg_interval"] else ""
        rows.append(ft.Text(("⏳ " if gap["warn"] else "🗓️ ") + f"마지막 글 이후 {gap['last_days']}일{avg}" +
                            (" — 발행이 뜸합니다. 아래 주제로 한 편 쓰는 것을 권합니다." if gap["warn"] else ""),
                            size=fs(12, scale), color="#8A6D3B" if gap["warn"] else None))

    def make_post(item: dict):
        def handler(e: ft.Event) -> None:
            c = repo.insert_campaign("manual", memo=item["memo"])
            repo.update_campaign(c["id"], post_type=item["post_type"])
            state.pending_workbench_campaign_id = c["id"]
            if state.navigate_to_workbench:
                state.navigate_to_workbench()
        return handler

    sugg = []
    for it in blog_insight.season_suggestions(posts, limit=0):
        line = [ft.Text(f"[{it['when']}] {it['topic']} · {post_types.label_of(it['post_type'])}", size=fs(12, scale), expand=True)]
        if it["similar"]:
            line.append(ft.Text(f"♻️ 1년 안에 비슷한 글: {it['similar']['title'][:28]}…", size=fs(10, scale), color="#8A6D3B"))
        line.append(ft.OutlinedButton("글 만들기", on_click=make_post(it)))
        sugg.append(ft.Row(line, spacing=8))
    rows += collapsible("🌱 이번·다음 달 주제 제안", ft.Column(sugg, spacing=6), initially_open=True)

    stale = blog_feed.stale_notices(posts)
    if stale:
        lines = [ft.Row([ft.Text(f"{p['title'][:40]} · {p['age_days']}일 전 — {p['reason']}", size=fs(11, scale), expand=True),
                         ft.TextButton("열기", on_click=lambda e, u=p["link"]: page.run_task(ft.UrlLauncher().launch_url, u))])
                 for p in stale[:8]]
        rows += collapsible(f"🧹 낡았을 수 있는 안내·소개글 {len(stale)}개", ft.Column(lines, spacing=4))

    rows.append(ft.Text("🔍 키워드 검색량·경쟁 조사는 설정 → 네이버 API 탭에서 합니다.", size=fs(11, scale), color=muted))
    return ft.Container(content=ft.Column(head + rows, spacing=6), bgcolor="#F4F6F4", padding=12, border_radius=8)
