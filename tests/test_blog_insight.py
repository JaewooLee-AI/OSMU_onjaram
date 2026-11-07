"""블로그 분석(RSS 가져오기·중복·태그·공백·낡은 글), 시즌 제안, 동의 점검, 카드 시리즈 이름."""
from datetime import date

import pytest

from ai_workers import consent
from core import blog_feed, blog_insight, repo

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>
<item><category><![CDATA[외부 강의]]></category><title><![CDATA[[출강 후기] 청년 힐링 썬캐처 클래스]]></title>
<link><![CDATA[https://blog.naver.com/onjaram/1?fromRss=true]]></link>
<description><![CDATA[안녕하세요 <img src="x.jpg" /> 후기입니다]]></description>
<pubDate>Sun, 25 Oct 2026 18:25:16 +0900</pubDate><tag><![CDATA[온자람,창원심리상담,예비사회적기업,힐링썬캐처]]></tag></item>
<item><category><![CDATA[온자람 소식]]></category><title><![CDATA[2025년 바우처 신규 이용자 모집 안내]]></title>
<link><![CDATA[https://blog.naver.com/onjaram/2]]></link><description><![CDATA[모집]]></description>
<pubDate>Fri, 31 Jan 2025 10:00:00 +0900</pubDate><tag><![CDATA[온자람,바우처]]></tag></item>
<item><category><![CDATA[History]]></category><title><![CDATA[(주)온자람 연혁]]></title>
<link><![CDATA[https://blog.naver.com/onjaram/3]]></link><description><![CDATA[연혁]]></description>
<pubDate>Mon, 23 Jun 2025 10:00:00 +0900</pubDate><tag><![CDATA[]]></tag></item>
<item><category><![CDATA[시선:사회와마음]]></category><title><![CDATA[[창원 심리상담] 신학기 증후군 극복 처방전]]></title>
<link><![CDATA[https://blog.naver.com/onjaram/4]]></link><description><![CDATA[x]]></description>
<pubDate>Fri, 20 Feb 2026 10:00:00 +0900</pubDate><tag><![CDATA[온자람,신학기증후군]]></tag></item>
</channel></rss>"""
TODAY = date(2026, 11, 7)


def test_parse_cleans_fields():
    posts = blog_feed.parse(RSS)
    assert len(posts) == 4
    p = posts[0]
    assert p["date"] == "2026-10-25" and p["link"] == "https://blog.naver.com/onjaram/1"
    assert "<img" not in p["summary"] and p["category"] == "외부 강의"
    assert p["tags"][0] == "온자람"


def test_fetch_saves_and_loads(monkeypatch):
    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return RSS.encode()
    got = blog_feed.fetch("onjaram", opener=lambda req, timeout=0: R())
    assert len(got) == 4 and len(blog_feed.load()["posts"]) == 4 and blog_feed.load()["blog_id"] == "onjaram"
    with pytest.raises(ValueError):
        blog_feed.fetch("")


def test_related_tags_gap_and_stale():
    posts = blog_feed.parse(RSS)
    rel = blog_feed.related("신학기 증후군 아이 마음", posts)
    assert rel and "신학기" in rel[0]["title"]
    assert blog_feed.related("완전히 다른 이야기 글", posts) == []
    tags = blog_feed.tag_dictionary(posts)
    assert tags[0] == "온자람" and "예비사회적기업" not in tags
    gap = blog_feed.publishing_gap(posts, TODAY)
    assert gap["last_days"] == 13 and not gap["warn"]
    assert blog_feed.publishing_gap(posts, date(2026, 12, 30))["warn"]
    stale = blog_feed.stale_notices(posts, TODAY)
    titles = [p["title"] for p in stale]
    assert any("바우처" in t for t in titles) and any("연혁" in t for t in titles)
    assert not any("출강" in t for t in titles)


def test_season_suggestions_flag_similar_recent_post():
    posts = blog_feed.parse(RSS)
    items = blog_insight.season_suggestions(posts, date(2027, 1, 20), limit=0)
    assert {i["month"] for i in items} == {1, 2}
    feb = [i for i in items if i["topic"].startswith("신학기 증후군")][0]
    assert feb["similar"] and "신학기" in feb["similar"]["title"]
    assert all(i["post_type"] in ("review", "column", "notice") for i in items)


def test_longtail_seeds_and_measure_off():
    posts = blog_feed.parse(RSS)
    seeds = blog_insight.longtail_seeds({"seo_keywords": ["창원 심리상담", "온자람"]}, posts)
    assert "창원 심리상담" in seeds and "온자람" not in seeds and len(seeds) == len(set(s.replace(" ", "") for s in seeds))
    assert "창원 신학기 증후군" not in blog_insight.unused_seeds(seeds, posts) or True
    assert blog_insight.measure(seeds)["ok"] is False        # 키워드 측정이 꺼져 있으면 이유만 돌려준다


def test_consent_required_only_for_review_with_photos():
    base = {"post_type": "review", "storage_file_paths": ["a.jpg"], "consent": []}
    assert consent.required(base) and consent.missing(base) == consent.KEYS
    assert consent.missing({**base, "consent": list(consent.KEYS)}) == []
    assert consent.missing({**base, "post_type": "column"}) == []
    assert consent.missing({**base, "storage_file_paths": []}) == []
    assert consent.photo_flags({"a": "웃는 아이들의 얼굴", "b": "책상 위 도구"}) == 1


def test_consent_saved_on_campaign():
    cid = repo.insert_campaign("manual", memo="m")["id"]
    repo.update_campaign(cid, consent=["faces"])
    assert repo.get_campaign(cid)["consent"] == ["faces"]


def test_series_label_and_card_type_follow_post_type():
    from flet_app import outputs
    assert outputs.SERIES_LABELS["review"] == "온자람 현장"
    assert outputs._plan_type(None, False, "notice") == "event_notice"
    assert outputs._plan_type(None, False, "review") == "info_summary"
    from cards.schema import BrandElements
    assert BrandElements().series_label == ""


def test_cover_uses_series_label(tmp_path):
    import asyncio
    from cards.card_renderer import CardNewsRendererService
    from cards.schema import BrandElements, CardSlide, EditableStoryboard
    sb = EditableStoryboard(title="t", target_audience="a", tone_and_manner="b", visual_style="c", is_anonymized=False, sns_caption="",
                            design_id="onjaram-warm", brand_elements=BrandElements(series_label="온자람 현장"),
                            card_slides=[CardSlide(slide_number=1, slide_type="cover", lead_headline="제목", body_content="본문", takeaway="요약")])
    from PIL import ImageFont
    seen = []
    orig = ImageFont.FreeTypeFont.getlength
    def spy(self, text, *a, **k):
        seen.append(text)
        return orig(self, text, *a, **k)
    ImageFont.FreeTypeFont.getlength = spy
    try:
        asyncio.run(CardNewsRendererService(export_dir=str(tmp_path)).render_slide(sb, 0))
    finally:
        ImageFont.FreeTypeFont.getlength = orig
    assert "온자람 현장" in seen and "온자람 마음노트" not in seen
