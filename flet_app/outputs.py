"""한 번에 만들기 — 블로그 · 카드뉴스 · 쇼츠 중 고른 것만 차례로 만듭니다.

- 블로그: 기존 생성 파이프라인(`run_pipeline`) 그대로(인스타 캡션·발행 태그 포함).
- 카드뉴스: 원고로 카드를 기획하고 그립니다. 원고는 블로그 본문이 있으면 그것, 없으면 메모입니다.
  카드 종류·디자인·이미지 모드는 이미 기획한 카드가 있으면 그 설정을, 없으면 기본값을 씁니다.
  `one_card`(한 장 카드) 모드면 카드 종류를 '한 장 카드'로 고정합니다.
- 쇼츠: 카드에서 대본을 만듭니다. 카드뉴스를 고르지 않고 쇼츠만 골랐으면 카드는 기획만 하고(이미지는 내보내지
  않고) 대본에 씁니다. **영상 렌더(음성 합성 비용 발생)는 여기서 하지 않고** 🎬 쇼츠 영상 탭의 확인 창을 거칩니다.
- AI 이미지 생성도 비용이 들어서 여기서 하지 않습니다(🃏 카드뉴스 탭에서 예상 비용을 보고 만듭니다).

화면 코드와 분리해 둬서 시험할 수 있습니다.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from ai_workers.content_writer import run_pipeline
from cards import card_types, shorts_script
from cards.director import plan_cards
from cards.schema import BrandElements
from core import repo

OUTPUT_LABELS = {"blog": "📝 블로그 (+인스타 캡션)", "cards": "🃏 카드뉴스", "shorts": "🎬 쇼츠"}
OUTPUT_KEYS = tuple(OUTPUT_LABELS)
STATE_KEY = "default_outputs"
ONE_CARD_TYPE = "one_card"

Progress = Optional[Callable[[str], None]]


def default_outputs() -> List[str]:
    """설정의 기본 생성 대상(저장한 적이 없으면 셋 다)."""
    stored = (repo.get_app_state(STATE_KEY) or {}).get("value")
    if not isinstance(stored, list):
        return list(OUTPUT_KEYS)
    return [k for k in OUTPUT_KEYS if k in stored]


def save_default_outputs(keys: List[str]) -> None:
    repo.set_app_state(STATE_KEY, {"value": [k for k in OUTPUT_KEYS if k in keys]})


def _say(progress: Progress, msg: str) -> None:
    if progress:
        progress(msg)


# 글 유형 → 카드 시리즈 이름(블로그 카테고리와 맞춤)·기본 카드 종류. 이미 기획한 카드가 있으면 그 종류를 따릅니다.
SERIES_LABELS = {"review": "온자람 현장", "column": "온자람 마음노트", "notice": "온자람 소식"}
POST_TYPE_CARD = {"review": "info_summary", "column": "empathy", "notice": "event_notice"}


def _plan_type(sb, one_card: bool, post_type: str | None = None) -> str:
    if one_card:
        return ONE_CARD_TYPE
    if sb is None and post_type in POST_TYPE_CARD and any(p["id"] == POST_TYPE_CARD[post_type] for p in card_types.available()):
        return POST_TYPE_CARD[post_type]
    if sb is not None and sb.card_format and sb.card_format != ONE_CARD_TYPE:
        return sb.card_format
    for pack in card_types.available():
        if pack["id"] != ONE_CARD_TYPE:
            return pack["id"]
    return card_types.get(None)["id"]


def has_ai_planner() -> bool:
    return any(r.get("is_active") for r in repo.list_llm_settings()) and repo.resolve_slot_model("text") is not None


def plan_for_campaign(campaign_id: str, type_id: Optional[str] = None, design_id: Optional[str] = None,
                      one_card: bool = False, use_ai: Optional[bool] = None, image_mode: Optional[str] = None,
                      source: Optional[str] = None, count: Optional[int] = None,
                      aspect: Optional[str] = None):
    """원고 → 카드 기획 → 글에 저장. 반환: (스토리보드, 보고서).
    원고는 `source`가 있으면 그것, 없으면 블로그 본문, 그것도 없으면 메모입니다. 종류·디자인·이미지 모드를 주지 않으면
    이미 기획한 카드의 설정을, 그것도 없으면 기본값을 씁니다."""
    from flet_app.views.card_studio import _assets_of, load_storyboard, save_storyboard, sync_assets

    campaign = repo.get_campaign(campaign_id) or {}
    text = (source or campaign.get("content") or campaign.get("memo") or "").strip()
    if not text:
        raise ValueError("카드·쇼츠를 만들 원고가 없습니다. 메모를 입력하거나 블로그도 함께 만드세요.")
    if use_ai is None:
        use_ai = has_ai_planner()
    old = load_storyboard(campaign)
    with repo.usage_scope(campaign_id):
        sb, report = plan_cards(
            text, type_id or _plan_type(old, one_card, campaign.get("post_type")), kit_id=campaign.get("brand_kit_id"), count=count,
            design_id=design_id or (old.design_id if old else None), use_llm=bool(use_ai),
            assets=_assets_of(campaign),
            elements=BrandElements(series_label=SERIES_LABELS.get(campaign.get("post_type") or "", "")),
            image_mode=image_mode or (old.image_mode if old else "own_first"),
        )
    sb.aspect = aspect or (old.aspect if old else "4:5")
    sync_assets(sb, campaign)
    save_storyboard(campaign_id, sb)
    return sb, report


def run_outputs(campaign_id: str, outputs: List[str], one_card: bool = False, use_ai: Optional[bool] = None,
                progress: Progress = None) -> Dict[str, object]:
    """고른 산출물을 차례로 만듭니다. 반환: 만든 것·건너뛴 것을 담은 요약(화면 문구용)."""
    # 화면 모듈의 저장·그리기 함수를 쓴다(같은 파일 형식을 한곳에서 관리하려고).
    from flet_app.views.card_studio import render_storyboard, save_storyboard

    chosen = [k for k in OUTPUT_KEYS if k in outputs]
    if not chosen:
        raise ValueError("만들 것을 하나 이상 고르세요.")
    result: Dict[str, object] = {"made": [], "notes": []}

    if "blog" in chosen:
        _say(progress, "블로그 글을 만드는 중…")
        run_pipeline(campaign_id, progress=progress)
        result["made"].append("블로그")

    if "cards" in chosen or "shorts" in chosen:
        _say(progress, "카드를 기획하는 중…")
        sb, report = plan_for_campaign(campaign_id, one_card=one_card, use_ai=use_ai)
        campaign = repo.get_campaign(campaign_id) or {}
        result["notes"] += list(report.get("warnings") or [])
        if "cards" in chosen:
            _say(progress, "카드를 그리는 중…")
            paths = render_storyboard(campaign_id, sb)
            result["made"].append(f"카드뉴스 {len(paths)}장")
        else:
            result["notes"].append("쇼츠용으로 카드를 기획만 했습니다(카드 이미지는 만들지 않았습니다).")

        if "shorts" in chosen:
            _say(progress, "쇼츠 대본을 만드는 중…")
            with repo.usage_scope(campaign_id):
                scenes, srep = shorts_script.convert(sb, campaign.get("brand_kit_id"), 45, use_llm=bool(use_ai))
            shorts_script.apply_to_storyboard(sb, scenes)
            save_storyboard(campaign_id, sb)
            result["notes"] += list(srep.get("warnings") or [])
            result["made"].append(f"쇼츠 대본 {len(scenes)}장면")
            result["notes"].append("쇼츠 영상은 🃏 카드·쇼츠 화면에서 [쇼츠 영상 만들기]를 눌러 만듭니다(음성 비용 확인 창이 뜹니다).")
    return result
