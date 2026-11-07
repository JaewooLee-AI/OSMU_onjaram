"""OS clipboard helper for the Naver semi-auto publisher.

Naver's Smart Editor ONE only accepts rich content via an actual paste
(Cmd/Ctrl+V) — there's no API to inject HTML into its DOM directly — so the
publish automation has to put real HTML on the OS clipboard first, exactly
like cjc_blog_v2/clipboard_manager.py does.

Originally scoped to macOS only (via `osascript`), since that's the only
platform this admin engine used to run on. The Windows port fell back to
`pyperclip.copy(html_content)`, which puts the HTML source on the clipboard
as *plain text* — Windows has no "set the clipboard to HTML" shell one-liner
the way macOS does via `osascript`. A plain-text paste doesn't get
interpreted as markup at all, so Naver's editor (and any other rich-text
target) inserted the literal `<p>...</p>` tags as visible characters instead
of paragraph breaks. Windows needs the actual `CF_HTML` clipboard format
(a text format with byte-offset header fields pointing at a fragment inside
a full HTML wrapper) written via the Win32 clipboard API for a browser paste
to recognize it as HTML.
"""
from __future__ import annotations

import re
import subprocess
import sys

# Naver's editor sometimes auto-applies strikethrough to pasted text that
# happens to contain certain characters — strip any pre-existing strike
# markup so it can't compound with that quirk.
_STRIKE_TAG_RE = re.compile(r"</?(?:del|s|strike)\b[^>]*>", re.IGNORECASE)
_STRIKE_STYLE_RE = re.compile(r"text-decoration\s*:\s*line-through\s*;?", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _sanitize_html(html_content: str) -> str:
    html_content = _STRIKE_TAG_RE.sub("", html_content)
    html_content = _STRIKE_STYLE_RE.sub("", html_content)
    return html_content


def _build_cf_html(fragment_html: str) -> bytes:
    """Wraps `fragment_html` in the Windows CF_HTML clipboard format.

    CF_HTML is plain text with a fixed-width header (Version + four
    byte-offset fields) followed by an HTML document; browsers read the
    StartFragment/EndFragment offsets to know which slice to actually paste.
    Offsets must be computed *after* the header exists, but the header's own
    length depends on the offsets — solved the standard way, by zero-padding
    every offset to a fixed 10 digits so the header's byte length is fixed
    before the real numbers are filled in.
    """
    header_template = (
        "Version:0.9\r\n"
        "StartHTML:{start_html:010d}\r\n"
        "EndHTML:{end_html:010d}\r\n"
        "StartFragment:{start_fragment:010d}\r\n"
        "EndFragment:{end_fragment:010d}\r\n"
    )
    header_len = len(header_template.format(start_html=0, end_html=0, start_fragment=0, end_fragment=0).encode("utf-8"))
    prefix = "<html><body>\r\n<!--StartFragment-->"
    suffix = "<!--EndFragment-->\r\n</body></html>"

    start_html = header_len
    start_fragment = start_html + len(prefix.encode("utf-8"))
    end_fragment = start_fragment + len(fragment_html.encode("utf-8"))
    end_html = end_fragment + len(suffix.encode("utf-8"))

    header = header_template.format(
        start_html=start_html, end_html=end_html,
        start_fragment=start_fragment, end_fragment=end_fragment,
    )
    return (header + prefix + fragment_html + suffix).encode("utf-8")


_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002


def _copy_html_windows(html_content: str) -> bool:
    """Writes CF_HTML + CF_UNICODETEXT with ctypes (user32/kernel32).

    pywin32 used to do this, but bundling it made `flet build`'s compileall
    hang on CI, and ctypes needs no extra package. Every Win32 call gets
    explicit argtypes/restype so 64-bit handles/pointers are not truncated to
    a C int.
    """
    try:
        import ctypes
        import time
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterClipboardFormatW.restype = wintypes.UINT
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
        kernel32.GlobalFree.restype = wintypes.HANDLE

        cf_html = user32.RegisterClipboardFormatW("HTML Format")
        if not cf_html:
            raise ctypes.WinError(ctypes.get_last_error())

        def set_data(fmt: int, data: bytes) -> None:
            handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                err = ctypes.get_last_error()
                kernel32.GlobalFree(handle)
                raise ctypes.WinError(err)
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(fmt, handle):
                err = ctypes.get_last_error()
                kernel32.GlobalFree(handle)  # 실패했을 때만 직접 해제한다
                raise ctypes.WinError(err)
            # 성공하면 클립보드가 handle을 소유하므로 해제하지 않는다.

        plain_text = _TAG_RE.sub("", html_content)
        text_bytes = (plain_text + "\0").encode("utf-16-le")
        html_bytes = _build_cf_html(html_content) + b"\0"

        # 다른 프로그램이 클립보드를 잡고 있으면 OpenClipboard가 잠깐 실패한다 — 재시도.
        for _ in range(10):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.05)
        else:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not user32.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            set_data(cf_html, html_bytes)
            set_data(_CF_UNICODETEXT, text_bytes)
        finally:
            user32.CloseClipboard()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[clipboard_utils] win32 HTML clipboard failed, falling back to plain text: {exc}")
        return False


def copy_html_to_clipboard(html_content: str) -> bool:
    """Puts rich HTML on the system clipboard so a subsequent Cmd/Ctrl+V
    pastes formatted content (not literal HTML tags as plain text)."""
    html_content = _sanitize_html(html_content)

    if sys.platform == "darwin":
        try:
            hex_data = html_content.encode("utf-8").hex()
            applescript = f"set the clipboard to {{«class HTML»:«data HTML{hex_data}»}}"
            proc = subprocess.Popen(["osascript", "-e", applescript], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            proc.communicate()
            return proc.returncode == 0
        except Exception as exc:  # noqa: BLE001
            print(f"[clipboard_utils] osascript HTML clipboard failed, falling back to plain text: {exc}")

    elif sys.platform == "win32":
        if _copy_html_windows(html_content):
            return True

    try:
        import pyperclip

        pyperclip.copy(html_content)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[clipboard_utils] pyperclip fallback failed: {exc}")
        return False
