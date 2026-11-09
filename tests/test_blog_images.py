"""블로그 사진 자리 → AI 이미지 채우기 (실제 이미지 호출 없이 가짜 생성기로)."""
import io

from PIL import Image

from ai_workers import blog_images, formatting
from core import repo


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 160, 130)).save(buf, "PNG")
    return buf.getvalue()


def _campaign():
    cid = repo.insert_campaign("manual", memo="m")["id"]
    content = "첫 문단입니다.\n\n둘째 문단입니다.\n\n셋째 문단입니다."
    fmt = {"items": [
        {"id": 1, "type": "photo_hint", "after": "첫 문단입니다.", "caption": "따뜻한 햇살이 드는 창가"},
        {"id": 2, "type": "photo_hint", "after": "둘째 문단입니다.", "caption": "찻잔과 노트"},
    ]}
    repo.update_campaign(cid, content=content, content_format=fmt)
    return cid


def test_open_hints_in_document_order():
    cid = _campaign()
    c = repo.get_campaign(cid)
    caps = [h["caption"] for h in formatting.open_photo_hints(c["content"], c["content_format"])]
    assert caps == ["따뜻한 햇살이 드는 창가", "찻잔과 노트"]


def test_generate_places_images_and_logs(monkeypatch):
    cid = _campaign()
    prompts = []
    monkeypatch.setattr(blog_images, "plan", lambda c: {"slots": 2, "count": 2, "model": {"vendor": "google", "model_id": "m", "display_name": "m"},
                                                          "per_image": None, "total_usd": None})

    def fake(model_id, prompt, aspect):
        prompts.append(prompt)
        return _png(), ".png", {"in": 1, "out": 2}

    res = blog_images.generate(cid, generate_fn=fake)
    assert res["made"] == 2 and res["placed"] == 2
    c = repo.get_campaign(cid)
    assert c["content"].count("[IMAGE:") == 2
    assert not [i for i in c["content_format"]["items"] if i["type"] == "photo_hint"]
    assert len(c["storage_file_paths"]) == 2
    caps = [i for i in c["content_format"]["items"] if i["type"] == "photo_caption"]
    assert [i["path"] for i in caps] == c["storage_file_paths"]
    assert caps[0]["caption"] == "따뜻한 햇살이 드는 창가 (AI로 만든 이미지)"
    assert "NO TEXT" in prompts[0] and "햇살" in prompts[0]


def test_failure_stops_and_keeps_remaining_slots(monkeypatch):
    cid = _campaign()
    monkeypatch.setattr(blog_images, "plan", lambda c: {"slots": 2, "count": 2, "model": {"vendor": "google", "model_id": "m", "display_name": "m"},
                                                          "per_image": None, "total_usd": None})
    calls = []

    def fake(model_id, prompt, aspect):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return _png(), ".png", {}

    res = blog_images.generate(cid, generate_fn=fake)
    c = repo.get_campaign(cid)
    assert res["made"] == 1 and len(res["failed"]) == 1
    assert c["content"].count("[IMAGE:") == 1
    assert len([i for i in c["content_format"]["items"] if i["type"] == "photo_hint"]) == 1


def test_no_model_means_disabled_message():
    est = {"slots": 2, "count": 2, "model": None, "per_image": None, "total_usd": None}
    assert "이미지 생성" in blog_images.describe(est)
