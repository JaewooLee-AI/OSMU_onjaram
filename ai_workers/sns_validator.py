"""Deterministic format checks for the Instagram, Shorts and Naver-tag outputs.

(X(트위터) 채널은 M0에서 뺐고, 트윗 길이 검사·나누기 함수도 함께 지웠습니다.)

The Naver path already follows this project's "verify, don't just instruct"
rule twice over (compliance guardrail, SEO density). The social writers did
not: `TWEET_MAX_CHARS` and the 125-character fold existed only as sentences
inside a system prompt, and nothing looked at what came back.

That gap matters more than the Naver one, because the failure is harder:
a missed keyword costs some ranking, but a 281-character tweet **cannot be
posted at all** — the marketer only finds out when X rejects the paste.

Everything here is deterministic. None of these checks needs a model: an
over-long tweet is split on sentence boundaries, an over-long hashtag list is
trimmed. Where a fix would require rewriting prose (a hook that runs past the
fold, too few hashtags), the issue is reported rather than guessed at, so the
marketer can decide — the same reason the compliance auditor explains instead
of silently rewriting.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

# Instagram collapses the caption behind "더보기" after ~125 characters or
# two lines, whichever comes first — a caption that opens with a short line
# and a line break shows even less.
IG_FOLD = 125
IG_FOLD_LINES = 2
IG_HASHTAG_MIN = 8
IG_HASHTAG_MAX = 15

# Shorts: on-screen text has to sit in the band between the top and the
# button/caption dead zones (see shorts_writer / the simulator overlay).
SHORTS_CAPTION_MAX = 20
SHORTS_TITLE_MAX = 40

# Naver's 발행 popup: the writer is asked for 7~12 tags.
NAVER_TAG_MIN = 7
NAVER_TAG_MAX = 12


def instagram_preview(caption: str) -> str:
    """The part of a caption visible before "더보기" — the single definition
    both the check below and the simulator's fold line use."""
    caption = caption or ""
    lines = caption.split("\n")
    head = "\n".join(lines[:IG_FOLD_LINES])
    return head[:IG_FOLD]

# Korean sentence enders, kept with the sentence they close.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?。？！])\s+|(?<=[다요])\.\s*")


def _split_sentences(text: str) -> List[str]:
    parts = [p.strip() for p in _SENTENCE_END_RE.split(text) if p and p.strip()]
    return parts or [text.strip()]


def validate_instagram(caption: str, hashtags: List[str]) -> Tuple[str, List[str], List[Dict]]:
    """Returns (caption, hashtags, issues). The caption is never rewritten —
    only measured — because trimming prose to fit the fold would cut the hook
    this check exists to protect."""
    issues: List[Dict] = []
    caption = caption or ""

    if caption:
        # Measured against the same preview the simulator draws, so the two
        # can't disagree about where the fold falls.
        first = _split_sentences(caption.split("\n", 1)[0])[0]
        preview = instagram_preview(caption)
        if len(first) > len(preview):
            issues.append(
                {
                    "level": "warn",
                    "message": (
                        f"첫 문장({len(first)}자)이 '더보기' 전에 보이는 부분({len(preview)}자) 안에 "
                        f"다 들어가지 않습니다(앞 {IG_FOLD}자·최대 {IG_FOLD_LINES}줄까지 보임). "
                        "훅이 잘린 채 노출되니 첫 문장을 짧게 끊으세요."
                    ),
                }
            )

    fixed_tags = list(hashtags or [])
    if len(fixed_tags) > IG_HASHTAG_MAX:
        issues.append(
            {
                "level": "fixed",
                "message": f"해시태그가 {len(fixed_tags)}개라 앞 {IG_HASHTAG_MAX}개만 남겼습니다.",
            }
        )
        fixed_tags = fixed_tags[:IG_HASHTAG_MAX]
    elif len(fixed_tags) < IG_HASHTAG_MIN:
        issues.append(
            {
                "level": "warn",
                "message": (
                    f"해시태그가 {len(fixed_tags)}개뿐입니다 "
                    f"({IG_HASHTAG_MIN}~{IG_HASHTAG_MAX}개 권장). 태그는 인스타의 주요 발견 경로입니다."
                ),
            }
        )

    return caption, fixed_tags, issues


def validate_shorts(script: dict) -> Tuple[dict, List[Dict]]:
    """Returns (script, issues). Shorts had only a simulator warning while X
    got automatic splitting. Captions are measured, not cut — a 20-character
    on-screen line is copy, and chopping it mid-word is worse than flagging
    it — but the one mechanical requirement, #shorts in the title, is added."""
    issues: List[Dict] = []
    script = dict(script or {})
    scenes = script.get("scenes") or []

    long_cuts = []
    if len(script.get("hook") or "") > SHORTS_CAPTION_MAX:
        long_cuts.append(f"훅({len(script['hook'])}자)")
    for i, scene in enumerate(scenes, start=1):
        caption = scene.get("caption") or ""
        if len(caption) > SHORTS_CAPTION_MAX:
            long_cuts.append(f"{i}번 컷({len(caption)}자)")
    if long_cuts:
        issues.append({
            "level": "warn",
            "message": (
                f"쇼츠 자막이 {SHORTS_CAPTION_MAX}자를 넘습니다: {', '.join(long_cuts)} — "
                "화면 우측 버튼·하단 캡션에 가려질 수 있으니 짧게 줄이세요."
            ),
        })

    title = (script.get("title") or "").strip()
    if title and "#shorts" not in title.lower():
        tags = [str(t).lower() for t in script.get("hashtags") or []]
        if "#shorts" not in tags:
            title = f"{title} #shorts"
            issues.append({"level": "fixed", "message": "쇼츠 제목에 #shorts가 없어 붙였습니다."})
    script["title"] = title
    if len(title) > SHORTS_TITLE_MAX:
        issues.append({
            "level": "warn",
            "message": f"쇼츠 제목이 {len(title)}자로 권장({SHORTS_TITLE_MAX}자)을 넘습니다 — 목록에서 잘려 보입니다.",
        })
    return script, issues


def validate_naver_tags(tags: List[str], fallback_keywords: List[str]) -> Tuple[List[str], List[Dict]]:
    """Returns (tags, issues) for the 발행-popup tag list.

    The writer's list used to go out unchecked, and a response it couldn't
    parse came back as [] — the post then went up with no tags at all and
    nothing said so. Tags are normalised ('#', no spaces, no duplicates),
    trimmed to the maximum, and topped up from the post's target keywords
    when the model returned too few.
    """
    issues: List[Dict] = []

    def norm(tag: str) -> str:
        body = re.sub(r"\s+", "", str(tag or "")).lstrip("#")
        return f"#{body}" if body else ""

    out: List[str] = []
    seen = set()
    for tag in tags or []:
        t = norm(tag)
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)

    if len(out) > NAVER_TAG_MAX:
        issues.append({"level": "fixed", "message": f"발행 태그가 {len(out)}개라 앞 {NAVER_TAG_MAX}개만 남겼습니다."})
        out = out[:NAVER_TAG_MAX]

    if len(out) < NAVER_TAG_MIN:
        before = len(out)
        for kw in fallback_keywords or []:
            t = norm(kw)
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
            if len(out) >= NAVER_TAG_MIN:
                break
        if len(out) > before:
            issues.append({
                "level": "fixed",
                "message": f"발행 태그가 {before}개뿐이라 이 글의 타깃 키워드로 {len(out) - before}개를 채웠습니다.",
            })
        if len(out) < NAVER_TAG_MIN:
            issues.append({
                "level": "warn",
                "message": f"발행 태그가 {len(out)}개뿐입니다({NAVER_TAG_MIN}~{NAVER_TAG_MAX}개 권장). 직접 추가하세요.",
            })
    return out, issues
