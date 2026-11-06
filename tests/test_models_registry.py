"""모델 등록·슬롯·라우터 연결·이미지/영상 단가 (LLM 호출 없음)."""
import pytest

from ai_workers import multi_llm_router as router
from core import crypto_utils as c
from core import model_seed, repo


def test_seed_only_when_empty_and_has_no_prices():
    assert model_seed.seed_models_if_empty() is True
    models = repo.list_models()
    assert len(models) == len(model_seed.SEED_MODELS)
    assert all(m["per_image"] is None and m["per_second"] is None for m in models)
    assert model_seed.seed_models_if_empty() is False  # 두 번째는 건드리지 않음
    assert {m["model_id"] for m in repo.list_models("image")} >= {"gemini-3.1-flash-image"}


def test_upsert_validates_and_updates_in_place():
    ref = repo.upsert_model("google", "m-1", "M1", ["text", "vision"])
    assert repo.upsert_model("google", "m-1", "M1 새 이름", ["text"], per_image=0.04) == ref  # 같은 (벤더, ID)는 갱신
    assert repo.get_model(ref)["display_name"] == "M1 새 이름" and repo.get_model(ref)["per_image"] == 0.04
    with pytest.raises(ValueError):
        repo.upsert_model("", "x")
    with pytest.raises(ValueError):
        repo.upsert_model("google", "x", capabilities=["nope"])
    with pytest.raises(ValueError):
        repo.upsert_model("google", "x", per_image=-1)
    other = repo.upsert_model("google", "m-2")
    with pytest.raises(ValueError):  # 다른 행으로 바꾸려다 이름이 겹침
        repo.upsert_model("google", "m-1", model_ref=other)


def test_renaming_model_id_keeps_slot_link():
    ref = repo.upsert_model("anthropic", "old-model-1", "Old", ["text"])
    repo.set_slot("text", ref)
    repo.upsert_model("anthropic", "new-model-2", "New", ["text"], model_ref=ref)  # 단종 → 새 버전
    assert repo.resolve_slot_model("text")["model_id"] == "new-model-2"


def test_slot_requires_capability_and_syncs_legacy_vendor():
    text = repo.upsert_model("google", "t", "T", ["text"])
    image = repo.upsert_model("google", "i", "I", ["image"])
    with pytest.raises(ValueError):
        repo.set_slot("text", image)
    with pytest.raises(ValueError):
        repo.set_slot("nope", text)
    repo.set_slot("text", text)
    assert repo.get_app_settings()["default_generation_vendor"] == "google"


def test_slot_follow_disabled_and_explicit_fallback():
    a = repo.upsert_model("google", "a", "A", ["text"])
    b = repo.upsert_model("openai", "b", "B", ["text"])
    assert repo.resolve_slot_model("text_blog") is None
    repo.set_slot("text", a)
    assert repo.resolve_slot_model("text_blog")["model_id"] == "a"  # 비우면 기본을 따른다
    repo.set_slot("text_blog", b)
    assert repo.resolve_slot_model("text_blog")["model_id"] == "b"
    repo.upsert_model("openai", "b", "B", ["text"], enabled=False)
    assert repo.resolve_slot_model("text_blog")["model_id"] == "a"  # 꺼진 모델 → 슬롯을 따라감(자동 대체 아님: 슬롯이 비어 보이는 것)
    repo.set_slot("text_blog", b, fallback_ref=a)
    assert repo.resolve_slot_model("text_blog")["model_id"] == "a"  # 지정한 대체 모델만 쓴다


def test_delete_clears_slots_but_keeps_usage():
    ref = repo.upsert_model("google", "gone", "Gone", ["text"])
    repo.set_slot("text", ref)
    repo.log_usage("text", vendor="google", model="gone", est_input_tokens=10)
    repo.delete_model(ref)
    assert repo.get_slots()["text"]["model_ref"] is None
    assert repo.recent_usage(1)[0]["model"] == "gone"


def test_media_cost_unpriced_is_none_then_priced():
    repo.upsert_model("google", "img", "Img", ["image"])
    repo.log_usage("image", vendor="google", model="img", image_count=2)
    assert repo.recent_usage(1)[0]["cost_usd"] is None  # 단가 미등록 ≠ 0원
    repo.upsert_model("google", "img", "Img", ["image"], per_image=0.04)
    repo.log_usage("image", vendor="google", model="img", image_count=3)
    assert repo.recent_usage(1)[0]["cost_usd"] == pytest.approx(0.12)
    repo.upsert_model("google", "vid", "Vid", ["video"], per_second=0.1)
    repo.log_usage("video", vendor="google", model="vid", seconds=5)
    row = repo.recent_usage(1)[0]
    assert row["cost_usd"] == pytest.approx(0.5) and row["media_seconds"] == 5
    repo.upsert_model("google", "img", "Img", ["image"], per_image=9.0)  # 단가 인상
    assert repo.recent_usage(3)[1]["cost_usd"] == pytest.approx(0.12)  # 과거 금액은 그대로


def test_vision_calls_do_not_use_image_price():
    repo.upsert_model("google", "v", "V", ["vision"], per_image=5.0)
    repo.log_usage("vision", vendor="google", model="v", image_count=4, est_input_tokens=100)
    assert repo.recent_usage(1)[0]["cost_usd"] is None  # 사진 분석은 토큰 단가로만 계산


def _key(vendor, model_name="legacy-model"):
    repo.upsert_llm_setting(vendor, model_name, c.encrypt_api_key("k-" + vendor))


def test_router_uses_slot_model_not_legacy_name():
    _key("google")
    ref = repo.upsert_model("google", "gemini-new", "G", ["text", "vision"])
    repo.set_slot("text", ref)
    assert router.get_configured_vendor() == "google"
    model, key = router.load_vendor_config("google")
    assert model == "gemini-new" and key == "k-google"
    repo.upsert_model("google", "gemini-newer", "G", ["text", "vision"], model_ref=ref)  # 모델 교체
    assert router.load_vendor_config("google")[0] == "gemini-newer"


def test_router_blog_slot_and_vision_slot():
    _key("google")
    _key("anthropic")
    g = repo.upsert_model("google", "g-text", "G", ["text", "vision"])
    a = repo.upsert_model("anthropic", "claude-x", "A", ["text"])
    gv = repo.upsert_model("google", "g-vision", "GV", ["vision"])
    repo.set_slot("text", g)
    repo.set_slot("text_blog", a)
    repo.set_slot("vision", gv)
    assert router.get_configured_vendor() == "google"
    with router.text_slot("text_blog"):
        assert router.get_configured_vendor() == "anthropic"
        assert router.load_vendor_config("anthropic")[0] == "claude-x"
    assert router.get_configured_vendor() == "google"  # 슬롯 범위를 벗어나면 원래대로
    assert router.get_vision_vendor() == "google"
    assert router.load_vendor_config("google", "vision")[0] == "g-vision"


def test_router_falls_back_to_legacy_when_registry_empty():
    _key("google", "old-name")
    repo.save_app_settings(default_generation_vendor="google")
    assert router.get_configured_vendor() == "google"
    assert router.load_vendor_config("google")[0] == "old-name"


def test_router_requires_active_key_for_slot_vendor():
    ref = repo.upsert_model("openai", "gpt-x", "X", ["text"])
    repo.set_slot("text", ref)
    with pytest.raises(RuntimeError):  # 키가 없음
        router.get_configured_vendor()


def test_models_part_round_trips_between_pcs():
    from tests.test_transfer import _new_pc
    from core import transfer

    g = repo.upsert_model("google", "g-text", "G", ["text", "vision"])
    a = repo.upsert_model("anthropic", "claude-x", "A", ["text"], note="메모")
    img = repo.upsert_model("google", "img", "Img", ["image"], per_image=0.05)
    repo.set_slot("text", g)
    repo.set_slot("text_blog", a, fallback_ref=g)
    repo.set_slot("image", img)
    raw = transfer.export_bundle(["models"])
    assert b"g-text" in raw and b"claude-x" in raw

    _new_pc()
    repo.upsert_model("openai", "only-here", "Here", ["text"])  # 받는 PC에만 있는 모델은 그대로
    result = transfer.import_bundle(raw, ["models"])
    assert "3개" in result["models"]
    ids = {(m["vendor"], m["model_id"]): m for m in repo.list_models()}
    assert set(ids) == {("google", "g-text"), ("anthropic", "claude-x"), ("google", "img"), ("openai", "only-here")}
    assert ids[("google", "img")]["per_image"] == 0.05 and ids[("anthropic", "claude-x")]["note"] == "메모"
    assert repo.resolve_slot_model("text")["model_id"] == "g-text"
    slots = repo.get_slots()
    assert repo.get_model(slots["text_blog"]["model_ref"])["model_id"] == "claude-x"
    assert repo.get_model(slots["text_blog"]["fallback_ref"])["model_id"] == "g-text"
    assert repo.get_app_settings()["default_generation_vendor"] == "google"  # 예전 설정도 같이 맞춰짐
    transfer.import_bundle(raw, ["models"])  # 두 번 가져와도 같은 결과
    assert len(repo.list_models()) == 4
