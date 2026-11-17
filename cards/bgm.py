"""쇼츠 배경 음악.

음원은 두 곳에서 찾습니다.
- 사용자가 넣은 음원(기본 방식): 데이터 폴더 `music/` (설정 → 📣 생성 채널의 [배경 음악 추가]로 복사, PC마다).
- 앱에 담긴 음원: `cards/music/` — 지금은 없음. 무료 음원 라이선스가 대개 원본 단독 재배포를 금지해서 이 폴더의 음원은
  `.gitignore`로 막았다. 재배포가 허용되는 음원을 담을 때만 예외를 더하고 `cards/music/LICENSES.md`에 적는다(시험이 확인).

음원 id는 'app:<파일 이름>' · 'user:<파일 이름>'. 빈 문자열은 '음악 없음'.
섞을 때는 음악을 쇼츠 길이만큼 반복하고, 말소리가 나는 동안 음악을 자동으로 줄였다가(사이드체인 압축) 쉬는 곳에서 되돌리며,
처음 1초는 서서히 키우고 끝 2초는 서서히 줄입니다.
"""
from __future__ import annotations

import os
import shutil
from typing import Dict, List, Optional

from cards.paths import CARDS_DIR, DATA_DIR

APP_DIR = os.path.join(CARDS_DIR, "music")
USER_DIR = os.path.join(DATA_DIR, "music")
EXTS = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac")
MAX_MB = 30
VOLUMES = {"low": 0.10, "mid": 0.18, "high": 0.28}   # 말이 없을 때 음악 크기(음성 대비). 말할 때는 이보다 더 줄어듦
VOLUME_LABELS = {"low": "작게", "mid": "보통", "high": "크게"}
DEFAULT_VOLUME = "mid"


class MusicTooLarge(ValueError):
    pass


def _name(fname: str) -> str:
    stem = os.path.splitext(fname)[0]
    parts = [p for p in stem.replace("_", "-").split("-") if p]
    if parts and parts[-1].isdigit():          # 내려받은 사이트의 번호 꼬리는 뺀다
        parts = parts[:-1]
    return " ".join(parts) or stem


def _scan(folder: str, kind: str) -> List[Dict[str, str]]:
    if not os.path.isdir(folder):
        return []
    out = []
    for f in sorted(os.listdir(folder)):
        if f.lower().endswith(EXTS) and not f.startswith("."):
            out.append({"id": f"{kind}:{f}", "name": _name(f), "file": f, "path": os.path.join(folder, f), "kind": kind})
    return out


def tracks() -> List[Dict[str, str]]:
    """고를 수 있는 음원(앱에 담긴 것 먼저)."""
    return _scan(APP_DIR, "app") + _scan(USER_DIR, "user")


def label(track: Dict[str, str]) -> str:
    return track["name"] + (" (내가 넣은 음원)" if track["kind"] == "user" else " (기본 음원)")


def resolve(track_id: Optional[str]) -> Optional[str]:
    """음원 id → 파일 경로. 없거나 지워졌으면 None. 파일 경로를 직접 주면(시험·고급) 그 파일."""
    if not track_id:
        return None
    if os.path.isfile(track_id):
        return track_id
    kind, _, fname = track_id.partition(":")
    folder = {"app": APP_DIR, "user": USER_DIR}.get(kind)
    if not folder or not fname or os.path.basename(fname) != fname:
        return None
    path = os.path.join(folder, fname)
    return path if os.path.isfile(path) else None


def add_user_track(src: str) -> Dict[str, str]:
    """음원 파일을 데이터 폴더 music/으로 복사한다. 같은 이름이 있으면 뒤에 번호를 붙인다."""
    fname = os.path.basename(src)
    if not fname.lower().endswith(EXTS):
        raise ValueError(f"음원 파일({', '.join(EXTS)})만 넣을 수 있습니다.")
    if os.path.getsize(src) > MAX_MB * 1024 * 1024:
        raise MusicTooLarge(f"음원은 한 곡에 {MAX_MB}MB까지 넣을 수 있습니다.")
    os.makedirs(USER_DIR, exist_ok=True)
    stem, ext = os.path.splitext(fname)
    dest, n = os.path.join(USER_DIR, fname), 2
    while os.path.exists(dest):
        dest = os.path.join(USER_DIR, f"{stem}_{n}{ext}")
        n += 1
    shutil.copyfile(src, dest)
    f = os.path.basename(dest)
    return {"id": f"user:{f}", "name": _name(f), "file": f, "path": dest, "kind": "user"}


def remove_user_track(track_id: str) -> bool:
    """사용자가 넣은 음원만 지운다(앱에 담긴 음원은 지우지 않음)."""
    if not (track_id or "").startswith("user:"):
        return False
    path = resolve(track_id)
    if path and os.path.dirname(os.path.abspath(path)) == os.path.abspath(USER_DIR):
        os.remove(path)
        return True
    return False


def volume_of(key: Optional[str]) -> float:
    return VOLUMES.get(key or DEFAULT_VOLUME, VOLUMES[DEFAULT_VOLUME])


def mix_args(voice: str, music: str, total: float, volume: float, out: str) -> List[str]:
    """FFmpeg 인자(실행 파일 제외): 음성 + 반복한 음악(말할 때 줄임, 앞뒤 서서히) → out(mp3)."""
    fade_out = max(0.0, total - 2.0)
    graph = (
        f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={volume:.3f},"
        f"afade=t=in:st=0:d=1,afade=t=out:st={fade_out:.3f}:d=2,atrim=end={total:.3f}[m];"
        "[0:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[v][key];"
        "[m][key]sidechaincompress=threshold=0.02:ratio=6:attack=30:release=600:makeup=1[duck];"
        "[v][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[out]"
    )
    return ["-y", "-v", "error", "-i", voice, "-stream_loop", "-1", "-i", music, "-filter_complex", graph,
            "-map", "[out]", "-t", f"{total:.3f}", "-c:a", "libmp3lame", "-b:a", "192k", out]
