"""Naver Blog hashtag generator.

Naver's [발행] popup tag field just wants a flat list of search keywords —
no caption, no character limit, no hook — which makes this the simplest of
the three hashtag writers (compare instagram_caption_writer.py, which needs
a hook+caption, and x_thread_writer.py, which needs a whole thread).

Used by the single unified pipeline (ai_workers/content_writer.py). The
발행 popup itself can't be driven by Playwright, so pages/05_naver_publish.py
just displays these for the marketer to copy/paste at publish time.
"""
from __future__ import annotations

import json
import re

from ai_workers.multi_llm_router import generate_text

HASHTAG_SYSTEM_PROMPT = (
    "당신은 네이버 블로그 SEO 전문가입니다. 아래 블로그 글의 제목과 본문을 분석해서, "
    "네이버 블로그 [발행] 팝업의 태그 입력란에 등록할 검색 노출용 해시태그를 7~12개 "
    "추천하세요. 다음 네 층을 골고루 섞으세요: ①브랜드(온자람 등) ②지역·서비스(예: 창원심리상담) "
    "③이 글의 프로그램·기관·주제 ④기법·대상(예: 교류분석, 부모교육, 청년). 실제 검색에 쓰일 법한 "
    "구체적인 단어를 우선하고, 글에 나오지 않은 기관·프로그램은 넣지 마세요. 이미 사회적기업 인증을 "
    "받은 회사이므로 '예비사회적기업'은 쓰지 마세요. 반드시 아래 JSON 형식으로만 응답하고 다른 설명은 "
    "포함하지 마세요:\n"
    '{"hashtags": ["#태그1", "#태그2", ...]}'
)


# 더는 맞지 않는 태그 — 프롬프트에서 막아도 모델이 쓰면 여기서 걸러 냅니다.
STALE_TAGS = ("예비사회적기업",)


def write_naver_hashtags(title: str, content: str, target_keywords: list[str], vendor: str,
                         known_tags: list[str] | None = None) -> list[str]:
    """Returns a list of "#tag" strings. Best-effort — callers must not let a
    failure here fail the whole draft, since these are a copy/paste aid for
    the publish popup, not the post body itself.

    Only this post's targets are offered, never the brand's whole pool: shown
    the pool 'for reference', the model tagged a special-class art lesson
    #DIY키트 #업사이클링키트, and a brand whose pool leads with 답례품 got
    gift tags on posts that never mention a gift.
    """
    keyword_hint = (
        f"\n\n[이 글이 다루는 검색 키워드 - 태그에 포함] {', '.join(target_keywords)}"
        if target_keywords else ""
    )
    known = [t for t in (known_tags or []) if not any(x in t for x in STALE_TAGS)][:20]
    if known:   # 예전에 쓴 태그 중 이 글에 맞는 것을 우선 — 같은 주제가 같은 태그로 모이게
        keyword_hint += f"\n\n[이 블로그가 예전에 쓴 태그 — 글에 맞는 것은 우선 사용] {', '.join(known)}"
    prompt = f"[제목]\n{title}\n\n[본문]\n{content[:3000]}{keyword_hint}"
    raw = generate_text(vendor=vendor, prompt=prompt, system=HASHTAG_SYSTEM_PROMPT, max_tokens=400, note="naver-hashtags")
    try:
        cleaned = re.sub(r"```json\s*|```\s*$", "", raw.strip())
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else {}
        tags = parsed.get("hashtags") or []
        tags = [t if str(t).startswith("#") else f"#{t}" for t in tags]
        return [t for t in tags if not any(stale in t for stale in STALE_TAGS)]
    except Exception:
        return []
