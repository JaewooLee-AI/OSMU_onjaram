"""네이버 키워드 측정은 선택 기능: 꺼짐이 기본이고, 꺼져 있으면 어떤 경로로도 호출이 나가지 않으며, 부분 데이터로도 점수가 난다."""
import pytest

from ai_workers import keyword_research as kr
from ai_workers import seo_optimizer
from core import crypto_utils as c
from core import repo, setup_check


@pytest.fixture
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("네트워크 호출이 나갔다")
    monkeypatch.setattr(kr.requests, "get", boom)
    monkeypatch.setattr(kr.requests, "post", boom, raising=False)
    monkeypatch.setattr(kr.requests, "request", boom, raising=False)


def _hub():
    repo.save_naver_api_settings(c.encrypt_api_key("id"), c.encrypt_api_key("secret"), 100)


def _ad():
    repo.save_searchad_settings(c.encrypt_api_key("cust"), c.encrypt_api_key("ak"), c.encrypt_api_key("sk"))


def test_default_is_off_and_level_zero():
    assert kr.enabled() is False and kr.level() == 0
    _hub()
    _ad()
    assert kr.level() == 0                       # 키가 있어도 켜지 않으면 레벨 0(호출 안 함)


def test_levels_follow_switch_and_keys():
    repo.save_app_settings(naver_keywords_enabled=True)
    assert kr.level() == 0                       # 켰지만 키 없음
    _hub()
    assert kr.level() == 1
    _ad()
    assert kr.level() == 2
    assert "레벨 2" in kr.LEVEL_LABELS[kr.level()]


def test_nothing_reaches_the_network_while_off(no_network):
    _hub()
    _ad()
    with pytest.raises(kr.NaverDisabled):
        kr._request(kr.BLOG_PATH, params={"query": "x"})
    with pytest.raises(kr.NaverDisabled):
        kr._searchad_request(kr.KEYWORDSTOOL_PATH, {"hintKeywords": "x"})
    with pytest.raises(kr.NaverApiError):        # 상위 함수도 같은 이유로 멈춘다
        kr.blog_document_count("심리상담", use_cache=False)


def test_connection_test_works_before_enabling(monkeypatch):
    seen = []

    class Resp:
        ok = True
        status_code = 200
        def json(self):
            return {"total": 1, "items": []}
        text = "{}"

    monkeypatch.setattr(kr.requests, "get", lambda *a, **k: seen.append(a) or Resp())
    assert kr.enabled() is False
    ok, _ = kr.test_connection("id", "secret")     # 켜기 전에 키가 맞는지 확인할 수 있어야 한다
    assert ok and seen


def _put(keyword, **metrics):
    for metric, value in metrics.items():
        repo.put_cached_metric(keyword if metric != "ad_volume" else kr.normalize(keyword), metric, str(value))


def test_opportunity_uses_best_available_signal_and_never_invents_competition():
    assert seo_optimizer._opportunity("측정안함") == 0.0
    _put("문서수만", blog_total=5000)
    _put("문서수만적음", blog_total=500)
    low, high = seo_optimizer._opportunity("문서수만"), seo_optimizer._opportunity("문서수만적음")
    assert 0 < low < high                                    # 레벨 1(문서 수만): 경쟁이 적을수록 높다
    _put("추이", blog_total=5000, trend_ratio=80)
    assert seo_optimizer._opportunity("추이") == pytest.approx(kr.golden_score(80, 5000))
    _put("검색량", blog_total=5000, trend_ratio=80, ad_volume=12000)
    assert seo_optimizer._opportunity("검색량") == pytest.approx(kr.golden_score(12000, 5000))   # 검색량이 있으면 그것을 쓴다
    _put("문서수없음", trend_ratio=90, ad_volume=9000)
    assert seo_optimizer._opportunity("문서수없음") == 0.0      # 경쟁도를 모르면 0(경쟁 없음으로 읽지 않는다)


def test_keyword_selection_works_with_no_measurements():
    picked = seo_optimizer.select_target_keywords("제목", "창원 심리상담 이야기. 마음 돌봄.", ["창원 심리상담", "마음 돌봄"])
    assert isinstance(picked, list)                            # 측정값이 없어도 글 생성 경로가 막히지 않는다


def test_setup_check_reports_missing_required_then_ready():
    missing = {i["key"] for i in setup_check.required_missing()}
    assert {"llm_key", "text_model"} <= missing
    ref = repo.upsert_model("google", "m", "M", ["text"])
    repo.set_slot("text", ref)
    assert {"llm_key", "text_key"} <= {i["key"] for i in setup_check.required_missing()}   # 모델은 골랐지만 키가 없음
    repo.upsert_llm_setting("google", "m", c.encrypt_api_key("k"))
    repo.save_company_profile(phone="055-255-1365")
    assert setup_check.required_missing() == []
    optional = {i["key"]: i for i in setup_check.items() if not i["required"]}
    assert optional["naver"]["ok"] is False and "선택" in optional["naver"]["label"]   # 선택 항목은 필수 점검에 안 걸린다


def test_switch_round_trips_through_data_transfer():
    from tests.test_transfer import _new_pc
    from core import transfer
    repo.save_app_settings(naver_keywords_enabled=True)
    raw = transfer.export_bundle(["company"])
    _new_pc()
    assert repo.get_app_settings().get("naver_keywords_enabled") in (0, False, None)
    transfer.import_bundle(raw, ["company"])
    assert repo.get_app_settings()["naver_keywords_enabled"] is True
