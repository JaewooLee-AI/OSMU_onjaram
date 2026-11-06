"""카드 이미지 — 내 사진 우선, 부족한 칸만 AI로 채우기(비용 절감).

이미지 모드(스토리보드의 `image_mode`):
- own_only : 내 사진만. AI 이미지 호출 0회. 사진이 없는 칸은 인포그래픽·글 카드로 그립니다.
- own_first: 내 사진 우선(기본). 사진이 없는 칸만 AI로 채웁니다.
- ai_first : AI 이미지 우선. 사용자가 직접 고르지 않은(asset_locked가 아닌) 사진 칸에 내 사진 대신 AI 이미지를 만듭니다(이미 AI 이미지가 있는 칸은 다시 만들지 않습니다).

사진 칸 = 디자인이 사진을 쓰는 카드(`DesignTemplate.uses_photo`). 사용자가 카드에 사진을 직접 고르거나 '사진 없음'을
고른 카드(`asset_locked`)는 자동 배치·AI 생성이 건드리지 않습니다. AI 이미지는 **실행 전 예상 비용**을 보여 주고
(`estimate`), 모델은 설정의 '이미지 생성' 슬롯(repo.resolve_slot_model("image"))에서 가져옵니다 — 코드에 모델 이름이 없고,
고른 모델이 실패하면 다른 모델로 몰래 바꾸지 않습니다. 현재는 Gemini 어댑터만 있습니다.

개인정보: 심리상담 콘텐츠이므로 AI 그림 프롬프트에는 실존·식별 가능한 인물을 그리지 않고 글자·로고를 넣지 않는다는 규칙을
항상 붙입니다.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from cards import design_templates
from cards.paths import DATA_DIR  # noqa: F401  (경로 규칙을 한곳에서 확인하려는 용도)
from cards.schema import EditableStoryboard, MediaAsset
from core import repo
from core.crypto_utils import decrypt_api_key

IMAGE_MODES = {
    "own_only": "내 사진만 (AI 이미지 없음 · 비용 0)",
    "own_first": "내 사진 우선, 부족한 칸만 AI",
    "ai_first": "AI 이미지 우선 (직접 고른 카드 제외)",
}
# 사진·그림을 쓸 수 있는 카드 종류(안내·번호·표 카드는 인포그래픽/글로 그려 AI 이미지 비용을 아낀다)
PHOTO_TYPES = ("cover", "body", "single", "quote")
DEFAULT_STYLE = ("Soft, calm flat illustration or gentle natural scene (leaves, light, hands, objects), sage green and cream "
                 "palette, warm and safe mood, plenty of empty space.")
SAFETY_RULE = ("Do NOT depict any identifiable real person or face. ABSOLUTELY NO TEXT of any kind in the image: no letters, "
               "words, numbers, signs, labels, captions, logos or watermarks.")
_ASPECTS = (("16:9", 16 / 9), ("3:2", 3 / 2), ("4:3", 4 / 3), ("1:1", 1.0), ("4:5", 0.8), ("3:4", 0.75), ("9:16", 9 / 16))

GenerateFn = Callable[[str, str, str], Tuple[bytes, str, Dict[str, Any]]]  # (모델 ID, 프롬프트, 화면비) → (바이트, 확장자, 사용량)


def photo_slot_indexes(sb: EditableStoryboard) -> List[int]:
    """디자인이 사진을 쓰는 카드 번호(0부터)."""
    design = design_templates.get(sb.design_id)
    return [i for i, s in enumerate(sb.card_slides) if s.slide_type in PHOTO_TYPES and design.uses_photo(s.slide_type)]


def slot_aspect(sb: EditableStoryboard) -> str:
    """사진 칸의 화면비에 가장 가까운 Gemini 지원 화면비."""
    design = design_templates.get(sb.design_id)
    if design.layout == "tri":
        parts = [max(1, int(x)) for x in (design.ratio or [2, 5, 3])[:3]]
        from cards.schema import CARD_ASPECTS
        ratio = 1080 / (CARD_ASPECTS.get(getattr(sb, "aspect", "4:5"), 1350) * parts[1] / sum(parts))
    else:
        w, _, h = (design.image_aspect or "4:5").partition(":")
        ratio = float(w) / float(h or 1)
    return min(_ASPECTS, key=lambda a: abs(a[1] - ratio))[0]


def _asset(sb: EditableStoryboard, asset_id: Optional[str]) -> Optional[MediaAsset]:
    return sb.asset(asset_id)


def apply_mode(sb: EditableStoryboard, user_assets: Optional[List[MediaAsset]] = None) -> None:
    """모드에 맞게 내 사진을 사진 칸에 자동 배치합니다(직접 고른 카드는 그대로).
    own_only·own_first는 올린 사진을 차례로 배치하고, ai_first는 자동 배치하지 않습니다."""
    users = [a for a in (user_assets if user_assets is not None else sb.assets) if a.source == "user" and a.kind in ("image", "video")]
    for s in sb.card_slides:
        if not s.asset_locked and (_asset(sb, s.asset_id) is None or _asset(sb, s.asset_id).source == "user"):
            s.asset_id = None
    if sb.image_mode == "ai_first":
        return
    queue = list(users)
    for i in photo_slot_indexes(sb):
        s = sb.card_slides[i]
        if s.asset_locked or s.asset_id:
            if s.asset_id and _asset(sb, s.asset_id) in queue:
                queue.remove(_asset(sb, s.asset_id))
            continue
        if queue:
            s.asset_id = queue.pop(0).id


def ai_targets(sb: EditableStoryboard) -> List[int]:
    """AI 이미지를 만들 카드 번호."""
    if sb.image_mode == "own_only":
        return []
    out = []
    for i in photo_slot_indexes(sb):
        s = sb.card_slides[i]
        if s.asset_locked:
            continue
        asset = _asset(sb, s.asset_id)
        # 이미 AI 이미지가 있는 칸은 다시 만들지 않는다(같은 비용을 두 번 쓰지 않게). 다시 만들려면 카드에서 사진을 '자동'으로 바꾼다.
        if asset is None or (sb.image_mode == "ai_first" and asset.source == "user"):
            out.append(i)
    return out


def estimate(sb: EditableStoryboard, only: Optional[List[int]] = None) -> Dict[str, Any]:
    """실행 전 예상: AI로 만들 장수, 모델, 장당·합계 단가(미등록이면 None).
    `only`를 주면 그 카드(0부터)만 새로 만듭니다 — 이미 AI 이미지가 있어도 다시 만드는 경우."""
    targets = list(only) if only is not None else ai_targets(sb)
    existing_ai = sum(1 for s in sb.card_slides if (_asset(sb, s.asset_id) is not None and _asset(sb, s.asset_id).source == "ai"))
    model = repo.resolve_slot_model("image")
    per = model.get("per_image") if model else None
    return {"count": len(targets), "targets": targets, "model": model, "per_image": per, "existing_ai": existing_ai,
            "total_usd": (per * len(targets)) if per is not None else None, "aspect": slot_aspect(sb)}


def describe_estimate(est: Dict[str, Any]) -> str:
    if est["count"] == 0:
        if est.get("existing_ai"):
            return (f"AI 이미지 {est['existing_ai']}장이 이미 카드에 들어 있습니다 — 더 만들 칸이 없습니다. "
                    "다시 만들려면 카드별 [AI 이미지 다시 만들기]를 누르세요.")
        return "AI로 만들 칸이 없습니다(사진 칸이 모두 내 사진이거나 이미지 모드가 '내 사진만'입니다) — 비용이 들지 않습니다."
    if est["model"] is None:
        return (f"AI 이미지 {est['count']}장이 필요하지만 '이미지 생성' 모델이 없거나 꺼져 있습니다"
                "(⚙️ 설정 → 🤖 모델 등록에서 지정하고 '사용'을 켜세요).")
    name = est["model"]["display_name"]
    if est["total_usd"] is None:
        return f"AI 이미지 {est['count']}장 · 모델 {name} · 단가 미등록(모델 등록에서 이미지 단가를 입력하면 예상 금액이 보입니다)"
    return f"AI 이미지 {est['count']}장 · 모델 {name} · 예상 ${est['total_usd']:.3f} (장당 ${est['per_image']:g})"


def build_prompt(sb: EditableStoryboard, index: int) -> str:
    slide = sb.card_slides[index]
    design = design_templates.get(sb.design_id)
    scene = (slide.image_prompt or "").strip() or f"{slide.lead_headline.replace('*', '')}의 분위기를 상징하는 차분한 장면"
    style = design.style_prompt.strip() or DEFAULT_STYLE
    return f"Scene: {scene}\nStyle: {style}\n{SAFETY_RULE}"


def _gemini_key() -> str:
    setting = repo.get_llm_setting("google")
    if not setting or not setting.get("is_active"):
        raise RuntimeError("Gemini API 키가 없습니다. ⚙️ 설정 → 🔑 LLM 벤더에서 Google 키를 등록하세요.")
    return decrypt_api_key(setting["encrypted_api_key"])


# 단가(장당 1K 기준)와 같은 해상도로 요청한다. 해상도를 안 정하면 모델 기본값을 따라 비용 가정이 어긋날 수 있다.
IMAGE_SIZE = "1K"


def _generate_gemini(model_id: str, prompt: str, aspect: str) -> Tuple[bytes, str, Dict[str, Any]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_gemini_key())

    def call(size):
        cfg = types.ImageConfig(aspect_ratio=aspect, **({"image_size": size} if size else {}))
        return client.models.generate_content(
            model=model_id, contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"], image_config=cfg))

    try:
        response = call(IMAGE_SIZE)
    except Exception as exc:  # noqa: BLE001 — 해상도 옵션을 모르는 모델이면 옵션만 빼고 한 번 더(모델은 바꾸지 않는다)
        text = str(exc).lower()
        if "image_size" in text or "imagesize" in text or ("invalid" in text and "size" in text):
            response = call(None)
        else:
            raise
    usage = getattr(response, "usage_metadata", None)
    info = {"in": getattr(usage, "prompt_token_count", 0) or 0,
            "out": (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)}
    for part in response.parts or []:
        if part.inline_data and part.inline_data.data:
            mime = part.inline_data.mime_type or "image/png"
            return part.inline_data.data, (".jpg" if "jpeg" in mime else ".png"), info
    raise RuntimeError("응답에 이미지가 없습니다(안전 필터 또는 프롬프트 문제).")


def _next_g(sb: EditableStoryboard) -> int:
    nums = [int(a.id[1:]) for a in sb.assets if a.id.startswith("G") and a.id[1:].isdigit()]
    return max(nums, default=0) + 1


def generate_missing(
    sb: EditableStoryboard,
    out_dir: str,
    generate: Optional[GenerateFn] = None,
    progress: Optional[Callable[[str], None]] = None,
    only: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """AI로 만들 카드의 이미지를 만들어 배치합니다. 반환: {"made": n, "failed": [(번호, 오류)], "estimate": …}.

    '이미지 생성' 슬롯의 모델만 씁니다(없으면 오류). 한 장이 실패해도 나머지는 계속하지만, 인증·권한 오류면 즉시 멈춰
    불필요한 호출을 막습니다. 만든 장마다 사용량을 기록합니다(등록 단가가 있으면 금액 계산)."""
    est = estimate(sb, only)
    result: Dict[str, Any] = {"made": 0, "failed": [], "estimate": est}
    if not est["targets"]:
        return result
    model = est["model"]
    if model is None:
        raise RuntimeError("'이미지 생성' 모델이 지정되지 않았습니다. ⚙️ 설정 → 🤖 모델 등록에서 지정하세요.")
    if generate is None:
        if model["vendor"] != "google":
            raise RuntimeError(f"이미지 생성은 현재 Google(Gemini) 모델만 지원합니다(지정된 모델: {model['vendor']}).")
        generate = _generate_gemini
    os.makedirs(os.path.join(out_dir, "ai"), exist_ok=True)
    for n, index in enumerate(est["targets"], 1):
        if progress:
            progress(f"AI 이미지 만드는 중… ({n}/{len(est['targets'])})")
        prompt = build_prompt(sb, index)
        try:
            data, ext, usage = generate(model["model_id"], prompt, est["aspect"])
        except Exception as exc:  # noqa: BLE001 — 한 장 실패가 전체를 막지 않게(인증 오류는 아래에서 멈춤)
            result["failed"].append((index + 1, f"{type(exc).__name__}: {str(exc)[:120]}"))
            if any(w in str(exc).lower() for w in ("api key", "api_key", "permission", "unauthorized", "403", "401")):
                break
            continue
        asset_id = f"G{_next_g(sb)}"
        path = os.path.join(out_dir, "ai", f"{asset_id}{ext}")
        with open(path, "wb") as f:
            f.write(data)
        sb.assets.append(MediaAsset(id=asset_id, kind="image", source="ai", path=path, original_name=f"AI_{asset_id}{ext}",
                                    description=prompt.splitlines()[0][:120]))
        sb.card_slides[index].asset_id = asset_id
        if only is not None:   # 카드에서 직접 'AI로 다시 만들기'를 고른 칸은 자동 배치·다른 AI 실행이 건드리지 않게 한다
            sb.card_slides[index].asset_locked = True
        repo.log_usage("image", vendor=model["vendor"], model=model["model_id"], image_count=1,
                       est_input_tokens=int(usage.get("in", 0)), est_output_tokens=int(usage.get("out", 0)), note="card-image")
        result["made"] += 1
    return result
