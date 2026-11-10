"""⚙️ 설정 → 🤖 모델 등록 탭.


기능(슬롯)마다 쓸 모델을 **벤더 선택 + 모델 이름(버전 포함) 직접 입력 + 단가**로 한 줄에 등록합니다.
모델이 단종되거나 새로 나오면 이름만 고쳐 저장하면 되고, 코드에 모델 이름이 박혀 있지 않습니다.
단가는 이 화면에서만 입력합니다(📈 사용량 탭은 보기 전용). 비워 두면 '단가 미등록'이며 0원이 아닙니다.

- 글자(토큰) 단가는 `model_prices`, 이미지·영상·음성 단가는 모델 등록 행(per_image/per_second)에 저장됩니다.
- '블로그 글 모델'·'사진 분석 모델'은 모델 이름을 비우면 기본 글쓰기 모델을 따릅니다.
- API 키는 벤더마다 하나라서 🔑 LLM 벤더 탭에서 등록합니다.
"""
from __future__ import annotations

import flet as ft

from ai_workers.multi_llm_router import VENDORS, normalize_model_name, test_connection
from core import google_catalog, repo
from core.crypto_utils import decrypt_api_key, encrypt_api_key
from flet_app.components.collapsible import collapsible

from flet_app.theme import BRAND_COLORS, fs

# 단가를 입력하는 방식: 글자(토큰) / 이미지 한 장 / 초당
_TOKEN_NEEDS = ("text", "vision", "image", "tts", "video")  # 공식 가격표는 모두 100만 토큰당 단가를 기본으로 씁니다
_PRICE_PAGES = {
    "google": "https://aistudio.google.com/docs/pricing",
    "openai": "https://openai.com/api/pricing/",
    "anthropic": "https://www.anthropic.com/pricing",
}
_HINTS = {
    "text": "예: gemini-3.8-flash", "text_blog": "비우면 기본 글쓰기 모델", "vision": "비우면 기본 글쓰기 모델",
    "image": "예: gemini-3.1-flash-image", "tts": "예: gemini-3.8-flash-tts", "video": "예: gemini-omni-1.1-flash",
}


KEEP = "__keep__"   # 간편 설정에서 '지금 설정 유지'(Claude·GPT 등 고급 설정에서 지정한 모델)


def _parse(text: str | None) -> float | None:
    cleaned = (text or "").replace(",", "").replace("$", "").strip()
    if not cleaned:
        return None
    return float(cleaned)


def _fmt(value) -> str:
    return "" if value is None else f"{value:g}"


def build_models_tab(page: ft.Page, scale: float, on_changed=None) -> ft.Control:
    """모델 등록 탭. 저장하면 이 컨테이너를 통째로 다시 만듭니다."""
    box = ft.Container(padding=0)

    def _refresh(control: ft.Control) -> None:
        try:
            control.update()
        except RuntimeError:  # 아직 화면에 붙기 전(시험에서 핸들러를 직접 부를 때)
            pass

    def rebuild() -> None:
        box.content = _body()
        _refresh(box)
        if on_changed:
            on_changed()

    def slot_card(slot: str, label: str, need: str, current: dict | None) -> ft.Control:
        status = ft.Text("", size=fs(11, scale))
        vendor = ft.Dropdown(
            label="벤더", width=150, dense=True, value=(current or {}).get("vendor", "google"),
            options=[ft.DropdownOption(key=k, text=v["label"].split()[-1]) for k, v in VENDORS.items()],
        )
        model_id = ft.TextField(label="모델 이름 (버전 포함)", value=(current or {}).get("model_id", ""), width=300,
                                dense=True, hint_text=_HINTS[slot])
        price = repo.get_model_price(current["vendor"], current["model_id"]) if current else None
        f_in = ft.TextField(label="입력 $/100만", value=_fmt(price and price["input_per_mtok"]), width=150, dense=True)
        f_out = ft.TextField(label="출력 $/100만", value=_fmt(price and price["output_per_mtok"]), width=150, dense=True)
        f_cache = ft.TextField(label="캐시 $/100만", value=_fmt(price and price["cached_input_per_mtok"]), width=150,
                               dense=True, tooltip="비우면 일반 입력 단가로 계산합니다.")
        # 이미지 모델의 '출력' 단가: 공식 가격표에 따라 이미지 1장당 또는 100만 토큰당 — 한 칸에 값을 넣고 단위를 고른다.
        cur_img = (current or {}).get("per_image")
        out_unit = "image" if (cur_img is not None or not (price and price["output_per_mtok"])) else "token"
        f_image = ft.TextField(label="출력 단가 ($)", width=130, dense=True,
                               value=_fmt(cur_img if out_unit == "image" else (price and price["output_per_mtok"])))
        f_textout = ft.TextField(label="글자·추론 출력 $/100만", width=190, dense=True,
                                 value=_fmt(price and price["output_per_mtok"]) if out_unit == "image" and price and price["output_per_mtok"] else "",
                                 tooltip="공식 가격표의 'Output (text and thinking)'. 이미지 토큰은 장당 단가에 들어 있으므로, 이미지 위에 더 나온 글자·추론 토큰만 이 단가로 셉니다.")
        f_unit = ft.Dropdown(label="출력 단위", width=170, dense=True, value=out_unit,
                             options=[ft.DropdownOption(key="image", text="이미지 1장당"), ft.DropdownOption(key="token", text="100만 토큰당")])
        f_second = ft.TextField(label="초당 $ (공식이 초당일 때만)", value=_fmt((current or {}).get("per_second")), width=190, dense=True)
        # 영상 모델의 '영상 출력' 단가: 공식 표기에 따라 1초당 또는 100만 토큰당(후자는 모델 옵션에 저장 — 영상 호출 코드가 생기면 사용).
        cur_opts = (current or {}).get("options") or {}
        v_unit = "second" if (current or {}).get("per_second") is not None else "token"   # 공식 가격표는 보통 100만 토큰당
        f_vout = ft.TextField(label="영상 출력 단가 ($)", width=150, dense=True,
                              value=_fmt((current or {}).get("per_second") if v_unit == "second" else cur_opts.get("video_out_per_mtok")))
        f_vunit = ft.Dropdown(label="영상 출력 단위", width=170, dense=True, value=v_unit,
                              options=[ft.DropdownOption(key="second", text="영상 1초당"), ft.DropdownOption(key="token", text="100만 토큰당")])
        if need == "image":   # 공식 가격표: 'Image • Input: $/100만 토큰 / Output: $/이미지 1장' — 출력 토큰 단가 칸은 두지 않는다
            price_fields = [f_in, f_image, f_unit, f_textout]
        elif need == "video":
            price_fields = [f_in, f_out, f_cache, f_vout, f_vunit]
        else:
            price_fields = [f_in, f_out, f_cache] + ([f_second] if need == "tts" else [])

        f_note = ft.TextField(label="메모 (예: 2027-01-01부터 가격이 2배로 바뀜 — 그날 단가를 다시 입력)", value=(current or {}).get("note") or "",
                              width=620, dense=True)

        def say(msg: str, ok: bool = True) -> None:
            status.value = msg
            status.color = "#1B6E3C" if ok else "#B3261E"
            _refresh(status)

        def on_save(e: ft.Event) -> None:
            try:
                clean = normalize_model_name(vendor.value, model_id.value)
                if not clean:
                    repo.set_slot(slot, None)
                    rebuild()
                    return
                existing = repo.find_model(vendor.value, clean)
                caps = list(dict.fromkeys(((existing or {}).get("capabilities") or []) + [need]))
                p_in, p_out, p_cache = _parse(f_in.value), _parse(f_out.value), _parse(f_cache.value)
                per_image = (existing or {}).get("per_image")
                if need == "image":
                    out_value = _parse(f_image.value)
                    if f_unit.value == "image":      # 출력은 이미지 1장당: 이미지 토큰은 장수 × 단가, 그 위의 글자·추론 토큰은 글자 출력 단가
                        per_image = out_value
                        p_out = (_parse(f_textout.value) or 0.0) if p_in is not None else None
                    else:                            # 출력은 100만 토큰당: 토큰 수 × 단가로 계산(장당 단가는 비움)
                        per_image, p_out = None, out_value
                if (p_in is None) != (p_out is None):
                    raise ValueError("입력·출력 단가는 함께 넣거나 둘 다 비워 두세요.")
                per_second = _parse(f_second.value) if need == "tts" else (existing or {}).get("per_second")
                options = dict((existing or {}).get("options") or {})
                if need == "video":
                    v = _parse(f_vout.value)
                    if f_vunit.value == "second":
                        per_second = v
                        options.pop("video_out_per_mtok", None)
                    else:
                        per_second = None
                        options["video_out_per_mtok"] = v
                ref = repo.upsert_model(vendor.value, clean, display_name=(existing or {}).get("display_name") or clean,
                                        capabilities=caps, enabled=True, per_image=per_image, per_second=per_second,
                                        note=f_note.value or "", options=options,
                                        model_ref=(existing or {}).get("id"))
                if need in _TOKEN_NEEDS:
                    if p_in is not None and p_out is not None:
                        repo.save_model_price(vendor.value, clean, p_in, p_out, p_cache)
                    else:
                        repo.delete_model_price(vendor.value, clean)
                repo.set_slot(slot, ref)
            except ValueError as exc:
                say(str(exc), ok=False)
                return
            rebuild()
            say_after = "" if (repo.get_llm_setting(vendor.value) or {}).get("is_active") else \
                " (이 벤더의 API 키는 🔑 LLM 벤더 탭에서 등록하세요)"
            say(f"✅ 저장했습니다.{say_after}")

        def on_test(e: ft.Event) -> None:
            clean = normalize_model_name(vendor.value, model_id.value)
            setting = repo.get_llm_setting(vendor.value)
            if not clean:
                say("모델 이름을 먼저 입력하세요.", ok=False)
                return
            if not setting:
                say("이 벤더의 API 키가 없습니다 (🔑 LLM 벤더 탭)", ok=False)
                return
            say("⏳ 테스트 중…")

            def _work() -> None:
                try:
                    ok, message = test_connection(vendor.value, clean, decrypt_api_key(setting["encrypted_api_key"]))
                except Exception as exc:  # noqa: BLE001 — 스레드에서 조용히 사라지지 않게
                    ok, message = False, str(exc)
                say(f"{'✅' if ok else '❌'} {message}"[:200], ok)

            page.run_thread(_work)

        price_button = ft.TextButton("공식 가격 보기", icon=ft.Icons.OPEN_IN_NEW, url=_PRICE_PAGES.get(vendor.value))

        def sync_price_url(e=None) -> None:
            price_button.url = _PRICE_PAGES.get(vendor.value)
            try:
                price_button.update()
            except RuntimeError:
                pass

        vendor.on_select = sync_price_url

        actions = [ft.FilledButton("저장", on_click=on_save)]
        if need in ("text", "vision"):
            actions.append(ft.OutlinedButton("연결 테스트", on_click=on_test))
        actions.append(price_button)
        in_use = current is not None
        unpriced = in_use and price is None and current.get("per_image") is None and current.get("per_second") is None
        return ft.Container(
            content=ft.Column([
                ft.Text(label, weight=ft.FontWeight.BOLD, size=fs(13, scale)),
                ft.Row([vendor, model_id], spacing=8, wrap=True),
                ft.Row(price_fields, spacing=8, wrap=True),
                f_note,
                *([ft.Text("공식 가격표를 옮기세요. Input은 입력 칸, 이미지 출력(예: 1K 이미지 $0.0336)은 '출력 단가' + 단위 '이미지 1장당', "
                           "'Output (text and thinking)'(예: $7.50)은 '글자·추론 출력' 칸입니다. 앱은 이미지를 1K 크기로 요청하므로 1K 가격을 넣으세요.",
                           size=fs(10, scale), color=BRAND_COLORS["text_muted"])] if need == "image" else []),
                *([ft.Text("공식 화면의 'Text, Image, Video • Input/Output'은 위 입력·출력 칸(100만 토큰당)에, 'Video • Output'은 "
                           "'영상 출력 단가'에 넣고 공식 표기에 맞는 단위(1초당/100만 토큰당)를 고르세요. 단위가 안 보이면 공식 가격 페이지에서 확인하세요.",
                           size=fs(10, scale), color=BRAND_COLORS["text_muted"])] if need == "video" else []),
                *([ft.Text("공식 화면의 'Text in / Audio out • Input/Output'은 100만 토큰당 가격이므로 입력·출력 칸에 그대로 넣으면 됩니다.",
                           size=fs(10, scale), color=BRAND_COLORS["text_muted"])] if need == "tts" else []),
                ft.Row(actions, spacing=8, wrap=True),
                *([ft.Text("단가 미등록 — 비용이 0원이 아니라 '단가 미등록'으로 기록됩니다.", size=fs(10, scale), color="#B3261E")]
                  if unpriced else []),
                status,
            ], spacing=6),
            border=ft.Border.all(1, "#14000000"), border_radius=8, padding=12,
        )

    # --- 간편 설정(Google) -----------------------------------------------------
    # 키만 넣으면: 키로 쓸 수 있는 모델 조회 → 공식 가격표 읽기 → 기능별 추천 → [적용].
    found: dict = {}

    def current_summary() -> str:
        slots = repo.get_slots()
        parts = []
        for slot in ("text", "image", "tts"):
            m = repo.get_model(slots[slot]["model_ref"])
            label = repo.MODEL_SLOTS[slot][0].split(" (")[0]
            if not m:
                parts.append(f"{label}: 지정 안 됨")
                continue
            priced = repo.get_model_price(m["vendor"], m["model_id"]) or m.get("per_image") is not None
            parts.append(f"{label}: {m['display_name']}" + ("" if priced else " (단가 미등록)"))
        return "지금 설정 — " + " · ".join(parts)

    def simple_panel() -> ft.Control:
        setting = repo.get_llm_setting("google")
        has_key = bool(setting and setting.get("is_active"))
        status = ft.Text("", size=fs(11, scale))
        spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        key_field = ft.TextField(label="Google API 키", password=True, can_reveal_password=True, width=420, dense=True,
                                 hint_text="AI Studio에서 받은 키를 붙여 넣으세요", visible=not has_key)
        change_key = ft.TextButton("키 바꾸기", visible=has_key)
        result_box = ft.Column(spacing=8)
        fetched = (repo.get_app_state(google_catalog.STATE_KEY) or {}).get("fetched")

        def say(msg: str, ok: bool = True) -> None:
            status.value = msg
            status.color = "#1B6E3C" if ok else "#B3261E"
            _refresh(status)

        def busy(on: bool) -> None:
            spinner.visible = on
            fetch_btn.disabled = on
            _refresh(spinner)
            _refresh(fetch_btn)

        def on_change_key(e: ft.Event) -> None:
            key_field.visible, change_key.visible = True, False
            _refresh(key_field)
            _refresh(change_key)

        def show_choices() -> None:
            priced, available = found["priced"], found["available"]
            rec = google_catalog.recommend(priced, available)
            avail_set = set(available or [])
            slots = repo.get_slots()
            rows, dropdowns = [], {}
            for slot in google_catalog.RULES:
                options = google_catalog.candidates(slot, priced, available)
                current = repo.get_model(slots[slot]["model_ref"])
                # 이미 쓰고 있는 Google 모델이 고를 수 있는 목록에 있으면 그대로 둔다(사용자가 고른 것을 추천으로 덮어쓰지 않음).
                keep = current["model_id"] if (current and current["vendor"] == "google" and current["model_id"] in options) else None
                other = current if (current and current["vendor"] != "google") else None   # Claude·GPT 등 직접 지정한 모델
                chosen = (KEEP if other else None) or keep or rec[slot]
                info = ft.Text("고급 설정에 등록한 모델과 단가를 그대로 씁니다." if chosen == KEEP else
                               google_catalog.price_line(priced.get(chosen)) if chosen else "고를 수 있는 모델이 없습니다",
                               size=fs(10, scale), color=BRAND_COLORS["text_muted"])
                dd = ft.Dropdown(label=repo.MODEL_SLOTS[slot][0], width=600, dense=True, value=chosen,
                                 options=[ft.DropdownOption(key=m, text=f"{priced[m]['name']}  ({m})"
                                                            + ("  ← 추천" if m == rec[slot] else "") + ("  (지금 사용 중)" if m == keep else "")
                                                            + ("" if m in avail_set else "  (키 목록에 없음)")) for m in options]
                                 + ([ft.DropdownOption(key=KEEP, text=f"지금 설정 유지: {other['display_name']} ({other['vendor']})")] if other else []))

                def on_pick(e, info=info, dd=dd) -> None:
                    info.value = ("고급 설정에 등록한 모델과 단가를 그대로 씁니다." if dd.value == KEEP
                                  else google_catalog.price_line(priced.get(dd.value)))
                    _refresh(info)

                dd.on_select = on_pick
                dropdowns[slot] = dd
                now = (f"지금: {current['display_name']} — 그대로 둡니다(바꾸려면 목록에서 고르세요)" if keep else
                       f"지금: {current['display_name']}" if current else "지금: 지정 안 됨")
                rows.append(ft.Column([dd, ft.Text(now, size=fs(10, scale), color=BRAND_COLORS["text_muted"]), info], spacing=2))

            def on_apply(e: ft.Event) -> None:
                try:
                    done = google_catalog.apply({k: (None if d.value == KEEP else d.value) for k, d in dropdowns.items()}, priced)
                    # 고른 모델이 없어 건너뛴 기능도 알려 준다(조용히 빠지지 않게)
                    done += [f"{repo.MODEL_SLOTS[k][0]}: 고른 모델이 없어 그대로 둠" for k, d in dropdowns.items() if not d.value]
                except ValueError as exc:
                    say(f"❌ {exc}", ok=False)
                    return
                found.clear()
                rebuild()
                page.show_dialog(ft.SnackBar(ft.Text("✅ 적용했습니다 — " + " / ".join(done))))

            result_box.controls = [
                ft.Text("추천 구성 (바꾸려면 목록에서 고르세요)", weight=ft.FontWeight.BOLD, size=fs(12, scale)),
                *rows,
                ft.Text("블로그 글·사진 분석은 비워 두면 기본 글쓰기 모델을 씁니다. 금액은 공식 가격표 기준 예상치이며, "
                        "무료 등급·할인은 반영하지 않습니다. 날짜가 정해진 가격 변경은 그날부터 자동으로 적용됩니다.",
                        size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
                ft.Row([ft.FilledButton("적용", icon=ft.Icons.CHECK, on_click=on_apply)]),
            ]
            _refresh(result_box)

        def on_fetch(e: ft.Event) -> None:
            typed = (key_field.value or "").strip() if key_field.visible else ""
            if not typed and not has_key:
                say("Google API 키를 먼저 붙여 넣으세요.", ok=False)
                return
            busy(True)
            say("⏳ 키 확인 → 모델 목록 → 공식 가격표를 불러오는 중…")

            def _work() -> None:
                try:
                    api_key = typed or decrypt_api_key(setting["encrypted_api_key"])
                    try:
                        available = google_catalog.list_available(api_key)
                    except Exception as exc:  # noqa: BLE001
                        say(f"❌ 키 확인 실패 — 키가 맞는지 확인하세요. ({str(exc)[:120]})", ok=False)
                        return
                    if typed:
                        repo.upsert_llm_setting("google", (setting or {}).get("model_name") or "", encrypt_api_key(typed))
                    try:
                        priced = google_catalog.parse_pricing(google_catalog.fetch_pricing_text())
                    except Exception as exc:  # noqa: BLE001
                        say(f"⚠️ 키는 정상입니다. 공식 가격표를 불러오지 못했습니다({str(exc)[:80]}). 인터넷 연결을 확인하고 잠시 뒤 "
                            "다시 시도하세요. 계속 안 되면 '⚙️ 고급 설정'에서 직접 입력하시거나 관리자에게 문의하세요.", ok=False)
                        return
                    problems = google_catalog.format_problems(priced, available)
                    if not priced:
                        say(google_catalog.FORMAT_MESSAGE, ok=False)
                        return
                    found.update(priced=priced, available=available)
                    if problems:   # 일부만 읽힘: 고를 수는 있게 두되, 단가가 빠질 수 있음을 알린다
                        say(google_catalog.FORMAT_MESSAGE + "\n(" + " ".join(problems) + " 키는 정상입니다.)", ok=False)
                    else:
                        say(f"✅ 키 정상 · 쓸 수 있는 모델 {len(available)}개 · 가격표 모델 {len(priced)}개를 읽었습니다.")
                    show_choices()
                finally:
                    busy(False)

            page.run_thread(_work)

        def on_refresh_prices(e: ft.Event) -> None:
            busy(True)
            say("⏳ 공식 가격표를 다시 불러오는 중…")

            def _work() -> None:
                try:
                    priced = google_catalog.parse_pricing(google_catalog.fetch_pricing_text())
                    if google_catalog.format_problems(priced):   # 형식이 바뀌었으면 지금 단가를 덮어쓰지 않는다
                        say(google_catalog.FORMAT_MESSAGE + " (지금 저장된 단가는 그대로 둡니다.)", ok=False)
                        return
                    n = google_catalog.refresh_registered(priced)
                    say(f"✅ 등록된 Google 모델 {n}개의 단가를 갱신했습니다." if n else "갱신할 Google 모델이 없습니다.", ok=bool(n))
                except Exception as exc:  # noqa: BLE001
                    say(f"❌ 가격표를 불러오지 못했습니다: {str(exc)[:120]}", ok=False)
                finally:
                    busy(False)

            page.run_thread(_work)

        fetch_btn = ft.FilledButton("키 확인하고 모델·가격 불러오기", icon=ft.Icons.CLOUD_DOWNLOAD, on_click=on_fetch)
        change_key.on_click = on_change_key
        if found:
            show_choices()
        return ft.Container(
            content=ft.Column([
                ft.Text("🚀 간편 설정 (Google 키 하나로)", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
                ft.Text("Google API 키만 넣으면 쓸 수 있는 모델과 공식 가격을 불러와 기능마다 추천합니다. [적용]을 누르면 끝입니다.",
                        size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
                ft.Row([ft.Text("✅ Google API 키 등록됨" if has_key else "🔑 Google API 키가 없습니다", size=fs(12, scale)),
                        change_key], spacing=8),
                key_field,
                ft.Row([fetch_btn, ft.OutlinedButton("단가만 다시 불러오기", icon=ft.Icons.REFRESH, on_click=on_refresh_prices),
                        spinner], spacing=8, wrap=True),
                ft.Text(current_summary(), size=fs(11, scale)),
                ft.Text(f"마지막으로 가격표를 불러온 날: {fetched}" if fetched else "아직 가격표를 불러온 적이 없습니다.",
                        size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
                status,
                result_box,
            ], spacing=8),
            border=ft.Border.all(1, "#14000000"), border_radius=8, padding=12, bgcolor="#F6F9F4",
        )

    def _body() -> ft.Control:
        slots = repo.get_slots()
        cards = [slot_card(slot, label, need, repo.get_model(slots[slot]["model_ref"]))
                 for slot, (label, need) in repo.MODEL_SLOTS.items()]
        advanced = ft.Column([
            ft.Text("기능마다 벤더·모델 이름·단가를 직접 입력합니다. Anthropic·OpenAI 모델을 쓰거나, 자동으로 읽은 단가를 고칠 때만 쓰세요. "
                    "단가를 비워 두면 '단가 미등록'입니다(0원 아님).",
                    size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
            *cards,
        ], spacing=10)
        return ft.Column([
            simple_panel(),
            *collapsible("⚙️ 고급 설정 (직접 입력 · 다른 벤더) ▸", advanced),
        ], spacing=10, scroll=ft.ScrollMode.AUTO)

    box.content = _body()
    return ft.Container(box, expand=True)
