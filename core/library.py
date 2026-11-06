"""📚 보관함 — 글이 수십·수백 개 쌓였을 때의 용량 확인·정리와 일괄 보관.

원칙: **돈과 시간이 든 것은 지우지 않는다.** 카드 그림(PNG)은 언제든 다시 그릴 수 있어 지워도 되고, 쇼츠 영상 파일도 지울 수
있지만(음성은 캐시에 남아 다시 만들 때 음성 비용이 들지 않는다), 돈을 내고 만든 AI 이미지와 올린 사진, 글 본문은 지우지 않는다.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import repo
from core.db import ASSETS_DIR, DATA_DIR


def _size(path: Optional[str]) -> int:
    if not path:
        return 0
    p = Path(path)
    try:
        if p.is_file():
            return p.stat().st_size
        if p.is_dir():
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        pass
    return 0


def disk_usage(campaign: Dict[str, Any]) -> Dict[str, int]:
    """글 하나가 차지하는 용량(바이트): photos(올린 사진 — 다른 글과 같은 파일을 쓸 수 있음) · cards(카드 PNG) ·
    ai_images(AI 이미지, 지우지 않음) · video(쇼츠 영상 파일)."""
    photos = sum(_size(str(ASSETS_DIR / rel)) for rel in
                 {*(campaign.get("storage_file_paths") or []), *(campaign.get("card_photo_paths") or [])})
    return {
        "photos": photos,
        "cards": _size(campaign.get("card_export_dir")),
        "ai_images": _size(str(DATA_DIR / "exports" / "cards" / str(campaign.get("id")) / "assets")),
        "video": _size(campaign.get("shorts_video_path")),
    }


def purgeable_bytes(campaign: Dict[str, Any], cards: bool = True, video: bool = False) -> int:
    u = disk_usage(campaign)
    return (u["cards"] if cards else 0) + (u["video"] if video else 0)


def purge(campaign_id: str, cards: bool = True, video: bool = False) -> int:
    """카드 PNG 폴더와(또는) 쇼츠 영상 파일을 지운다. 지운 바이트 수를 돌려준다. 글·AI 이미지·사진·대본은 그대로."""
    c = repo.get_campaign(campaign_id) or {}
    freed, fields = 0, {}
    if cards and c.get("card_export_dir"):
        freed += _size(c["card_export_dir"])
        shutil.rmtree(c["card_export_dir"], ignore_errors=True)
        fields["card_export_dir"] = None
    if video and c.get("shorts_video_path"):
        freed += _size(c["shorts_video_path"])
        try:
            Path(c["shorts_video_path"]).unlink(missing_ok=True)
        except OSError:
            pass
        fields["shorts_video_path"] = None
    if fields:
        repo.update_campaign(campaign_id, **fields)
    return freed


def published_older_than(days: int) -> List[Dict[str, Any]]:
    """게시한 지 `days`일이 지났고 아직 보관하지 않은 글(일괄 보관 후보)."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows, _ = repo.search_campaigns(status="published", archived="no", limit=100000)
    return [c for c in rows if (c.get("published_at") or "9999") < cutoff]


def total_usage() -> Dict[str, int]:
    """보관 여부와 상관없이 전체 글의 용량 합계."""
    total = {"photos": 0, "cards": 0, "ai_images": 0, "video": 0}
    rows, _ = repo.search_campaigns(archived="all", limit=100000)
    for c in rows:
        for k, v in disk_usage(c).items():
            total[k] += v
    return total
