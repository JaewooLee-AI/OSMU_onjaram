"""모델 등록 시드 — 첫 실행 때 한 번만 들어가는 **편집 가능한 예시**입니다.

모델은 자주 단종되거나 바뀌므로 코드가 아니라 데이터로 둡니다. ⚙️ 설정 → 🤖 모델 등록에서 이름(버전)을
고치거나 새 모델을 추가하세요. 여기에는 **단가를 넣지 않습니다**(비어 있으면 '단가 미등록'이고 0원이
아닙니다) — 공식 요금표를 보고 설정 화면에서 입력합니다. 이름은 형제 프로젝트(OSMU_cjc,
ammasarang_card_shorts)에서 쓰던 값이며, 지금도 쓸 수 있는지는 [연결 테스트]로 확인하세요.
이 파일을 고쳐도 이미 설치된 앱에는 반영되지 않습니다(DB가 원본).
"""
from __future__ import annotations

from core import repo

_NOTE = "예시 — 공식 문서와 [연결 테스트]로 지금도 사용할 수 있는지 확인하세요"

# (vendor, model_id, 화면 이름, 용도)
SEED_MODELS = [
    ("google", "gemini-3.8-flash", "Gemini 3.8 Flash", ["text", "vision"]),
    ("google", "gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite", ["text", "vision"]),
    ("anthropic", "claude-sonnet-5-5", "Claude Sonnet 5.5", ["text", "vision"]),
    ("anthropic", "claude-opus-5-5", "Claude Opus 5.5", ["text", "vision"]),
    ("anthropic", "claude-haiku-5-5", "Claude Haiku 5.5", ["text", "vision"]),
    ("openai", "gpt-5-mini", "GPT-5 mini", ["text", "vision"]),
    ("google", "gemini-3.1-flash-image", "Gemini 3.1 Flash Image", ["image"]),
    ("google", "gemini-2.5-flash-image", "Gemini 2.5 Flash Image", ["image"]),
    ("google", "gemini-3-pro-image", "Gemini 3 Pro Image", ["image"]),
    ("google", "gemini-3.8-flash-tts", "Gemini 3.8 Flash TTS", ["tts"]),
    ("google", "gemini-omni-1.1-flash", "Gemini Omni 1.1 Flash (영상)", ["video"]),
]


def seed_models_if_empty() -> bool:
    """등록된 모델이 하나도 없을 때만 예시를 넣습니다. 넣었으면 True."""
    if repo.list_models():
        return False
    for vendor, model_id, name, caps in SEED_MODELS:
        repo.upsert_model(vendor, model_id, display_name=name, capabilities=caps, note=_NOTE)
    return True
