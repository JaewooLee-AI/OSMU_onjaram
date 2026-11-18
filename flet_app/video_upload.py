"""동영상 올리기 — 고르기·받기·저장을 진행 창(막대 + 퍼센트)과 함께.

- 데스크톱(Windows 설치본): 고른 파일의 경로를 그대로 받는다. 저장(같은 영상인지 확인 → 데이터 폴더로 복사)은
  화면 스레드 밖에서 하고 진행률을 보여 준다. 화면 스레드에서 큰 파일을 다루면 Windows가 '응답 없음'으로 본다.
- 브라우저 실행(localhost): 파일 내용을 화면 연결로 통째로 받으면 큰 영상에서 멈춘다. 그래서 Flet 내장 업로드
  (`FilePicker.upload` → `ft.run(upload_dir=…)`)로 받고, 10%마다 오는 진행 알림을 진행 창에 보여 준다.
  받은 파일은 데이터 폴더 `uploads_tmp/`에 잠깐 두었다가 저장 후 지운다.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import uuid
from dataclasses import dataclass
from typing import List, Optional

import flet as ft

from cards.paths import DATA_DIR
from core import storage

UPLOAD_DIR = os.path.join(DATA_DIR, "uploads_tmp")
UPLOAD_TIMEOUT = 60 * 60          # 브라우저 업로드 한 번을 기다리는 최대 시간(초)


def prepare_server() -> str:
    """앱 시작 전에 부른다: 업로드 서명 키(실행할 때마다 새로, 파일에 쓰지 않음)와 임시 업로드 폴더를 준비하고 그 경로를 돌려준다."""
    os.environ.setdefault("FLET_SECRET_KEY", secrets.token_urlsafe(32))
    shutil.rmtree(UPLOAD_DIR, ignore_errors=True)       # 지난번에 남은 임시 파일
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    return UPLOAD_DIR


@dataclass
class Picked:
    name: str
    path: Optional[str] = None     # 받은 파일 경로(실패하면 None)
    size: int = 0
    error: str = ""
    temp: bool = False             # 브라우저 업로드로 받은 임시 파일(저장 후 지움)


def _mb(n: float) -> str:
    return f"{n / 1024 / 1024:.0f}MB"


class UploadProgress:
    """진행 창: 제목 + 지금 하는 일 + 진행 막대(0~1, 모르면 움직이는 막대). 다른 스레드에서 set()을 불러도 된다."""

    def __init__(self, page: ft.Page, title: str):
        self.page = page
        self.text = ft.Text("준비 중…", size=13)
        self.bar = ft.ProgressBar(value=None, width=420)
        self.note = ft.Text("끝날 때까지 창을 닫지 말고 기다려 주세요. 큰 영상은 1분 넘게 걸릴 수 있습니다.", size=11, color="#6E7378")
        self.dialog = ft.AlertDialog(modal=True, title=ft.Text(title),
                                     content=ft.Column([self.text, self.bar, self.note], tight=True, spacing=12, width=420))
        self._shown = False
        self._last = -1.0

    def open(self) -> None:
        if not self._shown:
            self.page.show_dialog(self.dialog)
            self._shown = True

    def set(self, msg: str, value: Optional[float] = None) -> None:
        if value is not None and self._last >= 0 and abs(value - self._last) < 0.02 and value < 1:
            return                                      # 너무 잦은 화면 갱신은 건너뜀(2% 단위)
        self._last = -1.0 if value is None else value
        self.text.value = msg
        self.bar.value = value
        try:
            self.text.update()
            self.bar.update()
        except Exception:  # noqa: BLE001 — 창이 닫힌 뒤의 갱신은 무시
            pass

    def close(self) -> None:
        if self._shown:
            try:
                self.page.pop_dialog()
            except Exception:  # noqa: BLE001
                pass
            self._shown = False


async def pick_videos(page: ft.Page, prog: UploadProgress) -> List[Picked]:
    """동영상을 고르게 하고 받아 온다. 고르기를 취소하면 []. 진행 창은 파일을 고른 뒤에 연다."""
    web = bool(getattr(page, "web", False))
    status: dict = {}              # 파일 이름 → 오류 문구(성공은 "")
    ended: list = []               # 끝난(성공·실패) 알림 수 — 이름이 같은 파일이 있어도 편 수로 기다림
    finished = asyncio.Event()
    expect: list = []

    def on_upload(e) -> None:
        name = e.file_name
        if e.error:
            status[name] = e.error
            ended.append(name)
        elif e.progress is not None:
            prog.set(f"{name} 받는 중… {e.progress:.0%}", e.progress)
            if e.progress >= 1.0:
                status.setdefault(name, "")
                ended.append(name)
        if expect and len(ended) >= len(expect):
            finished.set()

    fp = ft.FilePicker(on_upload=on_upload)
    files = await fp.pick_files(allow_multiple=True, file_type=ft.FilePickerFileType.CUSTOM,
                                allowed_extensions=[e.lstrip(".") for e in sorted(storage.VIDEO_EXTS)])
    if not files:
        return []
    prog.open()
    limit = storage.MAX_VIDEO_MB * 1024 * 1024
    out: List[Picked] = []
    for f in files:
        if f.size and f.size > limit:
            out.append(Picked(f.name, size=f.size, error=f"{_mb(f.size)} — {storage.MAX_VIDEO_MB}MB를 넘습니다. 필요한 부분만 잘라서 올려 주세요"))
        elif not web and f.path and os.path.isfile(f.path):
            out.append(Picked(f.name, path=f.path, size=f.size))
        elif not web:
            out.append(Picked(f.name, size=f.size, error="파일을 읽지 못했습니다"))
        else:
            out.append(Picked(f.name, size=f.size))
    if not web:
        return out

    # 브라우저 실행: 내장 업로드로 받는다(진행 알림은 on_upload)
    token = uuid.uuid4().hex[:12]
    todo = [(i, f, p) for i, (f, p) in enumerate(zip(files, out)) if not p.error]
    if todo:
        expect.extend(f.name for _, f, _ in todo)
        prog.set(f"동영상 {len(todo)}편을 받는 중…", 0.0)
        # 파일마다 하위 폴더(번호)를 따로 둔다 — 이름이 같은 영상을 함께 올려도 서로 덮어쓰지 않게
        await fp.upload([ft.FilePickerUploadFile(id=f.id, name=f.name, upload_url=page.get_upload_url(f"{token}/{i}/{f.name}", UPLOAD_TIMEOUT))
                         for i, f, _ in todo])
        try:
            await asyncio.wait_for(finished.wait(), timeout=UPLOAD_TIMEOUT)
        except asyncio.TimeoutError:
            pass
        for i, f, p in todo:
            dest = os.path.join(UPLOAD_DIR, token, str(i), f.name)
            if status.get(f.name):
                p.error = f"받지 못했습니다({status[f.name]})"
            elif os.path.isfile(dest):
                p.path, p.temp = dest, True
            else:
                p.error = "받지 못했습니다(시간 초과 또는 연결 끊김)"
    return out


def save_all(picked: List[Picked], prog: UploadProgress, after_each=None) -> tuple[list[str], list[str]]:
    """받은 영상을 데이터 폴더에 저장한다(다른 스레드에서 부름). 반환: (저장한 rel 경로들, 문제 문구들).
    after_each(picked, rel)를 주면 영상마다 저장 뒤에 부른다(대표 장면 뽑기 등)."""
    saved, problems = [], [f"{p.name}: {p.error}" for p in picked if p.error]
    todo = [p for p in picked if p.path and not p.error]
    for i, p in enumerate(todo, 1):
        head = f"{i}/{len(todo)} · {p.name} ({_mb(p.size or os.path.getsize(p.path))})"
        try:
            rel = storage.save_video(p.name, src_path=p.path,
                                     progress=lambda fr, head=head: prog.set(f"{head} 저장 중… {fr:.0%}", fr))
            saved.append(rel)
            if after_each:
                prog.set(f"{head} 대표 장면 뽑는 중…", None)
                after_each(p, rel)
        except storage.VideoTooLarge as exc:
            problems.append(f"{p.name}: {exc} — {storage.MAX_VIDEO_MB}MB를 넘습니다. 필요한 부분만 잘라서 올려 주세요")
        except OSError as exc:
            problems.append(f"{p.name}: 저장하지 못했습니다({type(exc).__name__})")
        finally:
            if p.temp:
                try:
                    os.remove(p.path)
                except OSError:
                    pass
    return saved, problems
