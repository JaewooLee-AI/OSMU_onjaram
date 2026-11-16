"""카드 글자 잘림 점검 — 자리가 모자라 '…'로 잘리거나 줄이 버려진 글이 있는 카드를 찾아 줍니다.

렌더러(`CardNewsRendererService`)가 그리면서 남긴 `clips`(카드 번호 → 잘린 글 목록)를 사람이 읽을 안내로 바꿉니다.
잘림은 오류가 아니라 '이 카드는 글을 줄이거나 글자 크기를 줄여야 한다'는 신호입니다.
"""
from __future__ import annotations

import asyncio
import tempfile
from typing import Dict, List


def _short(text: str, n: int = 16) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n] + "…"


def message(clips: Dict[int, List[str]]) -> str:
    """잘린 카드가 있으면 한 줄 안내, 없으면 빈 문자열."""
    hit = {i: v for i, v in sorted((clips or {}).items()) if v}
    if not hit:
        return ""
    parts = [f"{i + 1}번('{_short(v[0])}'" + (f" 외 {len(v) - 1}곳" if len(v) > 1 else "") + ")" for i, v in hit.items()]
    return "✂️ 글자가 잘린 카드: " + ", ".join(parts) + " — 글을 줄이거나 '말로 고치기'로 글자를 작게 해 보세요."


def check_storyboard(storyboard) -> Dict[int, List[str]]:
    """스토리보드를 임시 폴더에 그려 보고 카드별 잘린 글 목록을 돌려줍니다(파일은 남기지 않음)."""
    from cards.card_renderer import CardNewsRendererService
    with tempfile.TemporaryDirectory(prefix="osmu_lint_") as tmp:
        r = CardNewsRendererService(export_dir=tmp)
        asyncio.run(r.render_all_slides(storyboard))
        return {i: list(v) for i, v in getattr(r, "clips", {}).items() if v}
