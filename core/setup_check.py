"""시작 점검 — 앱을 쓰려면 무엇이 준비됐고 무엇이 빠졌는지 한눈에(비개발자 담당자용).

필수 항목이 모두 되어 있으면 대시보드에는 한 줄만 보이고, 빠진 것이 있으면 무엇을 어디서 하면 되는지 알려 줍니다.
선택 항목(이미지·음성·네이버 키워드 측정)은 없어도 핵심 흐름이 돌아가므로 '선택'으로 표시합니다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core import repo


def items() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def add(key: str, label: str, ok: bool, hint: str, required: bool) -> None:
        out.append({"key": key, "label": label, "ok": ok, "hint": hint, "required": required})

    keys = [r for r in repo.list_llm_settings() if r.get("is_active")]
    add("llm_key", "AI 키(Gemini·Claude·OpenAI 중 하나)", bool(keys),
        "⚙️ 설정 → 🤖 AI 연결·모델의 간편 설정에 Google 키를 넣으세요(키 하나로 시작할 수 있습니다).", True)
    text = repo.resolve_slot_model("text")
    add("text_model", "글쓰기 모델 지정", bool(text),
        "⚙️ 설정 → 🤖 AI 연결·모델에서 '기본 글쓰기 모델'을 고르세요(키를 저장하면 자동으로 지정됩니다).", True)
    if text and not any(k["vendor"] == text["vendor"] for k in keys):
        add("text_key", f"'{text['display_name']}'의 벤더 API 키", False,
            "선택한 모델의 벤더 키를 ⚙️ 설정 → 🔑 API 키 탭에서 등록하세요.", True)
    company = repo.get_company_profile()
    add("contact", "대표 전화·이메일(카드·쇼츠 상담 안내에 들어감)", bool(company.get("phone")),
        "🧵 브랜드 킷 → 기업 · 채널에서 대표 전화를 입력하세요.", True)

    image = repo.resolve_slot_model("image")
    add("image_model", "AI 이미지 모델 (선택 — 내 사진만 쓰면 필요 없음)", bool(image),
        "AI로 카드 이미지를 만들려면 🤖 AI 연결·모델에서 '이미지 생성' 모델을 지정하고 Google 키를 등록하세요.", False)
    voice = repo.resolve_slot_model("tts")
    add("tts_model", "음성 모델 (선택 — 없으면 무료 음성)", bool(voice),
        "쇼츠 내레이션 품질을 높이려면 🤖 AI 연결·모델에서 '음성 내레이션' 모델을 지정하세요.", False)
    from cards import ffmpeg_tools
    add("ffmpeg", "FFmpeg (쇼츠 영상 만들기)", ffmpeg_tools.available(),
        "설치 프로그램으로 설치했다면 앱을 다시 설치하세요. 소스 실행이면 ffmpeg를 PATH에 넣으세요.", False)
    from ai_workers import keyword_research
    lvl = keyword_research.level()
    add("naver", f"네이버 키워드 측정 (선택) — {keyword_research.LEVEL_LABELS[lvl].split(':')[0]}", lvl > 0,
        "키워드 순위를 데이터로 정하고 싶을 때만 ⚙️ 설정 → 네이버 API에서 켜세요. 꺼 두어도 글쓰기는 그대로 됩니다.", False)
    return out


def required_missing() -> List[Dict[str, Any]]:
    return [i for i in items() if i["required"] and not i["ok"]]
