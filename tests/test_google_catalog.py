"""Google 가격표 읽기·추천·적용 (네트워크 없이, 공식 페이지 형식을 줄인 예시로)."""
import datetime as dt

from core import google_catalog as g
from core import repo

SAMPLE = """
# Gemini Developer API pricing

## Gemini 9.1 Flash  {% id="gemini-9.1-flash" %}

{% two-column-layout %}
  {% left-column class="center-vertically" %}
  *[`gemini-9.1-flash`](/docs/models/gemini-9.1-flash)*
  {% /left-column %}
{% /two-column-layout %}

{% hr /%}

{% tabs %}
  {% tab title="Standard" %}
  {% table %}
  * Feature
  * Free Tier
  * Paid Tier, per 1M tokens in USD

  ---

  * Input price
  * Free of charge
  * $0.75 through December 31, 2026.
  $1.50 starting January 1, 2027.

  ---

  * Output price (including thinking tokens)
  * Free of charge
  * $3.75 through December 31, 2026.
  $7.50 starting January 1, 2027.

  ---

  * Context caching price
  * Free of charge
  * $0.075 through December 31, 2026.
  $0.15 starting January 1, 2027.
  $0.50 / 1,000,000 tokens per hour (storage price) through December 31, 2026.
  {% /table %}
  {% /tab %}

  {% tab title="Batch" %}
  {% table %}
  * Feature
  * Free Tier
  * Paid Tier, per 1M tokens in USD

  ---

  * Input price
  * Not available
  * $0.375
  {% /table %}
  {% /tab %}
{% /tabs %}

## Gemini 8.0 Flash Preview  {% id="gemini-8.0-flash-preview" %}

  *[`gemini-8.0-flash-preview`](/docs/models/gemini-8.0-flash-preview)*

{% hr /%}

{% table %}
  * Feature
  * Free Tier
  * Paid Tier, per 1M tokens in USD

  ---

  * Input price
  * Free of charge
  * $1.25, prompts <= 200k tokens
  $2.50, prompts > 200k tokens

  ---

  * Output price (including thinking tokens)
  * Free of charge
  * $10.00, prompts <= 200k tokens
  $15.00, prompts > 200k
{% /table %}

## Gemini 9.1 Flash Image (Nano)  {% id="gemini-9.1-flash-image" %}

  *[`gemini-9.1-flash-image`](/docs/models/gemini-9.1-flash-image)*

{% hr /%}

{% tabs %}
  {% tab title="Standard" %}
  {% table %}
  * Feature
  * Free Tier
  * Paid Tier, per 1M tokens in USD

  ---

  * Input price
  * Not available
  * $0.50 (text/image)

  ---

  * Output price
  * Not available
  * $3 (text and thinking)
  $60.00 (images)
  Equivalent to $0.045 per 0.5K image{% sup /%}
  $0.067 per 1K image{% sup /%},
  $0.101 per 2K image{% sup /%}
  {% /table %}
  {% /tab %}
{% /tabs %}

## Gemini 7 Flash Image  {% id="gemini-7-flash-image" %}

  *[`gemini-7-flash-image`](/docs/models/gemini-7-flash-image)*

{% hr /%}

{% callout type="warning" %}
   **Warning:** Gemini 7 Flash Image
  (`gemini-7-flash-image`) is [deprecated](/docs/deprecations) and will be shut
  down on March 15, 2027.
{% /callout %}

{% table %}
  * Feature
  * Free Tier
  * Paid Tier, per 1M tokens in USD

  ---

  * Input price
  * Not available
  * $0.30 (text / image)

  ---

  * Output price
  * Not available
  * $0.039 per image
{% /table %}

## Gemini 9.1 Flash TTS  {% id="gemini-9.1-flash-tts" %}

  *[`gemini-9.1-flash-tts`](/docs/models/gemini-9.1-flash-tts)*

{% hr /%}

{% table %}
  * Feature
  * Free Tier
  * Paid Tier, per 1M tokens in USD

  ---

  * Input price
  * Free of charge
  * $0.50 (text)

  ---

  * Output price
  * Free of charge
  * $9.00 (audio)
  Equivalent to $0.00225 per 10s audio
{% /table %}
"""

TODAY = dt.date(2026, 11, 9)


def test_parse_current_and_scheduled_prices():
    p = g.parse_pricing(SAMPLE, TODAY)
    f = p["gemini-9.1-flash"]
    assert (f["input"], f["output"], f["cache"]) == (0.75, 3.75, 0.075)
    assert f["schedule"] == [{"from": "2027-01-01", "input": 1.5, "output": 7.5, "cache": 0.15}]
    # 2027년이 되면 새 단가가 현재 단가
    assert g.parse_pricing(SAMPLE, dt.date(2027, 2, 1))["gemini-9.1-flash"]["input"] == 1.5


def test_parse_tiers_image_and_tts():
    p = g.parse_pricing(SAMPLE, TODAY)
    assert (p["gemini-8.0-flash-preview"]["input"], p["gemini-8.0-flash-preview"]["output"]) == (1.25, 10.0)
    img = p["gemini-9.1-flash-image"]
    assert (img["input"], img["output"], img["per_image"]) == (0.5, 3.0, 0.067)
    assert p["gemini-7-flash-image"]["per_image"] == 0.039
    assert p["gemini-7-flash-image"]["shutdown"] == "2027-03-15"
    assert (p["gemini-9.1-flash-tts"]["input"], p["gemini-9.1-flash-tts"]["output"]) == (0.5, 9.0)


def test_recommend_prefers_stable_and_skips_shutdown():
    p = g.parse_pricing(SAMPLE, TODAY)
    rec = g.recommend(p, None)
    assert rec == {"text": "gemini-9.1-flash", "image": "gemini-9.1-flash-image", "tts": "gemini-9.1-flash-tts"}
    assert "gemini-7-flash-image" not in g.candidates("image", p, None)
    # 키로 쓸 수 없는 모델은 고르지 않는다
    assert g.recommend(p, ["gemini-8.0-flash-preview"])["text"] == "gemini-8.0-flash-preview"


def test_apply_saves_models_prices_slots_and_due_change():
    p = g.parse_pricing(SAMPLE, TODAY)
    g.apply(g.recommend(p, None), p, TODAY)
    text = repo.resolve_slot_model("text")
    assert text["model_id"] == "gemini-9.1-flash"
    assert repo.get_model_price("google", "gemini-9.1-flash")["input_per_mtok"] == 0.75
    img = repo.resolve_slot_model("image")
    assert img["per_image"] == 0.067
    assert repo.resolve_slot_model("tts")["model_id"] == "gemini-9.1-flash-tts"
    assert g.apply_due_prices(TODAY) == []
    assert g.apply_due_prices(dt.date(2027, 1, 1)) == ["Gemini 9.1 Flash"]
    price = repo.get_model_price("google", "gemini-9.1-flash")
    assert (price["input_per_mtok"], price["output_per_mtok"], price["cached_input_per_mtok"]) == (1.5, 7.5, 0.15)
    assert repo.find_model("google", "gemini-9.1-flash")["options"]["price_schedule"] == []


def test_unreadable_page_gives_nothing():
    assert g.parse_pricing("<html>바뀐 형식</html>", TODAY) == {}
    assert "단가 미등록" in g.price_line(None)


def test_format_problems_detects_broken_prices():
    p = g.parse_pricing(SAMPLE, TODAY)
    assert g.format_problems(p) == []
    assert g.format_problems({}) != []
    broken = {k: dict(v, input=None, output=None, per_image=None) for k, v in p.items()}
    assert len(g.format_problems(broken)) == 3
    assert "관리자" in g.FORMAT_MESSAGE
