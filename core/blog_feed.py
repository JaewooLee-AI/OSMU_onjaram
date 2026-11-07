"""내 네이버 블로그의 공개 RSS를 가져와 분석하는 도구 — 로그인이 필요 없습니다.

네이버 블로그는 `https://rss.blog.naver.com/<블로그ID>.xml`로 최근 글 50개의 제목·카테고리·태그·요약을 공개합니다.
이 정보로 (1) 같은 주제를 또 쓰려는지 알려 주고, (2) 예전에 쓴 태그를 태그 사전으로 쓰고, (3) 발행 공백을 알리고,
(4) 오래된 안내글을 찾습니다. 본문 전체가 아니라 RSS가 주는 요약만 씁니다. 가져온 결과는 앱 상태(DB)에 저장해
네트워크 없이도 다시 볼 수 있습니다.

네트워크는 `fetch()`에서만 씁니다. 나머지 함수는 가져온 목록을 받아 계산만 하므로 시험할 수 있습니다.
"""
from __future__ import annotations

import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional

from core import repo

STATE_KEY = "blog_feed"
RSS_URL = "https://rss.blog.naver.com/{blog_id}.xml"
STALE_TAGS = ("예비사회적기업",)

# 안내·모집 성격의 제목에 흔한 말 — 시간이 지나면 내용이 낡습니다.
NOTICE_WORDS = ("모집", "안내", "신청", "바우처", "지원사업", "이전")
NOTICE_STALE_DAYS = 180
# 소개·연혁처럼 한 번 쓰고 두는 글의 카테고리 — 더 천천히 낡습니다.
EVERGREEN_CATEGORIES = ("온자람서비스", "History", "온자람파트너", "오시는 길", "사회적기업 온자람")
EVERGREEN_STALE_DAYS = 365


def _clean(text: str) -> str:
    text = re.sub(r"<img[^>]*>", "", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse(xml_text: str) -> List[Dict]:
    """RSS 문자열 → 글 목록(최신순). 날짜는 'YYYY-MM-DD'."""
    root = ET.fromstring(xml_text)
    posts: List[Dict] = []
    for item in root.iter("item"):
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            when = ""
        tags = [t.strip() for t in (item.findtext("tag") or "").split(",") if t.strip()]
        link = (item.findtext("link") or "").split("?")[0]
        posts.append({
            "title": _clean(item.findtext("title") or ""),
            "category": _clean(item.findtext("category") or ""),
            "date": when,
            "link": link,
            "tags": tags,
            "summary": _clean(item.findtext("description") or "")[:400],
        })
    return posts


def fetch(blog_id: str, timeout: float = 15.0, opener=None) -> List[Dict]:
    """공개 RSS를 가져와 저장합니다. 실패하면 예외(화면에서 안내)."""
    blog_id = (blog_id or "").strip()
    if not blog_id:
        raise ValueError("브랜드 킷에 네이버 블로그 ID가 없습니다.")
    req = urllib.request.Request(RSS_URL.format(blog_id=blog_id), headers={"User-Agent": "Mozilla/5.0"})
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    posts = parse(text)
    repo.set_app_state(STATE_KEY, {"blog_id": blog_id, "fetched_at": datetime.now().isoformat(timespec="seconds"), "posts": posts})
    return posts


def load() -> Dict:
    """마지막으로 가져온 결과 {blog_id, fetched_at, posts}. 없으면 빈 값."""
    state = repo.get_app_state(STATE_KEY) or {}
    return {"blog_id": state.get("blog_id") or "", "fetched_at": state.get("fetched_at") or "", "posts": state.get("posts") or []}


# --- 분석 -------------------------------------------------------------------

_STOP = {"프로그램", "창원", "심리상담", "온자람", "주식회사", "후기", "현장", "안내", "대한", "위한", "함께", "이번", "우리"}


def _tokens(text: str) -> set:
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", text or "")
    out = set()
    for w in words:
        out.add(w)
        if len(w) >= 4:                 # '신학기증후군' 같은 붙여 쓴 말은 앞뒤 두 글자씩도 단서로 쓴다
            out.update({w[:2], w[-2:]})
    return {w for w in out if w not in _STOP}


def related(text: str, posts: List[Dict], limit: int = 3, min_shared: int = 2) -> List[Dict]:
    """`text`(제목·메모)와 겹치는 낱말이 많은 기존 글. 겹침이 `min_shared`개 미만이면 뺍니다."""
    mine = _tokens(text)
    scored = []
    for p in posts:
        theirs = _tokens(p.get("title", "") + " " + " ".join(p.get("tags", [])))
        shared = len(mine & theirs)
        if shared >= min_shared:
            scored.append((shared, p))
    scored.sort(key=lambda x: -x[0])
    return [dict(p, shared=n) for n, p in scored[:limit]]


def tag_dictionary(posts: List[Dict], limit: int = 20) -> List[str]:
    """예전에 많이 쓴 태그(낡은 태그 제외), 많이 쓴 순."""
    counter: Counter = Counter()
    for p in posts:
        counter.update(t for t in p.get("tags", []) if not any(s in t for s in STALE_TAGS))
    return [t for t, _ in counter.most_common(limit)]


def categories(posts: List[Dict]) -> List[tuple]:
    return Counter(p.get("category") or "(없음)" for p in posts).most_common()


def _days(iso: str, today: date) -> Optional[int]:
    try:
        return (today - date.fromisoformat(iso)).days
    except (TypeError, ValueError):
        return None


def publishing_gap(posts: List[Dict], today: Optional[date] = None) -> Dict:
    """마지막 글 이후 며칠인지, 최근 1년 평균 간격과 비교해 공백이 큰지."""
    today = today or date.today()
    days = sorted(d for d in (_days(p.get("date"), today) for p in posts) if d is not None)
    if not days:
        return {"last_days": None, "avg_interval": None, "warn": False}
    last = days[0]
    recent = [d for d in days if d <= 365]
    avg = None
    if len(recent) >= 3:
        span = recent[-1] - recent[0]
        avg = round(span / (len(recent) - 1), 1)
    warn = last > 45 or bool(avg and last > avg * 1.5 and last > 21)
    return {"last_days": last, "avg_interval": avg, "warn": warn}


def stale_notices(posts: List[Dict], today: Optional[date] = None) -> List[Dict]:
    """낡았을 수 있는 안내·소개글. 안내·모집 성격은 180일, 소개·연혁 성격은 365일이 지난 글."""
    today = today or date.today()
    out = []
    for p in posts:
        age = _days(p.get("date"), today)
        if age is None:
            continue
        title, cat = p.get("title", ""), p.get("category", "")
        if cat in EVERGREEN_CATEGORIES and age > EVERGREEN_STALE_DAYS:
            out.append({**p, "age_days": age, "reason": "소개·연혁 글 — 내용이 그대로인지 확인"})
        elif any(w in title for w in NOTICE_WORDS) and age > NOTICE_STALE_DAYS:
            out.append({**p, "age_days": age, "reason": "안내·모집 글 — 기한·조건이 지났는지 확인"})
    return sorted(out, key=lambda p: -p["age_days"])
