"""쇼츠: 카드→대본, 음성(가짜 호출)·사용 기록, 3단 프레임 MP4 (실제 FFmpeg 사용 — 없으면 건너뜀)."""
import asyncio
import io
import os
import subprocess
import wave

import pytest

from cards import ffmpeg_tools, shorts_script, tts
from cards.director import plan_cards
from cards.shorts_renderer import ShortsOptions, ShortsRendererService
from core import repo
from core.brand_seed import seed_if_empty

TEXT = ("요즘 이유 없이 지치고 잠도 오지 않아요. 마음이 보내는 신호일 수 있어요.\n"
        "1. 같은 시간에 눕기\n2. 잠들기 전 화면 멀리하기\n3. 따뜻한 차 한 잔 마시기\n혼자 해결하기 어려우면 상담이 있어요.")


@pytest.fixture(autouse=True)
def seeded():
    seed_if_empty()


def _cards(type_id="howto", count=4):
    sb, _ = plan_cards(TEXT, type_id, use_llm=False, count=count)
    return sb


async def _fake_tts(model_id, text, voice):
    n = int(24000 * max(1.0, len(text) / 6.5))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\0\0" * n)
    return buf.getvalue(), {"in": 3, "out": 4}


def test_script_follows_cards_and_fixes_cta():
    sb = _cards()
    scenes, report = shorts_script.convert(sb, seconds=30)
    assert len(scenes) == len(sb.card_slides)
    assert scenes[0].section_type == "hook" and scenes[-1].section_type == "conclusion"
    assert "055-255-1365" in scenes[-1].narration_script            # 상담 안내는 브랜드 킷 값으로 고정
    assert [s.source_cards for s in scenes] == [[c.slide_number] for c in sb.card_slides]
    assert not report["warnings"]
    shorts_script.apply_to_storyboard(sb, scenes)
    assert not shorts_script.is_stale(sb)
    sb.card_slides[1].lead_headline = "바뀐 제목"
    assert shorts_script.is_stale(sb)                                # 카드를 고치면 다시 만들라고 안내


def test_script_blacklist_numbers_and_llm_fallback(monkeypatch):
    sb = _cards()
    sb.card_slides[1].body_content = "정신병 아니에요\n하루 99번 쉬어요"
    scenes, report = shorts_script.convert(sb)
    assert all("정신병" not in s.narration_script for s in scenes)
    monkeypatch.setattr("cards.shorts_script.get_configured_vendor", lambda slot=None: "google")
    llm = '{"scenes": [{"source_cards": [1], "narration_script": "하루 77번 쉬어 보세요.", "display_caption": "쉬어요"}]}'
    scenes, report = shorts_script.convert(sb, use_llm=True, generate=lambda **k: llm)
    assert report["engine"] == "llm" and any("77" in w for w in report["warnings"])   # 카드에 없는 숫자는 경고
    assert scenes[-1].section_type == "conclusion" and "055-255-1365" in scenes[-1].narration_script
    def boom(**k):
        raise RuntimeError("키 없음")
    scenes, report = shorts_script.convert(sb, use_llm=True, generate=boom)
    assert report["engine"] == "rule-based" and any("규칙 기반" in w for w in report["warnings"])


def test_tts_needs_slot_model_and_google(tmp_path):
    with pytest.raises(tts.TtsUnavailable):
        tts.GeminiTTS("auto", str(tmp_path))
    ref = repo.upsert_model("openai", "x", "X", ["tts"])
    repo.set_slot("tts", ref)
    with pytest.raises(tts.TtsUnavailable, match="Google"):
        tts.GeminiTTS("auto", str(tmp_path))


def test_tts_uses_slot_model_logs_cost_and_caches(tmp_path):
    ref = repo.upsert_model("google", "tts-model-x", "T", ["tts"], per_second=0.01)
    repo.set_slot("tts", ref)
    calls = []

    async def counting(model_id, text, voice):
        calls.append((model_id, voice))
        return await _fake_tts(model_id, text, voice)

    engine = tts.GeminiTTS("auto", str(tmp_path / "c"), call=counting)
    outs = [str(tmp_path / f"{i}.wav") for i in range(2)]
    texts = ["첫 번째 문장입니다.", "두 번째 문장입니다."]
    assert asyncio.run(engine.synthesize_all(texts, outs)) == 0
    assert calls == [("tts-model-x", "Aoede")] * 2 and all(os.path.exists(o) for o in outs)   # 슬롯 모델만 쓴다
    usage = [u for u in repo.recent_usage(5) if u["kind"] == "tts"]
    assert len(usage) == 2 and all(u["cost_usd"] and u["media_seconds"] > 0 for u in usage)
    assert asyncio.run(engine.synthesize_all(texts, outs)) == 2 and len(calls) == 2        # 두 번째는 캐시(추가 비용 없음)


@pytest.mark.skipif(not ffmpeg_tools.available(), reason="FFmpeg 없음")
def test_tri_shorts_mp4_is_1080x1920_with_audio_and_logs_voice(tmp_path):
    ref = repo.upsert_model("google", "tts-m", "T", ["tts"], per_second=0.01)
    repo.set_slot("tts", ref)
    sb = _cards()
    scenes, _ = shorts_script.convert(sb, seconds=20)
    shorts_script.apply_to_storyboard(sb, scenes)
    renderer = ShortsRendererService(export_dir=str(tmp_path))
    mp4 = asyncio.run(renderer.render_shorts_video(sb, options=ShortsOptions(frame_style="tri", tts_call=_fake_tts)))
    assert os.path.getsize(mp4) > 10_000 and not os.path.exists(tmp_path / "_work")     # 임시 폴더 정리
    probe = subprocess.run([ffmpeg_tools.ffprobe(), "-v", "error", "-show_entries", "stream=codec_name,width,height,duration",
                            "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout.split()
    assert any(l.startswith("h264,1080,1920") for l in probe) and any(l.startswith("aac") for l in probe)
    assert "Gemini TTS" in renderer.last_tts_engine and not renderer.last_warnings
    assert any(u["kind"] == "tts" for u in repo.recent_usage(10))


@pytest.mark.skipif(not ffmpeg_tools.available(), reason="FFmpeg 없음")
def test_shorts_falls_back_with_visible_warning_when_no_tts_model(tmp_path, monkeypatch):
    """음성 모델이 없으면 무료 음성(또는 무음)으로 대체하고 그 사실을 경고로 남긴다 — 조용히 넘어가지 않는다."""
    monkeypatch.setattr(ShortsRendererService, "_free_tts_scene",
                        lambda self, text, out_base, est: (self._silent(out_base, est), "silent"), raising=False)
    sb = _cards(count=3)
    scenes, _ = shorts_script.convert(sb, seconds=15)
    shorts_script.apply_to_storyboard(sb, scenes)
    renderer = ShortsRendererService(export_dir=str(tmp_path))

    def silent(out_base, est):
        wav = out_base + ".wav"
        subprocess.run([ffmpeg_tools.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "1.5", wav], check=True)
        return wav
    renderer._silent = silent
    mp4 = asyncio.run(renderer.render_shorts_video(sb, options=ShortsOptions(frame_style="tri")))
    assert os.path.exists(mp4) and any("음성 내레이션" in w and "무료 음성" in w for w in renderer.last_warnings)


def test_ffmpeg_resolution_prefers_env_then_bundled(tmp_path, monkeypatch):
    fake = tmp_path / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    fake.write_text("x")
    (tmp_path / ("ffprobe.exe" if os.name == "nt" else "ffprobe")).write_text("x")
    monkeypatch.setenv("OSMU_FFMPEG_DIR", str(tmp_path))
    assert ffmpeg_tools.ffmpeg() == str(fake) and ffmpeg_tools.available()
    monkeypatch.setenv("OSMU_FFMPEG_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(ffmpeg_tools, "_candidates", lambda name: iter(()))
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda n: None)
    with pytest.raises(RuntimeError, match="FFmpeg"):
        ffmpeg_tools.require()


def test_h264_encoder_choice_and_args(monkeypatch):
    monkeypatch.setattr(ffmpeg_tools, "_encoders", lambda: " V..... libopenh264  OpenH264\n V..... h264_mf  H264 via MediaFoundation")
    assert ffmpeg_tools.h264_encoder() == "libopenh264" and "-crf" not in ffmpeg_tools.h264_args()    # LGPL 빌드: x264 전용 인자 안 씀
    monkeypatch.setattr(ffmpeg_tools, "_encoders", lambda: " V..... h264_mf  H264 via MediaFoundation")
    assert ffmpeg_tools.h264_encoder() == "h264_mf" and ffmpeg_tools.h264_args("high")[-1] == "8M"
    monkeypatch.setattr(ffmpeg_tools, "_encoders", lambda: " V..... libx264  x264\n V..... libopenh264  OpenH264")
    assert ffmpeg_tools.h264_args("good", "veryfast") == ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


@pytest.mark.skipif(not ffmpeg_tools.available(), reason="FFmpeg 없음")
def test_tri_shorts_photo_motion_moves_only_the_photo_zone(tmp_path):
    """사진 움직임: 가운데 사진 칸만 시간에 따라 달라지고, 위·아래 글자 칸은 그대로여야 한다."""
    from PIL import Image, ImageChops, ImageDraw
    from cards.schema import MediaAsset
    repo.set_slot("tts", repo.upsert_model("google", "tts-m2", "T", ["tts"], per_second=0.01))
    photo = tmp_path / "p.png"
    img = Image.new("RGB", (1200, 900), "#CCDDCC")
    d = ImageDraw.Draw(img)
    for i in range(0, 1200, 60):
        d.rectangle([i, 100 + (i % 120), i + 30, 700], fill="#446644")
    img.save(photo)
    sb = _cards("empathy", 4)
    sb.assets = [MediaAsset(id="A1", kind="image", source="user", path=str(photo))]
    sb.card_slides[0].asset_id = "A1"            # 표지에 사진
    sb.design_id = "tri-2-5-3@sage"
    scenes, _ = shorts_script.convert(sb, seconds=20)
    shorts_script.apply_to_storyboard(sb, scenes)
    renderer = ShortsRendererService(export_dir=str(tmp_path / "out"))
    mp4 = asyncio.run(renderer.render_shorts_video(
        sb, options=ShortsOptions(frame_style="tri", tts_call=_fake_tts, photo_motion="zoom_in")))
    assert not renderer.last_warnings, renderer.last_warnings
    first_dur = scenes[0].duration_seconds

    def frame(t, name):
        out = tmp_path / name
        subprocess.run([ffmpeg_tools.ffmpeg(), "-y", "-v", "error", "-ss", f"{t}", "-i", mp4, "-frames:v", "1", str(out)], check=True)
        return Image.open(out).convert("RGB")

    a, b = frame(0.2, "a.png"), frame(max(1.0, first_dur - 0.5), "b.png")
    assert a.size == (1080, 1920)
    top = (0, 260, 1080, 520)       # 위 제목 칸(안전 여백 250 바로 아래)
    mid = (0, 700, 1080, 1100)      # 가운데 사진 칸
    assert _changed(a, b, top) < 60       # 압축 잡음 정도만
    assert _changed(a, b, mid) > 200


def _photo_storyboard(tmp_path, count=4):
    from PIL import Image, ImageDraw
    from cards.schema import MediaAsset
    repo.set_slot("tts", repo.upsert_model("google", "tts-m2", "T", ["tts"], per_second=0.01))
    photo = tmp_path / "p.png"
    img = Image.new("RGB", (1200, 900), "#CCDDCC")
    d = ImageDraw.Draw(img)
    for i in range(0, 1200, 60):
        d.rectangle([i, 100 + (i % 120), i + 30, 700], fill="#446644")
    img.save(photo)
    sb = _cards("empathy", count)
    sb.assets = [MediaAsset(id="A1", kind="image", source="user", path=str(photo))]
    for slide in sb.card_slides[:2]:
        slide.asset_id = "A1"
    scenes, _ = shorts_script.convert(sb, seconds=20)
    shorts_script.apply_to_storyboard(sb, scenes)
    return sb, scenes


def _changed(a, b, box, thresh=40):
    """두 그림의 box 안에서 크게 달라진 픽셀 수(H.264 압축 잡음은 무시)."""
    from PIL import ImageChops
    diff = ImageChops.difference(a.crop(box), b.crop(box)).convert("L").point(lambda v: 255 if v > thresh else 0)
    return diff.histogram()[255]


def _grab(mp4, t, path):
    from PIL import Image
    subprocess.run([ffmpeg_tools.ffmpeg(), "-y", "-v", "error", "-ss", f"{t}", "-i", mp4, "-frames:v", "1", str(path)], check=True)
    return Image.open(path).convert("RGB")


def _duration(mp4):
    out = subprocess.run([ffmpeg_tools.ffmpeg(), "-i", mp4], capture_output=True, text=True).stderr
    import re
    h, m, sec = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(sec)


@pytest.mark.skipif(not ffmpeg_tools.available(), reason="FFmpeg 없음")
def test_tri_shorts_dynamic_motion_text_slide_and_transitions(tmp_path):
    """다이나믹 사진 움직임 + 글자 슬라이드 + 장면 전환: 글자는 등장이 끝나면 멈추고, 사진은 계속 움직이고, 길이는 음성과 맞는다."""
    from PIL import ImageChops
    sb, scenes = _photo_storyboard(tmp_path)
    sb.design_id = "tri-2-5-3@sage"
    renderer = ShortsRendererService(export_dir=str(tmp_path / "out"))
    mp4 = asyncio.run(renderer.render_shorts_video(sb, options=ShortsOptions(
        frame_style="tri", tts_call=_fake_tts, photo_motion="dynamic", text_motion="slide", transition="auto")))
    assert not renderer.last_warnings, renderer.last_warnings
    if os.environ.get("OSMU_SAMPLE_OUT"):
        import shutil
        shutil.copy(mp4, os.environ["OSMU_SAMPLE_OUT"])
    first = scenes[0].duration_seconds
    early, settled, late = _grab(mp4, 0.05, tmp_path / "e.png"), _grab(mp4, 1.2, tmp_path / "s.png"), _grab(mp4, max(1.6, first - 0.8), tmp_path / "l.png")
    top = (0, 260, 1080, 520)
    mid = (0, 700, 1080, 1100)
    assert early.size == (1080, 1920)
    assert _changed(early, settled, top) > 500     # 등장 중에는 달라진다
    assert _changed(settled, late, top) < 60       # 등장이 끝나면 멈춘다(압축 잡음만)
    assert _changed(settled, late, mid) > 200      # 사진은 계속 움직인다
    total = sum(sc.duration_seconds for sc in scenes)
    assert abs(_duration(mp4) - _duration(str(tmp_path / "out" / "combined_narration.mp3"))) < 0.5


def test_voice_estimate_uses_token_price_when_registered():
    """TTS 공식 단가는 100만 토큰당이다 — 토큰 단가만 등록해도 실행 전 예상 금액이 나와야 한다('단가 미등록' 아님)."""
    from types import SimpleNamespace
    from flet_app.views.shorts_studio import describe_voice_estimate, estimate_voice

    sb = SimpleNamespace(shorts_scenes=[SimpleNamespace(narration_script="가" * 130)])
    ref = repo.upsert_model("google", "tts-est-x", "T", ["tts"])
    repo.set_slot("tts", ref)
    est = estimate_voice(sb)
    assert est["usd"] is None and "단가 미등록" in describe_voice_estimate(est)

    repo.save_model_price("google", "tts-est-x", 0.5, 9.0)
    est = estimate_voice(sb)
    assert est["usd"] is not None and est["usd"] > 0 and "예상 약 $" in describe_voice_estimate(est)
    assert est["basis"] == "토큰 단가 기준 어림"


@pytest.mark.skipif(not ffmpeg_tools.available(), reason="FFmpeg 없음")
def test_silent_test_voice_makes_video_without_tts_or_usage(tmp_path):
    """테스트 전용 '음성 없음': 음성 모델 호출·사용 기록 없이 무음 영상이 만들어지고 경고로 알려 준다."""
    sb, scenes = _photo_storyboard(tmp_path)
    called = []

    async def boom(*a, **k):
        called.append(1)
        raise AssertionError("TTS를 부르면 안 됩니다")

    before = len(repo.list_usage()) if hasattr(repo, "list_usage") else 0
    renderer = ShortsRendererService(export_dir=str(tmp_path / "out"))
    mp4 = asyncio.run(renderer.render_shorts_video(sb, options=ShortsOptions(
        frame_style="tri", voice="silent", tts_call=boom, photo_motion="dynamic", text_motion="slide", transition="auto")))
    assert not called and os.path.exists(mp4)
    assert any("무음" in w for w in renderer.last_warnings)
    assert abs(_duration(mp4) - sum(max(1.0, s.duration_seconds) for s in scenes) - 0.3 * (len(scenes) - 1)) < 1.0
    from flet_app.views.shorts_studio import voice_note
    assert "비용 없음" in voice_note("silent", {})


def test_non_tri_design_shorts_keeps_the_card_design_centered_in_9x16(tmp_path):
    """3단이 아닌 디자인(온자람)은 카드를 그 모양 그대로 9:16 화면 가운데 놓고, 움직임·전환을 적용해도 길이가 음성과 맞는다."""
    sb, scenes = _photo_storyboard(tmp_path)
    assert sb.design_id == "editorial"   # 기본 디자인(3단이 아님) → 카드 모양 그대로
    renderer = ShortsRendererService(export_dir=str(tmp_path / "out"))
    mp4 = asyncio.run(renderer.render_shorts_video(sb, options=ShortsOptions(
        frame_style="tri", tts_call=_fake_tts, photo_motion="dynamic", text_motion="slide", transition="auto")))
    assert not renderer.last_warnings, renderer.last_warnings
    a, b = _grab(mp4, 1.2, tmp_path / "a.png"), _grab(mp4, 1.9, tmp_path / "b.png")
    assert a.size == (1080, 1920)
    assert _changed(a, b, (0, 300, 1080, 1600)) > 100      # 화면 전체가 천천히 움직인다
    assert abs(_duration(mp4) - _duration(str(tmp_path / "out" / "combined_narration.mp3"))) < 0.5
    # 움직임 없이도 만들어진다
    r2 = ShortsRendererService(export_dir=str(tmp_path / "out2"))
    mp4b = asyncio.run(r2.render_shorts_video(sb, options=ShortsOptions(frame_style="tri", tts_call=_fake_tts)))
    assert os.path.exists(mp4b) and not r2.last_warnings


def test_tts_sends_no_style_instruction_and_overlong_audio_is_retried_not_cached(tmp_path):
    """영어 지시문이 읽혀 음성이 길어지는 문제: 지시문은 한국어, 이상하게 긴 음성은 한 번 다시 합성하고 캐시하지 않는다."""
    assert tts.style_instruction() == ""            # 지시문을 보내면 모델이 그것까지 읽는다
    assert tts.is_overlong("가" * 60, 24.0) and tts.is_overlong("가" * 60, 17.0)
    assert not tts.is_overlong("가" * 57, 10.2) and not tts.is_overlong("가" * 63, 13.0) and not tts.is_overlong("가" * 84, 14.8)
    repo.set_slot("tts", repo.upsert_model("google", "tts-model-y", "T", ["tts"], per_second=0.01))
    text = "가" * 60
    calls = []

    async def flaky(model_id, t, voice):
        calls.append(1)
        if len(calls) <= 2:                        # 처음 두 번은 지시문까지 읽은 것처럼 24초
            return _wav(24.0), {"in": 3, "out": 9}
        return _wav(len(t) / 6.0), {"in": 3, "out": 4}

    engine = tts.GeminiTTS("auto", str(tmp_path / "c"), call=flaky)
    out = str(tmp_path / "o.wav")
    asyncio.run(engine.synthesize_all([text], [out]))
    assert len(calls) == 2 and engine.warnings and not os.listdir(str(tmp_path / "c"))   # 재시도 1번, 경고, 캐시 안 함
    asyncio.run(engine.synthesize_all([text], [out]))                                  # 다시 만들면 새로 합성 → 정상 → 캐시
    assert len(calls) == 3 and len(os.listdir(str(tmp_path / "c"))) == 1
    assert len([u for u in repo.recent_usage(20) if u["kind"] == "tts"]) >= 3           # 재시도 비용도 기록


def _wav(sec):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\0\0" * int(24000 * sec))
    return buf.getvalue()
