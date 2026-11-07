"""글 유형(현장 후기·칼럼·모집·안내): 구조 지시, 제목 힌트, 문의 푸터, 낡은 태그 걸러내기."""
from ai_workers import post_types, prompt_builder
from core import repo

KIT = {"brand_name": "주식회사 온자람", "phone": "055-255-1365", "address": "경남 창원시 성산구 반송로82번길 29, 1층"}


def test_prompt_has_structure_only_when_type_chosen():
    plain = prompt_builder.build_blog_system_prompt(KIT)
    typed = prompt_builder.build_blog_system_prompt(KIT, post_type="review")
    assert "현장 후기" not in plain and "글쓰기 안전 규칙" not in plain
    assert "현장 후기" in typed and "마음성장파트너 주식회사 온자람입니다" in typed
    assert "효과를 단정하는 말" in typed
    assert "번호" in prompt_builder.build_blog_system_prompt(KIT, post_type="column")
    assert prompt_builder.build_blog_system_prompt(KIT, post_type="nope") == plain


def test_footer_uses_kit_values_only_once():
    body = "본문입니다."
    out = post_types.apply_footer(body, KIT, "review")
    assert "055-255-1365" in out and "반송로82번길 29" in out and out.startswith(body)
    assert post_types.apply_footer(out, KIT, "review") == out          # 두 번 붙지 않음
    assert post_types.apply_footer(body, KIT, "") == body              # 유형이 없으면 그대로
    assert post_types.apply_footer(body, {"brand_name": "x"}, "review") == body   # 킷에 값이 없으면 지어내지 않음
    assert "위치" not in post_types.apply_footer(body, {"phone": "02-000"}, "notice")


def test_post_type_is_saved_on_campaign():
    cid = repo.insert_campaign("manual", memo="메모")["id"]
    repo.update_campaign(cid, post_type="column")
    assert repo.get_campaign(cid)["post_type"] == "column"


def test_stale_hashtag_filtered(monkeypatch):
    from ai_workers import naver_hashtag_writer as w
    monkeypatch.setattr(w, "generate_text", lambda **k: '{"hashtags": ["#온자람", "#예비사회적기업", "#창원심리상담"]}')
    assert w.write_naver_hashtags("t", "c", [], "x") == ["#온자람", "#창원심리상담"]


def test_seed_has_blog_id():
    from core import brand_seed
    assert brand_seed.NAVER_BLOG_ID == "onjaram"
