"""FFmpeg·ffprobe 실행 파일 위치 찾기 — Windows 설치형은 앱에 동봉한 것을 쓰고, 없으면 PATH를 봅니다.

찾는 순서: 환경변수 OSMU_FFMPEG_DIR → 패키지 안 `cards/bin/` (설치 프로그램에 동봉) → 데이터 폴더 `bin/` → PATH.
설치 폴더(Program Files)에는 쓰지 않으므로 동봉 파일은 읽기만 합니다. 동봉 빌드와 라이선스는 docs/FFMPEG_동봉.md 참고.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from typing import Optional

from cards.paths import CARDS_DIR, DATA_DIR

_EXE = ".exe" if sys.platform.startswith("win") else ""


def _candidates(name: str):
    env = os.environ.get("OSMU_FFMPEG_DIR")
    if env:
        yield os.path.join(env, name + _EXE)
    yield os.path.join(CARDS_DIR, "bin", name + _EXE)
    yield os.path.join(DATA_DIR, "bin", name + _EXE)


def _find(name: str) -> Optional[str]:
    for path in _candidates(name):
        if os.path.isfile(path):
            return path
    return shutil.which(name)


def ffmpeg() -> str:
    return _find("ffmpeg") or "ffmpeg"


def ffprobe() -> str:
    return _find("ffprobe") or "ffprobe"


def available() -> bool:
    return bool(_find("ffmpeg") and _find("ffprobe"))


def require() -> None:
    """없으면 사용자에게 보여 줄 수 있는 오류를 낸다."""
    if not available():
        raise RuntimeError(
            "FFmpeg를 찾을 수 없습니다. 설치 프로그램으로 설치했다면 앱을 다시 설치하고, 소스로 실행 중이면 ffmpeg와 ffprobe를 "
            "PATH에 넣거나 환경변수 OSMU_FFMPEG_DIR로 폴더를 지정하세요."
        )


def no_window() -> dict:
    """Windows에서 ffmpeg를 띄울 때 검은 cmd 창이 깜빡이지 않게 하는 subprocess 인자(다른 OS에서는 빈 값)."""
    if os.name == "nt":
        import subprocess
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


# --- H.264 인코더 선택 --------------------------------------------------------
# libx264는 GPL 빌드에만 있다. LGPL 빌드(배포 라이선스 부담이 작음)에는 없으므로, 있는 인코더를 찾아 쓴다:
# libx264 → libopenh264 → h264_mf(Windows Media Foundation, 별도 라이브러리 없이 동작) → 없으면 오류.
_encoder_cache: dict = {}


def _encoders() -> str:
    key = ffmpeg()
    if key not in _encoder_cache:
        try:
            import subprocess
            _encoder_cache[key] = subprocess.run([key, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20,
                                                   **no_window()).stdout
        except Exception:  # noqa: BLE001
            _encoder_cache[key] = ""
    return _encoder_cache[key]


def h264_encoder() -> str:
    listing = _encoders()
    for name in ("libx264", "libopenh264", "h264_mf"):
        if re.search(rf"\b{name}\b", listing):
            return name
    return "libx264"      # 목록을 못 읽었을 때의 기본값(실패하면 FFmpeg가 분명한 오류를 낸다)


def h264_args(quality: str = "good", speed: str = "medium") -> list:
    """선택한 H.264 인코더에 맞는 품질 인자. quality: good(CRF≈20 / 6Mbps) | high(CRF≈18 / 8Mbps)."""
    enc = h264_encoder()
    crf = "18" if quality == "high" else "20"
    if enc == "libx264":
        return ["-c:v", enc, "-preset", speed, "-crf", crf]
    return ["-c:v", enc, "-b:v", "8M" if quality == "high" else "6M"]
