"""카드 이미지: 내 사진 우선·AI 보충·예상 비용 (실제 이미지 모델은 부르지 않음)."""
import pytest

from cards import images
from cards.director import plan_cards
from cards.schema import MediaAsset
from core import repo
from core.brand_seed import seed_if_empty

TEXT = "마음이 지칠 땐 쉬어가도 괜찮아요.\n왜 그럴까요? 몸이 보내는 신호예요.\n1. 눕기\n2. 쉬기\n3. 차 마시기\n혼자 어렵다면 상담이 있어요."


@pytest.fixture(autouse=True)
def seeded():
    seed_if_empty()


def _user_photo(i=1):
    return MediaAsset(id=f"A{i}", kind="image", path=f"/tmp/none{i}.jpg")


def _plan(mode="own_first", assets=None, type_id="empathy"):
    sb, _ = plan_cards(TEXT, type_id, use_llm=False, image_mode=mode, assets=assets or [])
    return sb


def _image_model(per_image=0.04):
    ref = repo.upsert_model("google", "img-model", "Img", ["image"], per_image=per_image)
    repo.set_slot("image", ref)
    return ref


def test_photo_slots_are_cover_and_body_only():
    sb = _plan()
    types = [sb.card_slides[i].slide_type for i in images.photo_slot_indexes(sb)]
    assert types and set(types) <= {"cover", "body"}          # 번호·안내 카드는 인포그래픽 → AI 이미지 안 씀


def test_own_only_never_uses_ai_and_costs_nothing():
    sb = _plan("own_only")
    est = images.estimate(sb)
    assert est["count"] == 0 and "비용이 들지 않습니다" in images.describe_estimate(est)
    called = []
    out = images.generate_missing(sb, "/tmp/unused", generate=lambda *a: called.append(a))
    assert out["made"] == 0 and not called


def test_own_first_fills_user_photos_then_ai_for_the_rest():
    sb = _plan("own_first", [_user_photo(1), _user_photo(2)])
    slots = images.photo_slot_indexes(sb)
    assert [sb.card_slides[i].asset_id for i in slots[:2]] == ["A1", "A2"]      # 올린 사진이 먼저
    assert images.ai_targets(sb) == slots[2:]                                      # 부족분만 AI


def test_ai_first_replaces_unlocked_but_respects_locked_cards():
    sb = _plan("ai_first", [_user_photo(1)])
    slots = images.photo_slot_indexes(sb)
    assert images.ai_targets(sb) == slots                          # ai_first는 자동 배치 없이 전부 AI
    sb.card_slides[slots[0]].asset_id = "A1"
    sb.card_slides[slots[0]].asset_locked = True                  # 사용자가 직접 고른 카드는 건드리지 않는다
    assert images.ai_targets(sb) == slots[1:]
    sb.card_slides[slots[1]].asset_locked = True                  # '사진 없음'을 고른 카드도 제외
    assert images.ai_targets(sb) == slots[2:]


def test_ai_first_does_not_pay_twice_for_a_slot_that_already_has_an_ai_image(tmp_path):
    _image_model()
    sb = _plan("ai_first")
    first = images.generate_missing(sb, str(tmp_path), generate=lambda *a: (b"x", ".png", {}))
    assert first["made"] > 0
    assert images.ai_targets(sb) == [] and images.estimate(sb)["count"] == 0      # 같은 칸을 다시 만들지 않는다
    again = images.generate_missing(sb, str(tmp_path), generate=lambda *a: pytest.fail("두 번째 호출이 일어났다"))
    assert again["made"] == 0


def test_disabled_image_model_is_explained():
    ref = _image_model()
    repo.upsert_model("google", "img-model", "Img", ["image"], enabled=False, per_image=0.04, model_ref=ref)
    est = images.estimate(_plan())
    assert est["model"] is None and "꺼져 있습니다" in images.describe_estimate(est)


def test_estimate_uses_registered_image_price():
    sb = _plan("own_first")
    est = images.estimate(sb)
    assert est["model"] is None and "없거나 꺼져 있습니다" in images.describe_estimate(est)
    _image_model(per_image=None)
    est = images.estimate(sb)
    assert est["total_usd"] is None and "단가 미등록" in images.describe_estimate(est)   # 0원으로 보이지 않는다
    _image_model(per_image=0.04)
    est = images.estimate(sb)
    assert est["total_usd"] == pytest.approx(0.04 * est["count"]) and "예상" in images.describe_estimate(est)


def test_slot_aspect_follows_template_zone():
    assert images.slot_aspect(_plan()) == "3:2"                    # tri 2:5:3 가운데 영역 1080x675
    sb = _plan()
    sb.design_id = "tri-1-1-1"
    assert images.slot_aspect(sb) == "16:9"


def test_prompt_forbids_people_and_text():
    sb = _plan()
    prompt = images.build_prompt(sb, images.photo_slot_indexes(sb)[0])
    assert "identifiable real person" in prompt and "NO TEXT" in prompt


def test_generate_missing_assigns_logs_cost_and_survives_one_failure(tmp_path):
    _image_model(0.04)
    sb = _plan("own_first")
    targets = images.ai_targets(sb)
    calls = []

    def fake(model_id, prompt, aspect):
        calls.append((model_id, aspect))
        if len(calls) == 2:
            raise RuntimeError("일시 오류")
        return b"\x89PNG-fake", ".png", {"in": 10, "out": 20}

    out = images.generate_missing(sb, str(tmp_path), generate=fake)
    assert out["made"] == len(targets) - 1 and len(out["failed"]) == 1
    assert all(c[0] == "img-model" for c in calls)                  # 슬롯에 지정한 모델 이름만 쓴다
    made = [s for s in sb.card_slides if s.asset_id and s.asset_id.startswith("G")]
    assert len(made) == out["made"] and all((tmp_path / "ai" / f"{s.asset_id}.png").exists() for s in made)
    usage = [u for u in repo.recent_usage(10) if u["kind"] == "image"]
    assert len(usage) == out["made"] and all(u["cost_usd"] == pytest.approx(0.04) for u in usage)
    assert all(a.source == "ai" for a in sb.assets)


def test_generate_stops_on_auth_error_and_requires_model(tmp_path):
    sb = _plan("own_first")
    with pytest.raises(RuntimeError, match="이미지 생성"):
        images.generate_missing(sb, str(tmp_path), generate=lambda *a: (b"", ".png", {}))
    _image_model()
    n = []

    def bad_key(*a):
        n.append(1)
        raise RuntimeError("API key not valid")

    out = images.generate_missing(sb, str(tmp_path), generate=bad_key)
    assert out["made"] == 0 and len(n) == 1                         # 키 오류면 첫 실패에서 멈춘다(불필요한 호출 방지)


def test_non_google_image_model_is_refused_without_silent_switch(tmp_path):
    ref = repo.upsert_model("openai", "some-image", "X", ["image"])
    repo.set_slot("image", ref)
    with pytest.raises(RuntimeError, match="Google"):
        images.generate_missing(_plan("own_first"), str(tmp_path))


def test_regenerate_one_card_replaces_existing_ai_image_and_locks_it(tmp_path):
    _image_model()
    sb = _plan("own_first")
    calls = []

    def fake(model_id, prompt, aspect):
        calls.append(prompt)
        return b"\x89PNG", ".png", {"in": 10, "out": 20}

    images.generate_missing(sb, str(tmp_path), generate=fake)
    first = sb.card_slides[0].asset_id
    assert first and first.startswith("G")
    # 이미 AI 이미지가 있어도 '다시 만들기'(only)는 그 칸만 새로 만들고 잠근다
    n = len(calls)
    result = images.generate_missing(sb, str(tmp_path), generate=fake, only=[0])
    assert result["made"] == 1 and len(calls) == n + 1
    assert sb.card_slides[0].asset_id != first and sb.card_slides[0].asset_locked
    # 안내 문구: 만들 칸이 없고 AI 이미지가 이미 있으면 그렇게 말한다
    est = images.estimate(sb)
    assert est["count"] == 0 and est["existing_ai"] >= 1 and "이미 카드에 들어 있습니다" in images.describe_estimate(est)


def test_image_cost_counts_image_per_piece_plus_only_text_and_thinking_tokens():
    """공식: 이미지 출력은 장당($0.0336/1K), 글자·추론 출력은 100만 토큰당($7.50). 이미지 토큰(1,120)은 장당 단가에 들어 있다."""
    repo.upsert_model("google", "nb", "NB", ["image"], per_image=0.0336)
    repo.save_model_price("google", "nb", 1.5, 7.5)
    repo.log_usage("image", vendor="google", model="nb", image_count=1, est_input_tokens=100, est_output_tokens=2287)
    row = next(r for r in repo.cost_by_model() if r["model"] == "nb")
    expected = 100 * 1.5 / 1e6 + 0.0336 + (2287 - repo.IMAGE_1K_OUTPUT_TOKENS) * 7.5 / 1e6
    assert row["cost_usd"] == pytest.approx(expected)


def test_gemini_image_request_asks_for_1k_and_retries_without_size_if_unsupported(monkeypatch):
    import sys
    import types as pytypes

    seen = []

    class Resp:
        usage_metadata = pytypes.SimpleNamespace(prompt_token_count=5, candidates_token_count=1120, thoughts_token_count=10)
        parts = [pytypes.SimpleNamespace(inline_data=pytypes.SimpleNamespace(data=b"x", mime_type="image/png"))]

    class Models:
        def generate_content(self, model, contents, config):
            size = getattr(config.image_config, "image_size", None)
            seen.append(size)
            if size and len(seen) == 1 and monkeypatch_state["reject"]:
                raise RuntimeError("400 INVALID_ARGUMENT: image_size is not supported")
            return Resp()

    class Client:
        def __init__(self, api_key):
            self.models = Models()

    monkeypatch_state = {"reject": False}
    import google.genai as genai
    monkeypatch.setattr(genai, "Client", Client)
    monkeypatch.setattr(images, "_gemini_key", lambda: "k")
    data, ext, usage = images._generate_gemini("m", "p", "4:5")
    assert seen == ["1K"] and usage["out"] == 1130
    seen.clear()
    monkeypatch_state["reject"] = True
    images._generate_gemini("m", "p", "4:5")
    assert seen == ["1K", None]       # 거부하면 해상도 옵션만 빼고 한 번 더(모델은 그대로)
