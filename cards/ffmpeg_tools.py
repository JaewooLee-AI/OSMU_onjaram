"""FFmpeg·ffprobe 실행 파일 위치 찾기 — Windows 설치형은 앱에 동봉한 것을 쓰고, 없으면 PATH를 봅니다.

찾는 순서: 환경변수 OSMU_FFMPEG_DIR → 패키지 안 `cards/bin/` (설치 프로그램에 동봉) → 데이터 폴더 `bin/` → PATH.
설치 폴더(Program Files)에는 쓰지 않으므로 동봉 파일은 읽기만 합니다. 동봉 빌드와 라이선스는 docs/FFMPEG_동봉.md 참고.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from typing import Optional, Tuple

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


_duration_cache: dict = {}


def probe_duration(path: str) -> float:
    """미디어 파일의 길이(초)를 ffprobe로 조회한다. 실패하거나 FFmpeg가 없으면 0.0.
    같은 파일(경로·크기·수정 시각)은 한 번만 묻는다 — 화면을 다시 그릴 때마다 영상마다 ffprobe를 띄우지 않게."""
    if not path or not os.path.isfile(path) or not available():
        return 0.0
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_size, int(st.st_mtime))
    if key in _duration_cache:
        return _duration_cache[key]
    try:
        import subprocess
        res = subprocess.run(
            [ffprobe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15, **no_window(),
        )
        dur = max(0.0, float((res.stdout or "").strip()))
    except Exception:  # noqa: BLE001
        return 0.0
    if dur > 0:
        _duration_cache[key] = dur
    return dur


def probe_size(path: str) -> Tuple[int, int]:
    """미디어의 화면 크기(가로, 세로). 휴대폰 영상의 회전 표시(90·270도)는 반영한다. 실패하면 (0, 0)."""
    if not path or not os.path.isfile(path) or not available():
        return (0, 0)
    try:
        import json
        import subprocess
        res = subprocess.run([ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height:stream_tags=rotate:stream_side_data=rotation", "-of", "json", path],
                             capture_output=True, text=True, timeout=15, **no_window())
        st = (json.loads(res.stdout or "{}").get("streams") or [{}])[0]
        w, h = int(st.get("width") or 0), int(st.get("height") or 0)
        rot = (st.get("tags") or {}).get("rotate")
        for sd in st.get("side_data_list") or []:
            rot = sd.get("rotation", rot)
        if rot is not None and abs(int(float(rot))) % 180 == 90:
            w, h = h, w
        return (w, h)
    except Exception:  # noqa: BLE001
        return (0, 0)


def extract_frame(video_path: str, time_sec: Optional[float] = None) -> Optional[bytes]:
    """동영상에서 대표 프레임 1장을 PNG 바이트로 추출한다. 실패 시 None."""
    if not video_path or not os.path.isfile(video_path) or not available():
        return None
    import subprocess
    import tempfile
    dur = probe_duration(video_path)
    if time_sec is None:
        t = min(max(0.2, dur * 0.35), max(0.2, dur - 0.2)) if dur > 0.4 else 0.0
    else:
        t = max(0.0, min(time_sec, max(0.0, dur - 0.1))) if dur > 0 else max(0.0, time_sec)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "frame.png")
            subprocess.run(
                [ffmpeg(), "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", video_path, "-frames:v", "1", out],
                check=True, capture_output=True, timeout=20, **no_window(),
            )
            if os.path.isfile(out):
                with open(out, "rb") as f:
                    return f.read()
    except Exception:  # noqa: BLE001
        pass
    return None

