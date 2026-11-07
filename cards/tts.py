"""Gemini TTS로 씬별 한국어 내레이션 합성 — 모델은 설정의 '음성 내레이션' 슬롯(repo.resolve_slot_model("tts")).

코드에 모델 이름이 없고, 고른 모델이 없거나 실패하면 다른 모델로 몰래 바꾸지 않습니다(호출한 쪽이 무료 음성 등으로
대체하되 화면에 알립니다). 같은 문장·목소리·모델은 캐시를 재사용해 비용을 아낍니다. 호출마다 사용 기록(kind='tts', 초 단위)을
남겨 등록 단가가 있으면 금액을 계산합니다.

온자람 기본 말투는 차분하고 따뜻한 상담 톤입니다(빠르고 경쾌한 홍보 톤이 아님).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import struct
from typing import List, Optional

from core import repo
from core.crypto_utils import decrypt_api_key

# 화면 표시용 라벨 → Gemini 기본 제공 목소리 이름 (Google 문서의 목소리 특징 기준)
VOICE_OPTIONS = {
    "자동 (차분하고 부드러운)": "auto",
    "Aoede · 부드럽고 편안한": "Aoede",
    "Kore · 단단하고 신뢰감 있는": "Kore",
    "Charon · 차분한 정보 전달형": "Charon",
    "Zephyr · 밝고 산뜻한": "Zephyr",
    "Puck · 경쾌하고 밝은": "Puck",
    "무료 음성 (gTTS · 인터넷 필요, 품질 낮음)": "free",
    "테스트 전용: 음성 없음 (무음 · 비용 없음)": "silent",
}
DEFAULT_VOICE = "Aoede"
STYLE = ("a calm, warm and gentle counselor's voice, unhurried and reassuring, with natural pauses")


def pick_voice(choice: str) -> str:
    return choice if choice and choice not in ("auto", "free") else DEFAULT_VOICE


def style_instruction() -> str:
    # 영어 지시문은 읽히지 않고 한국어 본문만 낭독됨(형제 프로젝트에서 실측)
    return f"Read the following Korean narration in {STYLE}, at a relaxed pace suitable for a short video:"


def _pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return header + b"data" + struct.pack("<I", len(pcm)) + pcm


def _wav_seconds(data: bytes) -> float:
    """16-bit mono WAV(24kHz 기본)의 길이(초) — 헤더에서 샘플레이트를 읽는다."""
    try:
        rate = struct.unpack("<I", data[24:28])[0] or 24000
        return max(0.0, (len(data) - 44) / (rate * 2))
    except struct.error:
        return 0.0


class TtsUnavailable(RuntimeError):
    """음성 슬롯 모델이나 키가 없어 쓸 수 없음 — 호출한 쪽이 대체 음성을 쓰고 화면에 알린다."""


class GeminiTTS:
    def __init__(self, voice: str, cache_dir: str, call=None):
        model = repo.resolve_slot_model("tts")
        if model is None:
            raise TtsUnavailable("'음성 내레이션' 모델이 지정되지 않았습니다(⚙️ 설정 → 🤖 모델 등록).")
        if model["vendor"] != "google":
            raise TtsUnavailable(f"음성 합성은 현재 Google(Gemini) 모델만 지원합니다(지정된 모델: {model['vendor']}).")
        self.model = model
        self.voice = pick_voice(voice)
        self.instruction = style_instruction()
        self.cache_dir = cache_dir
        self._call_override = call            # 시험용: async (model_id, text, voice) -> (wav 바이트, 사용량 dict)
        os.makedirs(cache_dir, exist_ok=True)
        self._client = None

    def _cache_path(self, text: str) -> str:
        key = hashlib.sha256(f"{self.model['model_id']}|{self.voice}|{self.instruction}|{text}".encode()).hexdigest()[:24]
        return os.path.join(self.cache_dir, f"{key}.wav")

    def _api_client(self):
        if self._client is None:
            setting = repo.get_llm_setting("google")
            if not setting or not setting.get("is_active"):
                raise TtsUnavailable("Gemini API 키가 없습니다(⚙️ 설정 → 🔑 LLM 벤더).")
            from google import genai
            self._client = genai.Client(api_key=decrypt_api_key(setting["encrypted_api_key"]))
        return self._client

    async def synthesize_all(self, texts: List[str], out_paths: List[str]) -> int:
        """모든 씬을 합성. 하나라도 실패하면 예외(목소리가 섞이지 않도록 호출 측이 전체를 대체). 반환: 캐시 재사용 수."""
        sem = asyncio.Semaphore(3)
        reused = 0

        async def one(text: str, out: str) -> None:
            nonlocal reused
            async with sem:
                cached = self._cache_path(text)
                if os.path.exists(cached):
                    with open(cached, "rb") as src, open(out, "wb") as dst:
                        dst.write(src.read())
                    reused += 1
                    return
                data, usage = await self._request(text)
                with open(cached, "wb") as f:
                    f.write(data)
                with open(out, "wb") as f:
                    f.write(data)
                repo.log_usage("tts", vendor=self.model["vendor"], model=self.model["model_id"],
                               est_input_tokens=int(usage.get("in", 0)), est_output_tokens=int(usage.get("out", 0)),
                               seconds=_wav_seconds(data), note="shorts-tts")

        await asyncio.gather(*(one(t, o) for t, o in zip(texts, out_paths)))
        return reused

    async def _request(self, text: str):
        last: Optional[Exception] = None
        for attempt in range(2):
            try:
                if self._call_override:
                    return await self._call_override(self.model["model_id"], text, self.voice)
                return await self._gemini(text)
            except TtsUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 — 한 번 재시도
                last = exc
                await asyncio.sleep(1.5)
        raise last or RuntimeError("음성 합성 실패")

    async def _gemini(self, text: str):
        from google.genai import types
        client = self._api_client()
        response = await asyncio.wait_for(client.aio.models.generate_content(
            model=self.model["model_id"], contents=f"{self.instruction}\n{text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice))),
            ),
        ), timeout=60)
        usage = getattr(response, "usage_metadata", None)
        info = {"in": getattr(usage, "prompt_token_count", 0) or 0,
                "out": (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)}
        part = response.candidates[0].content.parts[0]
        data, mime = part.inline_data.data, (part.inline_data.mime_type or "")
        if not data:
            raise RuntimeError("Gemini TTS 응답에 오디오가 없습니다")
        if data[:4] == b"RIFF":
            return data, info
        rate = 24000
        if "rate=" in mime:
            try:
                rate = int(mime.split("rate=")[1].split(";")[0])
            except ValueError:
                pass
        return _pcm_to_wav(data, rate), info
