"""블로그 분석을 바탕으로 한 제안 — 시즌 주제, 긴 꼬리 키워드 후보.

시즌 주제는 온자람 블로그에 실제로 반응·활동이 있던 시기(신학기, 방학, 지역 행사, 바우처 안내 등)와 일반적인 학사·계절 흐름에서
뽑은 **주제 제안**일 뿐이며, 사실(날짜·기관·숫자)은 담지 않습니다. 메모에는 담당자가 실제 내용을 채워야 합니다.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from core import blog_feed

# 월 → [(주제, 글 유형, 메모 시작 문구)]
SEASON_TOPICS: Dict[int, List[tuple]] = {
    1: [("새해 마음 돌봄 계획", "column", "새해를 시작하며 마음을 돌보는 작은 계획을 이야기합니다."),
        ("지원사업·바우처 안내 갱신", "notice", "올해 이용할 수 있는 지원 제도와 신청 방법을 안내합니다. (최신 조건은 담당자가 확인해 채우세요)")],
    2: [("신학기 증후군 극복", "column", "새 학기를 앞둔 아이와 부모의 긴장을 어떻게 살필지 이야기합니다.")],
    3: [("신학기 적응·집단상담 모집", "notice", "새 학기 집단상담 프로그램 모집 안내입니다. (일정·대상·신청 방법을 채우세요)"),
        ("아이의 첫 등교, 부모의 마음", "column", "입학·진급 시기 부모가 느끼는 마음을 이야기합니다.")],
    4: [("봄철 마음 날씨 살피기", "column", "계절이 바뀔 때 흔들리는 마음을 살피는 방법을 이야기합니다.")],
    5: [("가정의 달, 부모와 자녀의 소통", "column", "가족 안에서 마음을 주고받는 작은 습관을 이야기합니다.")],
    6: [("1학기 마무리 학교 프로그램 후기", "review", "학기 중 진행한 집단 프로그램 현장 후기입니다. (활동 내용을 채우세요)"),
        ("숏폼과 쉼, 마음 쉼표", "column", "바쁜 일상에서 진짜 쉼을 찾는 방법을 이야기합니다.")],
    7: [("여름방학 프로그램 모집", "notice", "방학 프로그램 모집 안내입니다. (일정·대상·신청 방법을 채우세요)")],
    8: [("방학 캠프·클래스 현장 후기", "review", "여름 프로그램 현장 후기입니다. (활동 내용을 채우세요)")],
    9: [("지역사회 행사·봉사 참여 후기", "review", "지역 행사 참여 후기입니다. (활동 내용을 채우세요)"),
        ("명절 연휴 뒤 마음 돌봄", "column", "명절 전후의 마음 부담을 살피는 방법을 이야기합니다.")],
    10: [("가을 지역 행사 체험 부스 후기", "review", "체험 부스 운영 후기입니다. (활동 내용을 채우세요)"),
         ("가을 감정 돌봄", "column", "날씨가 선선해지며 올라오는 감정을 살피는 방법을 이야기합니다.")],
    11: [("시험·연말 스트레스 다루기", "column", "시험과 연말에 쌓이는 긴장을 푸는 방법을 이야기합니다.")],
    12: [("한 해 돌아보기, 나를 칭찬하기", "column", "한 해를 정리하며 스스로를 돌아보는 방법을 이야기합니다."),
         ("내년 프로그램 안내", "notice", "내년 프로그램 안내입니다. (일정·대상·신청 방법을 채우세요)")],
}

# 지역·대상·주제를 조합한 긴 꼬리 키워드 틀 — 블로그에서 이미 다룬 주제들입니다.
LONGTAIL_TOPICS = ["청소년 집단상담", "신학기 증후군", "교류분석 부모교육", "청년 심리상담", "기관 출강 특강", "초등학생 자존감"]


def season_suggestions(posts: List[Dict], today: Optional[date] = None, limit: int = 4) -> List[Dict]:
    """이번 달·다음 달 주제 제안. 최근 1년 안에 비슷한 글이 있으면 `similar`에 그 글을 담습니다(중복 주의)."""
    today = today or date.today()
    nxt = today.month % 12 + 1
    recent = [p for p in posts if blog_feed._days(p.get("date"), today) is not None and blog_feed._days(p["date"], today) <= 365]
    out = []
    for month, tag in ((today.month, "이번 달"), (nxt, "다음 달")):
        for topic, ptype, memo in SEASON_TOPICS.get(month, []):
            sim = blog_feed.related(topic, recent, limit=1)
            out.append({"when": tag, "month": month, "topic": topic, "post_type": ptype, "memo": memo,
                        "similar": sim[0] if sim else None})
    return out[:limit] if limit else out


def longtail_seeds(brand_kit: Optional[dict], posts: List[Dict], limit: int = 20) -> List[str]:
    """키워드 점검 후보: 킷의 SEO 키워드 + 블로그에서 다룬 주제 × 지역 + 자주 쓴 태그."""
    seeds: List[str] = []
    seeds += [k for k in (brand_kit or {}).get("seo_keywords", [])]
    region = "창원"
    seeds += [f"{region} {t}" for t in LONGTAIL_TOPICS]
    seeds += [t.lstrip("#") for t in blog_feed.tag_dictionary(posts, 10)]
    out, seen = [], set()
    for s in seeds:
        key = s.replace(" ", "")
        if s and key not in seen and key != "온자람":
            seen.add(key)
            out.append(s)
    return out[:limit]


def unused_seeds(seeds: List[str], posts: List[Dict]) -> List[str]:
    """아직 태그·제목에 쓴 적 없는 후보(공략할 빈자리)."""
    used = " ".join(p.get("title", "") + " " + " ".join(p.get("tags", [])) for p in posts).replace(" ", "")
    return [s for s in seeds if s.replace(" ", "") not in used]


def measure(seeds: List[str], limit: int = 12) -> Dict:
    """네이버 키워드 측정(선택 기능)이 켜져 있을 때만 후보를 측정합니다. 꺼져 있으면 이유를 돌려줍니다."""
    from ai_workers import keyword_research as kr
    if not kr.enabled() or kr.level() < 1:
        return {"ok": False, "rows": [], "note": "설정 → 🔍 네이버 API에서 키워드 측정을 켜고 키를 넣으면 검색량·경쟁도를 볼 수 있습니다."}
    try:
        rows = kr.rank_keywords(seeds[:limit], include_trend=False)
    except Exception as exc:  # noqa: BLE001 — 네트워크·키 오류는 화면에서 안내
        return {"ok": False, "rows": [], "note": f"측정하지 못했습니다: {exc}"}
    return {"ok": True, "rows": rows, "note": ""}
