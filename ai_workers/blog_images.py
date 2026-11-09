"""블로그 '사진 자리'를 AI 이미지로 채우기 — 사용자가 직접 누를 때만 동작하는 선택 기능입니다.

사진을 올리지 않고 글을 만들면 본문에 '📷 사진 자리'(어떤 사진을 넣으면 좋은지 설명) 표시가 남습니다. 이 표시는 그대로 두고,
사용자가 [AI 이미지로 채우기]를 고르면 자리 설명으로 그림을 만들어 그 자리에 `[IMAGE: 경로]`로 넣습니다(사진을 올렸을 때와 같은 경로).

- 모델: 설정의 '이미지 생성' 슬롯(`repo.resolve_slot_model("image")`) — 카드 이미지와 같은 어댑터(`cards.images._generate_gemini`).
- 비용: 실행 전 `plan`으로 장수·예상 금액을 보여 주고 확인을 받습니다. 한 번에 `MAX_IMAGES`장까지.
- 개인정보·윤리: 실존·식별 가능한 인물, 글자·로고를 그리지 않는다는 규칙(`images.SAFETY_RULE`)을 항상 붙입니다.
- 앞 자리부터 차례로 만들고, 한 장이 실패하면 거기서 멈춥니다(만든 것까지만 넣고 나머지 자리 표시는 그대로 남음). 만든 장마다 사용 기록(kind='image')을 남깁니다.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ai_workers import formatting
from cards import images
from core import repo, storage

MAX_IMAGES = 4
ASPECT = "4:3"
Progress = Optional[Callable[[str], None]]


def plan(campaign: Dict[str, Any]) -> Dict[str, Any]:
    """실행 전 예상: 채울 수 있는 사진 자리 수, 만들 장수, 모델, 단가·합계(미등록이면 None)."""
    slots = formatting.open_photo_hints(campaign.get("content") or "", campaign.get("content_format"))
    count = min(len(slots), MAX_IMAGES)
    model = repo.resolve_slot_model("image")
    per = model.get("per_image") if model else None
    return {"slots": len(slots), "count": count, "model": model, "per_image": per,
            "total_usd": (per * count) if per is not None else None}


def describe(est: Dict[str, Any]) -> str:
    if est["slots"] == 0:
        return "AI 이미지를 넣을 '사진 자리'가 없습니다(사진을 이미 넣었거나 서식 강도가 '없음'입니다)."
    if est["model"] is None:
        return "'이미지 생성' 모델이 없거나 꺼져 있습니다(⚙️ 설정 → 🤖 모델 등록에서 지정하고 '사용'을 켜세요)."
    name = est["model"]["display_name"]
    more = f" (사진 자리 {est['slots']}곳 중 앞의 {est['count']}곳)" if est["slots"] > est["count"] else ""
    if est["total_usd"] is None:
        return f"AI 이미지 {est['count']}장{more} · 모델 {name} · 단가 미등록(모델 등록에서 입력하면 예상 금액이 보입니다)"
    return f"AI 이미지 {est['count']}장{more} · 모델 {name} · 예상 ${est['total_usd']:.3f} (장당 ${est['per_image']:g})"


def build_prompt(caption: str) -> str:
    scene = (caption or "").strip() or "차분하고 따뜻한 분위기의 장면"
    return f"Scene: {scene}\nStyle: {images.DEFAULT_STYLE}\n{images.SAFETY_RULE}"


def caption_for(hint_caption: str) -> str:
    """AI 이미지의 사진 설명. 사진 자리 설명(무엇을 그렸는지) + 'AI로 만든 그림'임을 밝히는 꼬리표."""
    base = (hint_caption or "").strip().rstrip(".")
    return f"{base} (AI로 만든 이미지)" if base else "AI로 만든 이미지"


def generate(campaign_id: str, generate_fn: Optional[images.GenerateFn] = None, progress: Progress = None) -> Dict[str, Any]:
    """사진 자리에 AI 이미지를 만들어 넣고 글에 저장합니다. 반환: {"made": n, "failed": [(번호, 오류)]}."""
    campaign = repo.get_campaign(campaign_id) or {}
    est = plan(campaign)
    result: Dict[str, Any] = {"made": 0, "failed": []}
    if not est["count"]:
        return result
    model = est["model"]
    if model is None:
        raise RuntimeError("'이미지 생성' 모델이 지정되지 않았습니다. ⚙️ 설정 → 🤖 모델 등록에서 지정하세요.")
    if generate_fn is None:
        if model["vendor"] != "google":
            raise RuntimeError(f"이미지 생성은 현재 Google(Gemini) 모델만 지원합니다(지정된 모델: {model['vendor']}).")
        generate_fn = images._generate_gemini

    slots = formatting.open_photo_hints(campaign.get("content") or "", campaign.get("content_format"))[:est["count"]]
    made_paths = []
    captions = []
    with repo.usage_scope(campaign_id):
        for n, hint in enumerate(slots, 1):
            if progress:
                progress(f"AI 이미지 만드는 중… ({n}/{len(slots)})")
            try:
                data, ext, usage = generate_fn(model["model_id"], build_prompt(hint.get("caption", "")), ASPECT)
            except Exception as exc:  # noqa: BLE001
                result["failed"].append((n, f"{type(exc).__name__}: {str(exc)[:120]}"))
                break   # 앞 자리부터 차례로 채우므로, 한 장이 실패하면 거기서 멈춰 그림과 자리 설명이 어긋나지 않게 한다
            made_paths.append(storage.save_upload(data, f"AI_blog_{n}{ext}"))
            captions.append(caption_for(hint.get("caption", "")))
            repo.log_usage("image", vendor=model["vendor"], model=model["model_id"], image_count=1,
                           est_input_tokens=int(usage.get("in", 0)), est_output_tokens=int(usage.get("out", 0)), note="blog-image")
            result["made"] += 1
    if not made_paths:
        return result

    fresh = repo.get_campaign(campaign_id) or {}
    attached = list(fresh.get("storage_file_paths") or [])
    attached += [p for p in made_paths if p not in attached]
    content, fmt, placed = formatting.fill_photo_hints(fresh.get("content") or "", fresh.get("content_format"), made_paths)
    repo.update_campaign(campaign_id, storage_file_paths=attached, content=content, content_format=fmt)
    # 사진을 올렸을 때처럼 '사진 설명'도 넣는다(시뮬레이터·게시 화면의 설명 칸). 실제 사진이 아님을 설명에 밝힌다.
    fmt = dict(fmt or {})
    fmt["items"] = list(fmt.get("items") or []) + [
        {"type": "photo_caption", "path": path, "caption": cap} for path, cap in zip(made_paths[:placed], captions)]
    repo.update_campaign(campaign_id, content_format=fmt)
    result["placed"] = placed
    return result
