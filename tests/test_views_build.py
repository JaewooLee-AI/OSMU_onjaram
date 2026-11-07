"""각 화면이 예외 없이 만들어지는지(컨트롤 트리 생성) 확인합니다.

실제 창은 띄우지 않습니다. 화면의 build()는 페이지 객체를 이벤트 처리기에서만 쓰므로,
여기서는 아무 일도 하지 않는 가짜 페이지를 넘깁니다. 클릭 동작은 로컬에서 앱으로 확인합니다.
"""
from __future__ import annotations

from datetime import date, timedelta

import flet as ft
import pytest

from core import repo
from core.brand_seed import seed_if_empty
from flet_app.state import AppState


class _FakeServices:
    def register_service(self, service):
        pass


class FakePage:
    _services = _FakeServices()
    _naver_publish_poll_generation = 0

    def __getattr__(self, name):
        return lambda *a, **k: None


def _walk(control, seen=None):
    """컨트롤 트리를 끝까지 돌아 속성 접근 오류를 드러냅니다."""
    seen = seen if seen is not None else set()
    if control is None or id(control) in seen:
        return 0
    seen.add(id(control))
    n = 1
    for attr in ("content", "controls", "tabs", "rows", "cells", "spans", "title", "actions"):
        child = getattr(control, attr, None)
        if isinstance(child, list):
            for c in child:
                if isinstance(c, ft.BaseControl):
                    n += _walk(c, seen)
        elif isinstance(child, ft.BaseControl):
            n += _walk(child, seen)
    return n


@pytest.fixture(autouse=True)
def page_context():
    """복사 버튼(ft.CopyToClipboard)은 만들 때 현재 페이지를 찾으므로 가짜 페이지를 넣어 둡니다."""
    from flet.controls import context as flet_context
    token = flet_context._context_page.set(FakePage())
    yield
    flet_context._context_page.reset(token)


@pytest.fixture
def populated():
    seed_if_empty()
    a = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="가발 세척")
    b = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="가발 보관")
    repo.update_campaign(b["id"], status="draft", title="보관법", content="첫 문단입니다.\n둘째 문단입니다.",
                         guardrail_report={"compliance_pass": True, "score": 95,
                                           "cost": {"calls": 3, "cost_krw": 12.3, "cost_usd": 0.0088,
                                                    "unpriced_calls": 0, "input_tokens": 1, "output_tokens": 1}})
    c = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="게시됨")
    repo.mark_published(c["id"], "https://blog.naver.com/cjc/223000000009")
    repo.save_model_price("google", "gemini-3.8-flash", 0.3, 2.5)
    repo.log_usage("text", vendor="google", model="gemini-3.8-flash", est_input_tokens=1000, est_output_tokens=300)
    repo.log_usage("text", vendor="anthropic", model="claude-x", est_input_tokens=1000)
    repo.set_monthly_budget_krw(1)
    return {"a": a, "b": b, "c": c}


def test_dashboard_builds(populated):
    from flet_app.views import dashboard_view
    assert _walk(dashboard_view.build(FakePage(), AppState())) > 20


def test_settings_builds(populated):
    from flet_app.views import settings_view
    assert _walk(settings_view.build(FakePage(), AppState())) > 50


def test_naver_publish_builds(populated):
    from flet_app.views import naver_publish_view
    assert _walk(naver_publish_view.build(FakePage(), AppState())) > 10


@pytest.mark.parametrize("which", ["a", "b", "c"])
def test_workbench_builds_each_campaign(populated, which):
    from flet_app.views import workbench_view
    state = AppState(pending_workbench_campaign_id=populated[which]["id"])
    assert _walk(workbench_view.build(FakePage(), state)) > 20


def test_formatted_post_renders_in_workbench_simulator_and_publish(populated):
    from ai_workers import formatting
    from tests.test_v2_formatting import DRAFT
    from flet_app.views import naver_publish_view, workbench_view
    import flet_app.simulators as sim

    plain, items = formatting.extract(DRAFT)
    fmt = formatting.finalize(plain, items, "rich", "info")
    cid = populated["b"]["id"]
    repo.update_campaign(cid, content=plain, content_format=fmt, status="ready_to_publish")
    campaign = repo.get_campaign(cid)
    for mobile in (False, True):
        assert _walk(sim.render("naver", campaign, is_mobile=mobile, brand_kit=repo.get_campaign_brand_kit(campaign))) > 30
    assert _walk(workbench_view.build(FakePage(), AppState(pending_workbench_campaign_id=cid))) > 60
    assert _walk(naver_publish_view.build(FakePage(), AppState())) > 20


def test_brand_kit_view_builds_with_design_fields(populated):
    from flet_app.views import brand_kit_view
    assert _walk(brand_kit_view.build(FakePage(), AppState())) > 50


def test_transfer_tab_builds(populated):
    from flet_app.views import settings_view
    tab = settings_view._build_transfer_tab(FakePage(), 1.0)
    labels = [getattr(c, "label", "") or "" for c in tab.controls if isinstance(c, ft.Checkbox)]
    assert any("브랜드 킷" in label and "이 PC:" in label for label in labels)
    assert _walk(tab) > 15


def test_models_tab_saves_typed_model_and_prices(populated):
    """모델 등록 탭: 모델 이름을 직접 입력하고 단가까지 한 번에 저장하면 슬롯·단가가 함께 생긴다."""
    from flet_app.views import model_registry_view as mrv
    tab = mrv.build_models_tab(FakePage(), 1.0)
    assert _walk(tab) > 40

    def find(control, pred, out):
        if control is None:
            return out
        if pred(control):
            out.append(control)
        for attr in ("content", "controls", "actions"):
            child = getattr(control, attr, None)
            for c in (child if isinstance(child, list) else [child]):
                if isinstance(c, ft.BaseControl):
                    find(c, pred, out)
        return out

    def card(title):
        return find(tab, lambda c: isinstance(c, ft.Container) and isinstance(getattr(c, "content", None), ft.Column)
                    and any(getattr(x, "value", None) == title for x in c.content.controls), [])[0]

    text_card = card("기본 글쓰기 모델")
    fields = {f.label: f for f in find(text_card, lambda c: isinstance(c, ft.TextField), [])}
    fields["모델 이름 (버전 포함)"].value = "unit-test-model"
    fields["입력 $/100만"].value = "0.3"
    fields["출력 $/100만"].value = "2.5"
    save = find(text_card, lambda c: isinstance(c, ft.FilledButton), [])[0]
    save.on_click(None)
    model = repo.find_model("google", "unit-test-model")
    assert model is not None and repo.resolve_slot_model("text")["model_id"] == "unit-test-model"
    price = repo.get_model_price("google", "unit-test-model")
    assert (price["input_per_mtok"], price["output_per_mtok"]) == (0.3, 2.5)

    # 이미지 슬롯: 장당 단가가 모델 행에 저장되고, 이름을 비우고 저장하면 슬롯이 비워진다.
    tab = mrv.build_models_tab(FakePage(), 1.0)
    image_card = card("AI 이미지 생성 모델")
    f = {x.label: x for x in find(image_card, lambda c: isinstance(c, ft.TextField), [])}
    f["모델 이름 (버전 포함)"].value = "img-x"
    f["입력 $/100만"].value = "0.25"
    f["출력 단가 ($)"].value = "0.0336"        # 기본 단위: 이미지 1장당
    f["글자·추론 출력 $/100만"].value = "7.5"
    f["메모 (예: 2027-01-01부터 가격이 2배로 바뀜 — 그날 단가를 다시 입력)"].value = "2027-01-01 가격 변경"
    find(image_card, lambda c: isinstance(c, ft.FilledButton), [])[0].on_click(None)
    assert repo.resolve_slot_model("image")["per_image"] == 0.0336
    price = repo.get_model_price("google", "img-x")
    assert (price["input_per_mtok"], price["output_per_mtok"]) == (0.25, 7.5)
    assert repo.find_model("google", "img-x")["note"] == "2027-01-01 가격 변경"
    # 단위를 '100만 토큰당'으로 바꾸면 장당 단가는 비워지고 토큰 단가로 계산한다
    f_unit = next(x for x in find(image_card, lambda c: isinstance(c, ft.Dropdown), []) if x.label == "출력 단위")
    f_unit.value = "token"
    find(image_card, lambda c: isinstance(c, ft.FilledButton), [])[0].on_click(None)
    assert repo.find_model("google", "img-x")["per_image"] is None
    assert repo.get_model_price("google", "img-x")["output_per_mtok"] == 0.0336
    f_unit.value = "image"
    find(image_card, lambda c: isinstance(c, ft.FilledButton), [])[0].on_click(None)
    assert repo.find_model("google", "img-x")["per_image"] == 0.0336
    # 입력은 100만 토큰당, 출력은 장당으로 계산 — 출력 토큰은 세지 않는다.
    repo.log_usage("image", vendor="google", model="img-x", image_count=1, est_input_tokens=1000, est_output_tokens=1290)
    row = next(r for r in repo.cost_by_model() if r["model"] == "img-x")
    # 입력 1000토큰 + 이미지 1장 + (출력 1290 − 이미지 1120 = 글자·추론 170토큰) × 7.5
    assert abs(row["cost_usd"] - (1000 * 0.25 / 1e6 + 0.0336 + 170 * 7.5 / 1e6)) < 1e-9
    f["모델 이름 (버전 포함)"].value = ""
    find(image_card, lambda c: isinstance(c, ft.FilledButton), [])[0].on_click(None)
    assert repo.resolve_slot_model("image") is None


def test_card_studio_plans_edits_and_renders(populated, tmp_path, monkeypatch):
    """워크벤치 카드뉴스 탭: 기획(AI 끔) → 내용 저장 → 그리기까지 핸들러를 직접 눌러 본다."""
    import os
    from cards import paths as card_paths
    from flet_app.views import card_studio
    monkeypatch.setattr(card_studio, "EXPORTS_DIR", str(tmp_path))
    campaign = repo.get_campaign(populated["a"]["id"])
    repo.update_campaign(campaign["id"], content="마음이 지칠 땐 쉬어가도 괜찮아요.\n1. 같은 시간에 눕기\n2. 화면 멀리하기\n3. 따뜻한 차 한 잔")
    campaign = repo.get_campaign(campaign["id"])
    page = FakePage()
    page.run_thread = lambda fn: fn()
    tab = card_studio.build_card_tab(page, campaign, 1.0)
    assert _walk(tab) > 15
    from cards import preview as card_preview
    monkeypatch.setattr(card_preview, "PREVIEW_DIR", str(tmp_path / "pv"))
    shown = []
    page.show_dialog = lambda d: shown.append(d)
    # 종류·디자인 미리보기 버튼: 눌러서 샘플 카드 대화상자가 뜨는지
    def find_btn(root):
        for attr in ("content", "controls"):
            child = getattr(root, attr, None)
            for c in (child if isinstance(child, list) else [child]):
                if isinstance(c, ft.BaseControl):
                    if getattr(c, "content", None) == "미리보기":
                        return c
                    r = find_btn(c)
                    if r:
                        return r
    find_btn(tab).on_click(None)
    assert shown and _walk(shown[-1]) > 8

    def buttons(root, label, out=None):
        out = [] if out is None else out
        for attr in ("content", "controls"):
            child = getattr(root, attr, None)
            for c in (child if isinstance(child, list) else [child]):
                if isinstance(c, ft.BaseControl):
                    if getattr(c, "content", None) == label or getattr(c, "text", None) == label:
                        out.append(c)
                    buttons(c, label, out)
        return out

    switches = []
    def collect(root):
        for attr in ("content", "controls"):
            child = getattr(root, attr, None)
            for c in (child if isinstance(child, list) else [child]):
                if isinstance(c, ft.BaseControl):
                    if isinstance(c, ft.Switch):
                        switches.append(c)
                    collect(c)
    collect(tab)
    switches[0].value = False                       # AI 끔
    buttons(tab, "카드 기획하기")[0].on_click(None)
    stored = repo.get_campaign(campaign["id"])["card_storyboard"]
    assert stored and len(stored["card_slides"]) >= 3 and stored["card_slides"][-1]["slide_type"] == "call_to_action"
    # 기획 뒤 화면을 다시 만들면 저장된 카드가 편집 칸으로 보인다 → 그리기까지
    tab2 = card_studio.build_card_tab(page, repo.get_campaign(campaign["id"]), 1.0)
    buttons(tab2, "카드 그리기")[0].on_click(None)
    after = repo.get_campaign(campaign["id"])
    assert after["card_export_dir"] and os.path.exists(os.path.join(after["card_export_dir"], "slide_01.png"))


def test_card_studio_single_card_redraw_keeps_other_cards(populated, tmp_path, monkeypatch):
    import os
    from flet_app.views import card_studio
    from cards.director import plan_cards
    monkeypatch.setattr(card_studio, "EXPORTS_DIR", str(tmp_path))
    cid = populated["a"]["id"]
    sb, _ = plan_cards("마음이 지칠 땐 쉬어가도 괜찮아요.\n1. 눕기\n2. 쉬기\n3. 차 마시기", "info_summary", use_llm=False)
    first = card_studio.render_storyboard(cid, sb)
    keep = os.path.getmtime(first[1])
    sb.card_slides[0].lead_headline = "바뀐 제목"
    second = card_studio.render_one(cid, sb, 0)
    assert len(second) == len(first) and all(os.path.exists(p) for p in second)
    assert os.path.dirname(second[0]) != os.path.dirname(first[0]) and not os.path.exists(os.path.dirname(first[0]))
    assert os.path.getmtime(second[1]) <= os.path.getmtime(second[0])     # 다른 카드는 다시 그리지 않고 복사만
    assert abs(os.path.getmtime(second[1]) - keep) < 5
    assert repo.get_campaign(cid)["card_export_dir"] == os.path.dirname(second[0])


def test_card_types_tab_duplicates_pack_and_design(tmp_path, monkeypatch):
    from cards import card_types, design_templates
    from flet_app.views import card_types_view
    monkeypatch.setattr(card_types, "CUSTOM_DIR", str(tmp_path / "types"))
    monkeypatch.setattr(design_templates, "TEMPLATES_DIR", str(tmp_path / "designs"))
    tab = card_types_view.build_card_types_tab(FakePage(), 1.0)
    assert _walk(tab) > 30

    def icon_buttons(root, tooltip, out=None):
        out = [] if out is None else out
        for attr in ("content", "controls"):
            child = getattr(root, attr, None)
            for c in (child if isinstance(child, list) else [child]):
                if isinstance(c, ft.BaseControl):
                    if getattr(c, "tooltip", None) == tooltip:
                        out.append(c)
                    icon_buttons(c, tooltip, out)
        return out

    icon_buttons(tab, "복제해서 수정")[0].on_click(None)        # 첫 카드 종류 복제
    packs, errors = card_types.load_all(include_hidden=True)
    custom = [p for p in packs.values() if p["source"] == "custom"]
    assert len(custom) == 1 and custom[0]["status"] == "draft" and not errors
    designs = [d for d in design_templates.list_all() if not d.builtin]
    assert not designs
    # 복제 뒤 화면이 다시 만들어지므로 새 탭에서 디자인 복제 버튼(종류 버튼들 다음)을 누른다
    tab2 = card_types_view.build_card_types_tab(FakePage(), 1.0)
    n_types = len(card_types.load_all(include_hidden=True)[0])
    icon_buttons(tab2, "복제해서 수정")[n_types].on_click(None)
    assert len([d for d in design_templates.list_all() if not d.builtin]) == 1


def _find_all(root, pred, out=None):
    out = [] if out is None else out
    if pred(root):
        out.append(root)
    for attr in ("content", "controls", "actions"):
        child = getattr(root, attr, None)
        for c in (child if isinstance(child, list) else [child]):
            if isinstance(c, ft.BaseControl):
                _find_all(c, pred, out)
    return out


def _label(c):
    return getattr(c, "content", None) if isinstance(getattr(c, "content", None), str) else getattr(c, "text", None)


def test_card_studio_manual_photo_choice_and_ai_images_with_cost(populated, tmp_path, monkeypatch):
    from cards import images
    from flet_app.views import card_studio
    monkeypatch.setattr(card_studio, "EXPORTS_DIR", str(tmp_path))
    ref = repo.upsert_model("google", "img-model", "Img", ["image"], per_image=0.05)
    repo.set_slot("image", ref)
    monkeypatch.setattr(images, "_generate_gemini", lambda model, prompt, aspect: (b"\x89PNG", ".png", {"in": 1, "out": 2}))
    cid = populated["a"]["id"]
    repo.update_campaign(cid, content="마음이 지칠 땐 쉬어가도 괜찮아요.\n왜 그럴까요? 몸이 보내는 신호예요.\n1. 눕기\n2. 쉬기\n3. 차 마시기")
    page = FakePage()
    shown = []
    page.run_thread = lambda fn: fn()
    page.show_dialog = lambda d: shown.append(d)
    page.pop_dialog = lambda: None

    def tab():
        return card_studio.build_card_tab(page, repo.get_campaign(cid), 1.0)

    t = tab()
    switch = _find_all(t, lambda c: isinstance(c, ft.Switch))[0]
    switch.value = False
    mode = _find_all(t, lambda c: isinstance(c, ft.Dropdown) and c.label == "이미지")[0]
    mode.value = "own_first"
    _find_all(t, lambda c: isinstance(c, ft.Dropdown) and c.label == "카드 종류")[0].value = "empathy"   # 사진 칸이 여러 개인 종류
    _find_all(t, lambda c: _label(c) == "카드 기획하기")[0].on_click(None)
    sb = card_studio.load_storyboard(repo.get_campaign(cid))
    assert sb and sb.image_mode == "own_first" and sb.card_slides[0].asset_id is None

    t = tab()                                       # 저장된 카드로 다시 그린 화면
    text = " ".join(str(getattr(c, "value", "")) for c in _find_all(t, lambda c: isinstance(c, ft.Text)))
    assert "예상 $" in text                          # 실행 전 예상 비용이 보인다
    photo_dds = _find_all(t, lambda c: isinstance(c, ft.Dropdown) and c.label == "사진")
    assert photo_dds
    photo_dds[0].value = "none"                      # 첫 사진 칸은 '사진 없음'으로 직접 고른다
    _find_all(t, lambda c: _label(c) == "카드 내용 저장")[0].on_click(None)
    sb = card_studio.load_storyboard(repo.get_campaign(cid))
    assert sb.card_slides[0].asset_locked and sb.card_slides[0].asset_id is None
    before = len(images.ai_targets(sb))

    t = tab()
    ai = _find_all(t, lambda c: str(_label(c) or "").startswith("AI 이미지"))[0]
    ai.on_click(None)                                # 확인 창이 먼저 뜬다(바로 호출하지 않음)
    assert shown and "예상" in shown[-1].content.value
    go = _find_all(shown[-1], lambda c: _label(c) == "만들기")[0]
    go.on_click(None)
    sb = card_studio.load_storyboard(repo.get_campaign(cid))
    made = [a for a in sb.assets if a.source == "ai"]
    assert len(made) == before and sb.card_slides[0].asset_id is None       # 직접 '사진 없음'을 고른 카드는 건드리지 않음
    cost = sum(u["cost_usd"] or 0 for u in repo.recent_usage(20) if u["kind"] == "image")
    assert cost == pytest.approx(0.05 * before)


def test_render_keeps_ai_image_folder_and_saving_does_not_lock_auto_photos(populated, tmp_path, monkeypatch):
    """회귀: ① 카드를 그린 뒤 AI 이미지 폴더가 지워지던 문제 ② 저장만 눌러도 자동 배치 사진이 '직접 고름'으로 굳던 문제."""
    import io
    import os
    from PIL import Image as PILImage
    from cards import images
    from cards.schema import MediaAsset
    from cards.director import plan_cards
    from flet_app.views import card_studio
    monkeypatch.setattr(card_studio, "EXPORTS_DIR", str(tmp_path))
    cid = populated["a"]["id"]
    photo = tmp_path / "mine.jpg"
    PILImage.new("RGB", (400, 300), (90, 140, 120)).save(photo)
    mine = MediaAsset(id="A1", kind="image", path=str(photo), original_name="mine.jpg")
    monkeypatch.setattr(card_studio, "_assets_of", lambda campaign: [mine])
    ref = repo.upsert_model("google", "m", "M", ["image"], per_image=0.04)
    repo.set_slot("image", ref)
    sb, _ = plan_cards("마음이 지칠 땐 쉬어가도 괜찮아요.\n왜 그럴까요?\n1. 눕기\n2. 쉬기", "empathy", use_llm=False, assets=[mine])
    buf = io.BytesIO()
    PILImage.new("RGB", (300, 200), (100, 150, 120)).save(buf, "PNG")
    folder = os.path.join(str(tmp_path), "cards", cid, "assets")
    images.generate_missing(sb, folder, generate=lambda m, p, a: (buf.getvalue(), ".png", {}))
    ai_paths = [a.path for a in sb.assets if a.source == "ai"]
    assert ai_paths
    card_studio.save_storyboard(cid, sb)
    card_studio.render_storyboard(cid, sb)
    card_studio.render_storyboard(cid, sb)
    assert all(os.path.exists(p) for p in ai_paths)                 # 두 번 그려도 AI 이미지는 그대로

    page = FakePage()
    page.run_thread = lambda fn: fn()
    tab = card_studio.build_card_tab(page, repo.get_campaign(cid), 1.0)
    _find_all(tab, lambda c: _label(c) == "카드 내용 저장")[0].on_click(None)       # 아무것도 바꾸지 않고 저장
    saved = card_studio.load_storyboard(repo.get_campaign(cid))
    assert saved.card_slides[0].asset_id == "A1" and not saved.card_slides[0].asset_locked
    assert not any(s.asset_locked for s in saved.card_slides)


def test_shorts_tab_needs_cards_then_converts_estimates_and_renders(populated, tmp_path, monkeypatch):
    import os
    from cards import ffmpeg_tools
    from cards.director import plan_cards
    from flet_app.views import card_studio, shorts_studio
    monkeypatch.setattr(shorts_studio, "EXPORTS_DIR", str(tmp_path))
    cid = populated["a"]["id"]
    page = FakePage()
    page.run_thread = lambda fn: fn()
    shown = []
    page.show_dialog = lambda d: shown.append(d)
    page.pop_dialog = lambda: None
    first = shorts_studio.build_shorts_tab(page, repo.get_campaign(cid), 1.0)
    assert "먼저" in first.value                                    # 카드가 없으면 안내만
    sb, _ = plan_cards("마음이 지칠 땐 쉬어가도 괜찮아요.\n1. 눕기\n2. 쉬기\n3. 차 마시기", "howto", use_llm=False)
    card_studio.save_storyboard(cid, sb)
    ref = repo.upsert_model("google", "tts-m", "T", ["tts"], per_second=0.01)
    repo.set_slot("tts", ref)

    tab = shorts_studio.build_shorts_tab(page, repo.get_campaign(cid), 1.0)
    _find_all(tab, lambda c: _label(c) == "카드에서 대본 만들기")[0].on_click(None)
    saved = card_studio.load_storyboard(repo.get_campaign(cid))
    assert saved.shorts_scenes and saved.shorts_scenes[-1].section_type == "conclusion"
    tab = shorts_studio.build_shorts_tab(page, repo.get_campaign(cid), 1.0)
    text = " ".join(str(getattr(c, "value", "")) for c in _find_all(tab, lambda c: isinstance(c, ft.Text)))
    assert "예상 약 $" in text                                          # 실행 전 음성 예상 비용
    render = _find_all(tab, lambda c: _label(c) == "쇼츠 영상 만들기")[0]
    render.on_click(None)
    assert shown and "예상" in shown[-1].content.value               # 확인 창이 먼저 뜬다
    if ffmpeg_tools.available():
        async def fake(model, text, voice):
            import io, wave
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b"\0\0" * 24000 * 3)
            return buf.getvalue(), {}
        out = shorts_studio.render_video(cid, saved, "auto", "tri", tts_call=fake)
        path = out.splitlines()[0]
        assert os.path.exists(path) and repo.get_campaign(cid)["shorts_video_path"] == path


def test_naver_tab_switch_saves_and_shows_details(populated):
    from ai_workers import keyword_research as kr
    from flet_app.views import settings_view
    tab = settings_view._build_naver_tab(FakePage(), 1.0)
    switch = _find_all(tab, lambda c: isinstance(c, ft.Switch))[0]
    assert switch.value is False and kr.enabled() is False             # 기본은 꺼짐
    details = [c for c in tab.controls if isinstance(c, ft.Column) and len(c.controls) > 4][0]
    assert details.visible is False                                     # 꺼져 있으면 키 입력 등은 숨김
    switch.value = True
    switch.on_change(None)
    assert kr.enabled() is True and details.visible is True
    switch.value = False
    switch.on_change(None)
    assert kr.enabled() is False and details.visible is False


def test_studio_view_flow_make_edit_apply_and_script(populated, tmp_path, monkeypatch):
    """🃏 카드·쇼츠 스튜디오: 카드 만들기 → 한 장 고쳐 적용 → 쇼츠 대본까지 버튼을 직접 눌러 본다."""
    import os
    from flet_app.views import card_studio, studio_view
    monkeypatch.setattr(card_studio, "EXPORTS_DIR", str(tmp_path))
    cid = populated["a"]["id"]
    repo.update_campaign(cid, memo="마음이 지칠 땐 쉬어가도 괜찮아요.\n1. 같은 시간에 눕기\n2. 화면 멀리하기\n3. 따뜻한 차 한 잔\n혼자 어려우면 상담이 있어요.")
    state = AppState()
    state.studio_campaign_id = cid
    page = FakePage()
    page.run_thread = lambda fn: fn()
    shown = []
    page.show_dialog = lambda d: shown.append(d)
    root = studio_view.build(page, state)
    assert _walk(root) > 20

    def find(control, label, out=None):
        out = [] if out is None else out
        for attr in ("content", "controls"):
            child = getattr(control, attr, None)
            for c in (child if isinstance(child, list) else [child]):
                if isinstance(c, ft.BaseControl):
                    if label in (getattr(c, "content", None), getattr(c, "text", None)):
                        out.append(c)
                    find(c, label, out)
        return out

    count_dd = next(x for x in _collect(root, ft.Dropdown) if x.label == "카드 장수")
    assert [o.key for o in count_dd.options][0] == "1" and len(count_dd.options) > 3
    find(root, "🃏 카드 만들기")[0].on_click(None)
    c = repo.get_campaign(cid)
    assert c["card_storyboard"] and c["card_export_dir"] and os.path.exists(os.path.join(c["card_export_dir"], "slide_01.png"))
    # 다듬기: 제목을 고치고 [적용] → 저장·다시 그리기
    edit = find(root, "적용 (이 카드 다시 그리기)")
    assert edit, "② 다듬기 구역이 보여야 합니다"
    heads = [f for f in _collect(root, ft.TextField) if (f.label or "").startswith("제목")]
    heads[0].value = "고친 제목입니다"
    edit[0].on_click(None)
    assert repo.get_campaign(cid)["card_storyboard"]["card_slides"][0]["lead_headline"] == "고친 제목입니다"
    # 쇼츠 대본
    find(root, "카드에서 대본 만들기")[0].on_click(None)
    assert repo.get_campaign(cid)["card_storyboard"]["shorts_scenes"]


def _collect(control, kind, out=None):
    out = [] if out is None else out
    if isinstance(control, kind):
        out.append(control)
    for attr in ("content", "controls"):
        child = getattr(control, attr, None)
        for c in (child if isinstance(child, list) else [child]):
            if isinstance(c, ft.BaseControl):
                _collect(c, kind, out)
    return out


def test_video_slot_saves_output_in_seconds_or_tokens(populated):
    from flet_app.views import model_registry_view as mrv
    tab = mrv.build_models_tab(FakePage(), 1.0)
    card = next(c for c in _collect(tab, ft.Container) if isinstance(getattr(c, "content", None), ft.Column)
                and any(getattr(x, "value", None) == "AI 영상 모델" for x in c.content.controls))
    f = {x.label: x for x in _collect(card, ft.TextField)}
    unit = next(x for x in _collect(card, ft.Dropdown) if x.label == "영상 출력 단위")
    save = _collect(card, ft.FilledButton)[0]
    f["모델 이름 (버전 포함)"].value = "omni-x"
    f["입력 $/100만"].value, f["출력 $/100만"].value = "1.5", "9"
    f["영상 출력 단가 ($)"].value = "12"
    assert unit.value == "token"               # 기본 단위: 100만 토큰당(공식 가격표 방식)
    save.on_click(None)
    m = repo.find_model("google", "omni-x")
    assert m["per_second"] is None and m["options"]["video_out_per_mtok"] == 12.0
    unit.value = "second"
    save.on_click(None)
    m = repo.find_model("google", "omni-x")
    assert m["per_second"] == 12.0 and "video_out_per_mtok" not in m["options"]
    assert repo.get_model_price("google", "omni-x")["output_per_mtok"] == 9.0


def test_photo_thumbnails_use_inline_images_and_survive_unreadable_files(tmp_path):
    """워크벤치 사진 칸은 경로가 아니라 줄인 그림(base64)으로 보여야 웹 모드에서도 보인다. 못 읽는 파일은 이름 상자로 대체."""
    from PIL import Image
    from flet_app.image_src import b64_src, image_or_placeholder
    good, bad = tmp_path / "a.jpg", tmp_path / "b.heic"
    Image.new("RGB", (2000, 1000), "#336699").save(good)
    bad.write_bytes(b"not an image")
    assert b64_src(str(good), 200)
    assert b64_src(str(bad), 200) is None
    assert isinstance(image_or_placeholder(str(good), 90, 90), ft.Image)
    assert isinstance(image_or_placeholder(str(bad), 90, 90), ft.Container)


def test_studio_card_count_one_makes_a_single_card(populated, tmp_path, monkeypatch):
    from flet_app.views import card_studio, studio_view
    monkeypatch.setattr(card_studio, "EXPORTS_DIR", str(tmp_path))
    cid = populated["a"]["id"]
    repo.update_campaign(cid, memo="마음이 지칠 땐 쉬어가도 괜찮아요. 오늘은 10분만 눈을 감아 보세요. 작은 쉼이 마음을 가볍게 합니다.")
    state = AppState()
    state.studio_campaign_id = cid
    page = FakePage()
    page.run_thread = lambda fn: fn()
    page.show_dialog = lambda d: None
    root = studio_view.build(page, state)
    count_dd = next(x for x in _collect(root, ft.Dropdown) if x.label == "카드 장수")
    count_dd.value = "1"
    next(b for b in _collect(root, ft.FilledButton) if getattr(b, "content", None) == "🃏 카드 만들기").on_click(None)
    sb = repo.get_campaign(cid)["card_storyboard"]
    assert len(sb["card_slides"]) == 1 and sb["card_slides"][0]["slide_type"] == "single"


def test_save_bytes_sends_src_bytes_in_web_mode_and_writes_the_file_on_desktop(tmp_path, monkeypatch):
    """웹 모드의 save_file은 src_bytes가 필수(없으면 오류) — 웹은 내용을 넘기고, 데스크톱은 고른 경로에 확장자를 붙여 쓴다."""
    import asyncio
    import zipfile
    from flet_app import save_dialog
    calls = []

    class FakePicker:
        async def save_file(self, **kw):
            calls.append(kw)
            if kw.get("src_bytes") is None and kw.get("web_check"):
                raise ValueError('"src_bytes" is required')
            return str(tmp_path / "picked") if not kw.get("src_bytes") else None

    monkeypatch.setattr(save_dialog.ft, "FilePicker", FakePicker)
    web = type("P", (), {"web": True})()
    desk = type("P", (), {"web": False})()
    assert asyncio.run(save_dialog.save_bytes(web, b"abc", "x.osmu", "osmu")) == ("x.osmu", "download")
    assert calls[-1]["src_bytes"] == b"abc" and calls[-1]["file_name"] == "x.osmu"
    path, how = asyncio.run(save_dialog.save_bytes(desk, b"xyz", "x.osmu", "osmu"))
    assert how == "file" and path.endswith("picked.osmu") and open(path, "rb").read() == b"xyz"
    assert "src_bytes" not in calls[-1]
    f = tmp_path / "a.png"
    f.write_bytes(b"png")
    z = save_dialog.zip_files([str(f)], "cards/")
    assert zipfile.ZipFile(__import__("io").BytesIO(z)).namelist() == ["cards/a.png"]


def _import_tab_with_picker(monkeypatch, files, web=True):
    import asyncio
    from flet_app.views import settings_view as sv

    class Picker:
        async def pick_files(self, **kw):
            Picker.kwargs = kw
            return files

    monkeypatch.setattr(sv.ft, "FilePicker", Picker)
    page = type("P", (), {"web": web, "update": lambda self: None, "__getattr__": lambda self, n: (lambda *a, **k: None)})()
    tab = sv._build_transfer_tab(page, 1.0)
    allc = _collect(tab, ft.BaseControl)
    open_btn = next(c for c in allc if ".osmu 파일 열기" in str(getattr(c, "content", "")))
    imp_btn = next(c for c in allc if "이 PC에 가져오기" in str(getattr(c, "content", "")))
    texts = [c for c in allc if isinstance(c, ft.Text)]
    asyncio.run(open_btn.on_click(None))
    return imp_btn, texts, Picker


def test_import_enables_button_for_a_real_bundle_and_explains_failures(monkeypatch):
    from core import transfer
    data = transfer.export_bundle(["company"], None)
    F = lambda **kw: type("F", (), {"name": "x.osmu", "path": None, "size": 1, "bytes": None, **kw})()
    btn, texts, picker = _import_tab_with_picker(monkeypatch, [F(bytes=data)])
    assert btn.disabled is False and picker.kwargs["cancel_upload_on_window_blur"] is False and "allowed_extensions" not in picker.kwargs
    # 아무것도 못 받았을 때는 조용히 멈추지 않고 이유를 보인다(버튼은 그대로 꺼짐)
    btn, texts, _ = _import_tab_with_picker(monkeypatch, [])
    assert btn.disabled is True and any("전달하지 못했습니다" in (t.value or "") for t in texts)
    btn, texts, _ = _import_tab_with_picker(monkeypatch, [F(bytes=None)])
    assert btn.disabled is True and any("읽지 못했습니다" in (t.value or "") for t in texts)
    btn, texts, _ = _import_tab_with_picker(monkeypatch, [F(bytes=b"not a bundle")])
    assert btn.disabled is True and any("❌" in (t.value or "") for t in texts)


def test_published_posts_keep_their_card_work_and_stay_reachable(populated, tmp_path, monkeypatch):
    """게시 완료로 바뀌어도 카드·쇼츠 작업은 그대로이고, 워크벤치·스튜디오 목록과 대시보드에서 계속 열 수 있다."""
    from flet_app.views import dashboard_view, studio_view, workbench_view
    cid = populated["a"]["id"]
    sb = {"title": "t", "target_audience": "", "tone_and_manner": "", "visual_style": "", "is_anonymized": False,
          "card_slides": [{"slide_number": 1, "slide_type": "cover", "lead_headline": "제목", "body_content": "", "takeaway": ""}],
          "sns_caption": "", "design_id": "tri-2-5-3"}
    repo.update_campaign(cid, title="게시할 글", content="본문", card_storyboard=sb)
    repo.mark_published(cid, "https://blog.naver.com/x/1")
    c = repo.get_campaign(cid)
    assert c["status"] == "published" and c["card_storyboard"]["card_slides"][0]["lead_headline"] == "제목"

    state = AppState()
    state.studio_campaign_id = cid
    page = FakePage()
    root = studio_view.build(page, state)
    selector = next(x for x in _collect(root, ft.Dropdown) if x.label == "카드·쇼츠를 만들 글")
    assert cid in [o.key for o in selector.options] and selector.value == cid

    state2 = AppState()
    state2.pending_workbench_campaign_id = None
    wb = workbench_view.build(page, state2)
    wsel = next(x for x in _collect(wb, ft.Dropdown) if x.label == "작업할 콘텐츠")
    assert cid in [o.key for o in wsel.options]
    keys = [o.key for o in wsel.options]
    assert keys.index(cid) > keys.index(populated["b"]["id"])             # 게시 완료 글은 진행 중인 글 뒤쪽

    board = dashboard_view.build(page, AppState())
    buttons = [getattr(b, "content", None) for b in _collect(board, ft.TextButton)]
    assert "🃏 카드·쇼츠" in buttons and "✍️ 작업 열기" in buttons


def test_dashboard_blog_panel_builds_with_and_without_feed(populated):
    from core import blog_feed
    from flet_app.views import blog_panel
    page = FakePage()
    assert _walk(blog_panel.build(page, 1.0, AppState(), lambda live: None)) >= 3          # 가져오기 전
    repo.set_app_state(blog_feed.STATE_KEY, {"blog_id": "onjaram", "fetched_at": "2026-11-07T10:00:00", "posts": [
        {"title": "[출강 후기] 청년 특강", "category": "외부 강의", "date": "2026-10-25", "link": "https://blog.naver.com/onjaram/1", "tags": ["온자람"], "summary": ""},
        {"title": "2025 바우처 모집 안내", "category": "온자람 소식", "date": "2025-01-31", "link": "https://blog.naver.com/onjaram/2", "tags": [], "summary": ""}]})
    assert _walk(blog_panel.build(page, 1.0, AppState(), lambda live: None)) > 15          # 가져온 뒤
