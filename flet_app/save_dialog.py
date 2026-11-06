"""파일 저장 도우미 — 데스크톱 앱과 웹 모드(브라우저)에서 같은 코드로 저장합니다.

- 데스크톱: 저장 위치 대화상자를 열고 그 경로에 씁니다(확장자가 없으면 붙임).
- 웹 모드: 서버 파일 시스템에 쓸 수 없으므로 내용을 브라우저로 보내 **다운로드**하게 합니다. 이때 Flet은 `src_bytes`가
  반드시 필요하고(없으면 오류), 저장 경로를 돌려주지 않습니다.
"""
from __future__ import annotations

import io
import os
import zipfile
from typing import List, Optional, Tuple

import flet as ft


def is_web(page) -> bool:
    return bool(getattr(page, "web", False))


async def save_bytes(page, data: bytes, file_name: str, ext: Optional[str] = None, title: str = "저장") -> Tuple[Optional[str], str]:
    """(저장한 경로 또는 파일 이름, 방식). 사용자가 취소하면 (None, "")."""
    picker = ft.FilePicker()
    if is_web(page):
        await picker.save_file(dialog_title=title, file_name=file_name, src_bytes=data)
        return file_name, "download"
    kwargs = {"file_type": ft.FilePickerFileType.CUSTOM, "allowed_extensions": [ext]} if ext else {}
    path = await picker.save_file(dialog_title=title, file_name=file_name, **kwargs)
    if not path:
        return None, ""
    if ext and not path.endswith("." + ext):
        path += "." + ext
    with open(path, "wb") as fh:
        fh.write(data)
    return path, "file"


def zip_files(paths: List[str], prefix: str = "") -> bytes:
    """파일들을 한 zip으로 묶어 메모리에 만든다(웹 모드 다운로드용)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:       # PNG는 이미 압축돼 있어 저장만
        for p in paths:
            z.write(p, f"{prefix}{os.path.basename(p)}")
    return buf.getvalue()
