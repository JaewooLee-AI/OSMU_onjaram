"""쇼츠 배경 음악(cards/bgm.py)과 '화면 내용을 읽는' 대본, 읽을 시간 쉼 제한."""
import asyncio
import os
import re
import subprocess

import pytest

from cards import bgm, ffmpeg_tools, shorts_script, shorts_typo
from cards.schema import CardSlide
from cards.shorts_renderer import ShortsOptions, ShortsRendererService
from test_shorts import _fake_tts
from test_shorts_ed import _sb, seeded  # noqa: F401 — seeded는 자동 적용 픽스처

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_tools.available(), reason="FFmpeg 없음")


# --- 앱에 담긴 음원은 라이선스 표에 있어야 한다 ---------------------------------------------------------
def test_bundled_music_is_listed_in_licenses():
    table = open(os.path.join(bgm.APP_DIR, "LICENSES.md"), encoding="utf-8").read()
    listed = set(re.findall(r"^\|\s*([^|\s][^|]*?)\s*\|", table, re.M))
    for t in bgm.tracks():
        if t["kind"] == "app":
            assert t["file"] in listed, f"{t['file']}을 cards/music/LICENSES.md에 적어 주세요(출처·라이선스)"


def test_user_tracks_add_resolve_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(bgm, "USER_DIR", str(tmp_path / "music"))
    src = tmp_path / "calm-piano-12345.mp3"
    src.write_bytes(b"ID3fake")
    t = bgm.add_user_track(str(src))
    assert t["id"] == "user:calm-piano-12345.mp3" and t["name"] == "calm piano"
    assert bgm.resolve(t["id"]) == t["path"]
    again = bgm.add_user_track(str(src))              # 같은 이름은 번호를 붙여 따로
    assert again["id"] != t["id"]
    assert bgm.resolve("user:../secret.mp3") is None and bgm.resolve("") is None
    with pytest.raises(ValueError):
        bgm.add_user_track(str(tmp_path / "x.txt"))
    assert bgm.remove_user_track(t["id"]) and bgm.resolve(t["id"]) is None
    assert not bgm.remove_user_track("app:anything.mp3")     # 앱에 담긴 음원은 지우지 않음


# --- 대본: 화면에 보이는 카드 내용을 빠짐없이 ----------------------------------------------------------
def _slide(t, body="", take=""):
    return CardSlide(slide_number=1, slide_type=t, lead_headline="쉬어도 *피곤한* 이유", body_content=body, takeaway=take)


def test_screen_narration_reads_everything_on_screen():
    n = shorts_script.screen_narration(_slide("checklist", "- 잠이 자주 깨요: 자고 일어나도 개운하지 않아요\n- 작은 일에도 짜증이 나요",
                                              "오래 이어지면 이야기를 나눠 보세요"))
    for part in ("쉬어도 피곤한 이유", "잠이 자주 깨요", "자고 일어나도 개운하지 않아요", "작은 일에도 짜증이 나요", "오래 이어지면"):
        assert part in n
    n = shorts_script.screen_narration(_slide("body", "몸은 쉬어도 생각은\n계속 일해요.\n걱정을 적어 보세요", "생각에도 쉼이 필요해요"))
    assert n == "쉬어도 피곤한 이유. 몸은 쉬어도 생각은 계속 일해요. 걱정을 적어 보세요. 생각에도 쉼이 필요해요."
    assert "첫째, 숨 고르기" in shorts_script.screen_narration(_slide("steps", "1. 숨 고르기\n2. 적어 보기"))
    assert "일정, 매주 화요일" in shorts_script.screen_narration(_slide("event_info", "- 일정: 매주 화요일"))


def test_convert_follows_screen_by_default_and_can_trim(tmp_path):
    sb = _sb(tmp_path)
    long_body = "\n".join(f"{i}번째 문장은 꽤 길게 이어지는 설명입니다." for i in range(1, 7))
    for s in sb.card_slides:
        if s.slide_type == "body":
            s.body_content = long_body
    full, _ = shorts_script.convert(sb, seconds=20)
    short, _ = shorts_script.convert(sb, seconds=20, follow_screen=False)
    i = next(k for k, s in enumerate(sb.card_slides) if s.slide_type == "body")
    assert "5번째 문장" in full[i].narration_script and "6번째" not in full[i].narration_script   # 화면에 보이는 5줄까지
    assert len(short[i].narration_script) < len(full[i].narration_script)


# --- 렌더: 쉼 제한·음악 섞기 ---------------------------------------------------------------------------
def _dur(path):
    return float(subprocess.run([ffmpeg_tools.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True).stdout.strip())


def _mean_db(path, start, length):
    err = subprocess.run([ffmpeg_tools.ffmpeg(), "-hide_banner", "-ss", str(start), "-t", str(length), "-i", path, "-af", "volumedetect",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", err)
    return float(m.group(1)) if m else -91.0


@needs_ffmpeg
def test_read_padding_is_capped_and_music_fills_silence(tmp_path):
    sb = _sb(tmp_path)
    for sc in sb.shorts_scenes:
        sc.narration_script = "짧게."           # 음성(무음 가짜) 1초 — 화면 글자는 많다
    tone = tmp_path / "tone.mp3"
    subprocess.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=3", str(tone)], check=True)
    r = ShortsRendererService(export_dir=str(tmp_path / "out"))
    mp4 = asyncio.run(r.render_shorts_video(sb, options=ShortsOptions(frame_style="tri", tts_call=_fake_tts, photo_motion="none",
                                                                      text_motion="none", music=str(tone), music_volume="mid")))
    n = len(sb.shorts_scenes)
    assert _dur(mp4) <= n * (1.0 + 0.3 + shorts_typo.PAD_MAX) + 0.5      # 장면당 쉼은 최대 PAD_MAX초
    assert any("배경 음악" in x for x in r.last_notes), r.last_notes
    assert _mean_db(mp4, 1.5, 1.0) > -40                                  # 가짜 음성은 무음 → 들리는 것은 음악
    assert not [w for w in r.last_warnings if "음악" in w]


@needs_ffmpeg
def test_missing_music_warns_and_still_renders(tmp_path):
    sb = _sb(tmp_path)
    r = ShortsRendererService(export_dir=str(tmp_path / "out"))
    mp4 = asyncio.run(r.render_shorts_video(sb, options=ShortsOptions(frame_style="tri", tts_call=_fake_tts, photo_motion="none",
                                                                      text_motion="none", music="user:없는곡.mp3")))
    assert os.path.getsize(mp4) > 10_000
    assert any("배경 음악" in w for w in r.last_warnings)
