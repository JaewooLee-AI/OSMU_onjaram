"""화면에 그림을 보이는 공통 도우미.

로컬 파일 경로를 `ft.Image(src=…)`에 그대로 주면 데스크톱 앱에서는 보이지만 웹 모드(브라우저)에서는 서버 파일에 접근할 수
없어 그림이 비어 보입니다. 파일을 줄여서 base64로 넘기면 두 방식 모두에서 같게 보이고, 큰 사진을 그대로 싣지도 않습니다.
"""
from __future__ import annotations

import base64
import io
import os
from typing import Optional

from PIL import Image, ImageOps


def b64_src(path: str, width: int) -> Optional[str]:
    """그림 파일 → `width`px로 줄인 JPEG의 base64. 읽을 수 없으면 None(HEIC 등 Pillow가 못 여는 형식)."""
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            if im.width > width:
                im = im.resize((width, max(1, int(im.height * width / im.width))))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=88)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 — 깨진 파일 하나가 화면 전체를 막지 않게
        return None


def fit_size(path: str, max_w: int, max_h: int) -> tuple[int, int]:
    """그림을 비율 그대로 (max_w, max_h) 안에 맞췄을 때의 크기. 읽을 수 없으면 최대 크기를 돌려줍니다.
    그림 상자를 이 크기로 두면 빈 여백이 없어 바로 아래 글(사진 설명)이 그림에 붙어 보입니다."""
    try:
        with Image.open(path) as im:
            w, h = ImageOps.exif_transpose(im).size
        if w <= 0 or h <= 0:
            return max_w, max_h
        scale = min(max_w / w, max_h / h, 1.0)
        return max(1, round(w * scale)), max(1, round(h * scale))
    except Exception:  # noqa: BLE001
        return max_w, max_h


def image_or_placeholder(path: str, width: int, height: int, fit=None, **kwargs):
    """줄인 그림을 보여 주고, 못 읽으면 파일 이름이 적힌 회색 상자를 보여 줍니다."""
    import flet as ft

    src = b64_src(path, max(width, 1) * 2) if os.path.exists(path) else None
    if src is None:
        return ft.Container(width=width, height=height, bgcolor="#F3F1EC", border_radius=6, alignment=ft.Alignment.CENTER,
                            content=ft.Text(os.path.basename(path)[:14] or "사진", size=10, color="#8A8A8A", text_align=ft.TextAlign.CENTER))
    return ft.Image(src=src, width=width, height=height, fit=fit or ft.BoxFit.CONTAIN, **kwargs)
