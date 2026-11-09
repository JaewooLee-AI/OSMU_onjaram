# CLAUDE.md — 온자람 OSMU 개발 문서

주식회사 온자람(사회적기업, 창원) 전용 OSMU 앱입니다. 메모·사진 한 벌에서 블로그·카드뉴스·쇼츠를 만들고(당근은 2차)
온자람 브랜드 규칙으로 검수합니다. `OSMU_cjc`(블로그 중심)를 베이스로 하고 `ammasarang_card_shorts`의
카드·쇼츠 엔진을 서비스로 이식하는 중입니다. 전체 설계는 `docs/설계안_온자람_OSMU_v0.1.md`.

## 반드시 지킬 것

1. **공개 저장소입니다.** API 키·`.master_key`·`.osmu` 전송 파일·DB(`data/`)·내담자 정보·네이버 로그인 세션·
   실제 업로드 사진은 어떤 파일에도 쓰거나 커밋하지 않습니다. 회사 원본 문서는 `info/`(gitignore)에만 둡니다.
2. **API 키는 하드코딩하지 않습니다.** 앱 ⚙️ 설정에서 사용자가 입력하고 AES-256-GCM으로 암호화해 DB에 저장합니다.
3. **`git commit`·`push`는 사용자가 요청할 때만 합니다.** `main` push는 고객용 Release 자동 게시를 일으킵니다.
4. **사실을 지어내지 않습니다.** 브랜드 킷의 팩트·가격·인증 수치는 `info/` 문서와 사용자가 알려준 것만 씁니다.
   문서에 없는 값(홈페이지·블로그 ID·동읍 거점 번지 등)은 비워 두고 사용자에게 묻습니다.
5. **심리상담 윤리.** 개별 내담자 사례(나이·시기·상황)를 콘텐츠에 쓰지 않고 보편 심리교육 내용으로 바꿉니다.
   치료·완치·효과 보장 표현과 낙인·공포 표현은 금지(`core/brand_seed.py` BLACKLIST_MAP, `ai_workers/guardrail.py`).
   법률 기준은 실서비스 전 법무 검토가 필요합니다.
6. **무료 라이선스 폰트만** 동봉합니다(OFL 고지 파일 포함). 라이선스를 확인하지 못한 폰트는 넣지 않습니다.
7. 실제 LLM 호출·Windows 전용 동작·네이버 게시는 클라우드에서 검증하지 않고 "로컬 검증 필요"로 남깁니다.

## 실행·시험

```bash
pip install -r requirements.txt
python flet_app/main.py
python -m pytest tests          # LLM·실제 데이터 폴더를 쓰지 않음
```

데이터 폴더: 소스 실행 시 저장소 루트 `data/`가 있으면 그것, 아니면 `%APPDATA%\OSMU_ONJARAM`(Windows)
(`core/db.py`의 `_default_data_dir`, `.env`의 `OSMU_DATA_DIR`이 우선). 설치 폴더에는 쓰지 않습니다.

## 구조

`flet_app/`(UI) · `core/`(SQLite·repo·암호화·`brand_seed`·`transfer` 📦 데이터 옮기기) · `ai_workers/`(생성 파이프라인·LLM 라우터·가드레일) ·
`tests/` · `docs/`(설계·계획) · `installer/`(Inno Setup) · `.github/workflows/`(Windows 빌드).

## 진행 상태 (설계안 §13)

- **M0 완료**: cjc 복사, 캘린더·자동 작성·뉴스 큐레이션·X(트위터) 채널 제거, 브랜드 킷을 온자람 2트랙(공감·회복 / 전문·신뢰)으로 시드,
  가드레일 감사 프롬프트를 상담 기준으로 교체, 앱 아이콘·식별자(AppId 새로 발급)·데이터 폴더 이름 변경.
  남은 잔재: 일부 코드 주석의 가발/키노피스 예시, `ai_workers/sns_validator.py`의 쓰지 않는 트윗 검증 함수, 멀티 킷 UI(두 킷을 보이스 트랙으로 사용 중).
- **M1 완료(코드·시험)**: `model_registry`·`model_slots`(core/db.py), `repo.upsert_model/set_slot/resolve_slot_model/media_cost_usd`, 라우터가 슬롯의 모델을 사용(`text`·`text_blog`·`vision`, 블로그 파이프라인은 `text_blog`), 이미지·영상·음성 단가와 `usage_log.media_seconds`, 📦 데이터 옮기기 `models` 항목, 설정 → 🤖 모델 등록 탭. 모델 이름은 `core/model_seed.py`의 편집 가능한 예시일 뿐이며 코드에 박지 않습니다(남은 예외: 임베딩 모델 이름).
- **M2 완료**: `cards/` 패키지(card_shorts 렌더러 이식, 무료 OFL 글꼴 Pretendard·Gmarket Sans 동봉), 3단(`tri`) 레이아웃(`cards/layout_tri.py`, 비율 `ratio`·밝은/어두운), 카드 종류 팩 8종(`cards/types/*.json`, 사용자 팩은 데이터 폴더 `card_types/`), 기획기(`cards/director.py`: AI→규칙 기반 대체, 금기어 치환, 숫자 팩트 락 경고, CTA 연락처 고정), 워크벤치 🃏 카드뉴스 탭(`flet_app/views/card_studio.py`: 기획·카드별 편집·전체/한 장 다시 그리기), 설정 🃏 카드 종류·디자인 탭(복제·수정·JSON 가져오기/내보내기), `company_profile`에 전화·이메일·주소, `campaigns.card_storyboard`.
  글꼴: Pretendard·Gmarket Sans·고운바탕(세리프)을 OFL 라이선스 원문(`cards/fonts/OFL-*.txt`)과 함께 동봉합니다. 마루부리·Noto Serif KR은 라이선스 원문 확인 전이라 동봉하지 않았습니다(Noto Serif KR은 23MB라 사용자가 데이터 폴더 `fonts/custom`에 넣는 방식). 새 글꼴은 OFL 원문 파일이 있어야 하며 시험이 확인합니다.
  남은 것: 새 슬라이드 모양이 필요하면 `card_types.VALID_ARCHETYPES`와 렌더러에 같이 등록.
- **M3 완료(코드·시험)**: `cards/images.py` — 이미지 모드 3가지(내 사진만 / 내 사진 우선+부족분 AI / AI 우선), 사진 칸은 표지·본문·한 장·인용 카드만(번호·안내·표 카드는 인포그래픽이라 AI 이미지 0), 카드별 수동 선택·'사진 없음'(`asset_locked`)은 자동 배치·AI가 건드리지 않음, 실행 전 예상 비용(`estimate`: 이미지 생성 슬롯 모델의 등록 단가, 미등록이면 '단가 미등록'), 확인 창 후 생성, 장마다 `log_usage(kind='image')`. AI 프롬프트에는 실존 인물·글자 금지 규칙을 항상 붙임. 카드뉴스 탭에 사진 올리기·이미지 모드·카드별 사진 선택·AI 이미지 만들기.
  **로컬 검증 필요**: 실제 Gemini 이미지 호출(`_generate_gemini`)과 생성 이미지 품질·가격, 사진 올리기(FilePicker)는 Windows에서 직접 확인. 이미지 모델은 Google만 지원(다른 벤더 모델을 슬롯에 지정하면 안내 후 중단).
- **M4 완료(코드·시험)**: `cards/shorts_script.py`(카드→쇼츠 대본: 규칙 기반/AI, 숫자 팩트 락·금기어, 상담 안내 장면은 브랜드 킷 값 고정, 카드가 바뀌면 `is_stale`), `cards/tts.py`(음성 슬롯 모델 Gemini TTS, 캐시, 호출마다 `log_usage(kind='tts', seconds=…)`), `cards/shorts_renderer.py`(형제 렌더러 이식 + **3단 프레임 모드**: 카드와 같은 템플릿을 1080x1920·위아래 250px 안전 여백으로 그려 이어 붙임, 키네틱 모드는 코드만 이식), `cards/ffmpeg_tools.py`(FFmpeg 위치 탐색, H.264 인코더 libx264→libopenh264→h264_mf 선택), 워크벤치 🎬 쇼츠 영상 탭(대본 편집·음성 예상 비용·확인 창). 음성 모델이 없거나 실패하면 무료 gTTS→무음으로 대체하고 경고를 남김.
  **로컬 검증 필요**: 실제 Gemini TTS 호출·음질, Windows 설치본의 FFmpeg 동봉(워크플로 `Bundle FFmpeg`는 CI에서 아직 실행 안 함, docs/FFMPEG_동봉.md), 키네틱 모드의 화면·글꼴, 휴대폰 재생. **미이식**: AI 영상(Omni) — 영상 슬롯·단가 등록은 있으나 호출 코드는 없음, 업로드 영상 클립 사용(3단 모드는 정지 프레임).
- **M5 완료(코드·시험)**: 네이버 키워드 측정은 선택 기능 — `app_settings.naver_keywords_enabled`(기본 꺼짐), 꺼져 있으면 `_request`·`_searchad_request`가 네트워크 전에 `NaverDisabled`로 멈춤(연결 테스트는 예외), `keyword_research.level()`(0 없음/1 API HUB/2 +검색광고), `seo_optimizer._opportunity`는 검색량→검색 추이→문서 수만 순으로 부분 점수(경쟁도를 모르면 0), 설정 → 🔍 네이버 API 탭 스위치(꺼지면 키 입력·마법사 숨김), `core/setup_check.py` + 대시보드 '시작 점검' 패널(필수: AI 키·글쓰기 모델·대표 전화 / 선택: 이미지·음성·FFmpeg·네이버). 키 일괄 배포는 기존 📦 데이터 옮기기로. 주의: 이 앱이 쓰는 레벨 1 API는 NCP API HUB(개발자센터 오픈 API 아님).
- **선택 생성(추가)**: 워크벤치 [이번에 만들 것] — 블로그·카드뉴스·쇼츠를 글마다 골라 만듭니다(`flet_app/outputs.py`; 기본값은 설정 → 📣 생성 채널의 '기본 생성 대상'). 쇼츠는 카드 기준 대본 한 가지로 통일(예전 컷 자막 생성은 끔), 쇼츠만 고르면 카드는 이미지 없이 기획만, 영상 렌더·AI 이미지는 비용 확인을 거쳐 각 탭에서. 쇼츠 3단 모드는 [사진 움직임](확대·축소·번갈아, 가운데 사진 칸만 — `ShortsOptions.photo_motion`)을 고를 수 있음(AI 영상 Omni는 여전히 미이식). 카드 1장 옵션 = 카드 종류 `one_card`(한 장 카드). 기본 팩 목록·미리보기(`cards/preview.py`), 서비스·신청 정보 시트(`ai_workers/factsheet.py` PRODUCT, 키는 예전 그대로).
- **화면 구조 개편**: 사이드바에 🃏 카드·쇼츠 스튜디오(`flet_app/views/studio_view.py`)를 따로 둠 — 왼쪽 큰 미리보기·넘겨보기·저장, 오른쪽 ①카드 만들기(종류·디자인만 고르고 한 번) ②한 장 다듬기·적용(그 카드만 다시 그림) ③쇼츠. 긴 작업은 진행 창, 그린 뒤 바뀐 카드는 '다시 그리기' 안내(`card_studio.stale_cards`). 워크벤치는 글을 다 쓰면 결과를 맨 위에, 메모·설정은 접어 둠. 예전 `card_studio.build_card_tab`·`shorts_studio.build_shorts_tab` 화면은 더 이상 쓰이지 않고 로직 함수만 재사용.
- **브랜드 배색**: `design_templates.BRAND_PALETTES` 5종(세이지·네이비·코랄·오트·투톤 — 브랜드 컬러로만 구성, 어두운 파생색 표시)을 어떤 디자인에든 "디자인@배색" id로 입힘(스튜디오 '배색', 설정 미리보기). 내장 gov·color_block·poster 기본색도 브랜드 색으로 교체. 카드별 색·글자 크기는 `CardSlide.style`(말로 고치기).
- **카드 글자 가독성 정비**: 카드(1080px)는 휴대폰에서 폭 약 1/3로 보이므로 `cards/fonts.py`의 `legible_size`가 작은 글자일수록 더 키움(21→28px 등, 큰 글자는 그대로)하고, 본문·목록·표 시작 크기를 올리고(맞춤 반복문이 넘치면 줄임), 제목 시작 크기를 올림. 3단 디자인에서도 행사 안내·비교표를 같은 3단 모양으로 그림. 휴대폰 크기(폭 270px)로 줄여 읽히는지 보는 것이 점검 기준.
- **카드 크기**: 폭 1080 고정, 높이는 `EditableStoryboard.aspect`(4:5=1350 기본 · 3:4=1440 · 9:16=1920 · 1:1=1080, `cards/schema.CARD_ASPECTS`)로 고름. 3단 디자인만 높이를 바꾸고(다른 디자인은 좌표가 4:5 고정) 쇼츠 3단 프레임은 따르지 않음(`FOLLOW_ASPECT=False`). 사진 칸 수는 디자인·종류마다 달라 스튜디오가 미리 안내.
- **데이터 옮기기에 '작업 내용' 추가**(`core/transfer.py` part `work`): 글(본문·서식·카드·쇼츠 대본·게시 기록)·올린 사진·사진 분석 결과·카드 그림(AI 이미지 포함)·쇼츠 영상을 .osmu 한 파일에 담음(파일은 base64, 크기는 화면에 표시). 가져올 때는 받는 PC에 **없는 글만** 더하고 같은 id의 글은 그대로 둠, 파일 경로는 받는 PC 데이터 폴더 기준으로 고치고, 브랜드 킷은 이름으로 이음. 'PC를 통째로 바꿀 때 데이터 폴더를 복사하세요' 안내는 없앰.
- **📚 보관함**(`flet_app/views/library_view.py`, `core/library.py`): 검색(제목·메모·본문)·필터(상태·보관·킷·라벨·내용)·정렬·20개씩 쪽 나누기, 한 줄에서 워크벤치/카드·쇼츠/네이버 글 이동, 보관(`campaigns.archived`, 삭제 아님)·라벨(`campaigns.labels`)·용량 정리(카드 PNG·쇼츠 영상 파일만 — AI 이미지·사진·글은 지우지 않음)·게시 후 30일 지난 글 일괄 보관. 워크벤치·스튜디오 글 선택은 최근 15개(+열려 있는 글)만, 나머지는 보관함. 대시보드·작업 목록은 보관한 글을 숨김.
- **글 유형(블로그 고도화 1순위)**: 공개 블로그 RSS 50개 글 분석 결과를 `ai_workers/post_types.py`로 옮김 — 현장 후기·칼럼·모집·안내 3종(글마다 선택, `campaigns.post_type`, 비우면 예전 동작). 고정 인사·번호 소제목 구조·제목 말머리 지시, 발행 전 문의 푸터(킷 전화·주소만) 자동 삽입, 참여자 소감 효과 단정 금지·프로그램 이름 은유 안전 규칙(가드레일 감사 프롬프트에도 반영), 발행 태그 4층 구성·'예비사회적기업' 제거, 시드 블로그 ID `onjaram`. **로컬 검증 필요**: 실제 LLM이 틀(인사·소제목)을 지키는지. 
- **블로그 고도화 2·3순위**: `core/blog_feed.py`(공개 RSS 가져오기·저장, 로그인 불필요 — 중복 주제 `related`, 태그 사전, 발행 공백, 낡은 안내·소개글), `core/blog_insight.py`(시즌 주제 제안; 긴 꼬리 후보·측정 함수는 있으나 화면에서는 안 씀), 대시보드 📰 패널(`flet_app/views/blog_panel.py`; 키워드 조사는 여기 두지 않고 설정 → 네이버 API로 일원화, 시즌 주제 [글 만들기]는 메모·글 유형이 채워진 새 글로 이동), `ai_workers/consent.py`(현장 후기+사진이면 게시 화면에서 동의 3항목을 체크해야 [게시] 활성, `campaigns.consent`), 생성 보고에 비슷한 기존 글·사람 보이는 사진 수 표시, 글 유형→카드 시리즈 이름(`BrandElements.series_label`: 온자람 현장/마음노트/소식)·기본 카드 종류. 태그 생성에 예전 태그 사전 반영. **로컬 검증 필요**: 실제 RSS 가져오기 버튼(네트워크), 키워드 측정(네이버 키 필요), 게시 화면 체크박스 동작. 시즌 주제는 제안일 뿐 사실(날짜·기관)은 담지 않음.
- **모델 간편 설정(Google)**: 설정 → 🤖 모델 등록 맨 위 '간편 설정' — Google 키만 넣으면 `core/google_catalog.py`가 키로 쓸 수 있는 모델(models.list)과 공식 가격표(`ai.google.dev/gemini-api/docs/pricing`, 로그인 없이 마크다운)를 읽어 글쓰기·이미지·음성 슬롯을 규칙으로 추천(정식 최신 Flash 우선, 종료 예정 모델 제외, 이미 쓰는 모델은 유지) → [적용]. 날짜가 정해진 단가 변경은 모델 옵션 `price_schedule`에 두고 앱 시작 때 `apply_due_prices`가 적용. 가격표를 못 읽으면 값을 지어내지 않고 '단가 미등록'. 예전 입력 화면은 '고급 설정'으로 접음(Anthropic·OpenAI는 거기서). 금액은 Standard 유료 단가 기준 예상치.
- **블로그 AI 이미지(선택)**: 워크벤치 사진 영역 [🎨 사진 자리를 AI 이미지로 채우기] — '사진 자리' 설명으로 이미지 생성(최대 4장, 비용 확인 창), `[IMAGE:]`로 삽입하고 사진 설명에 '(AI로 만든 이미지)'를 붙임(`ai_workers/blog_images.py`). **로컬 검증 필요**: 실제 이미지 호출.
- **쇼츠 카드 모드 여백 채우기**: 카드가 9:16보다 짧으면 위 띠에 회사 이름·한 줄 소개, 아래 띠에 장면 자막·상담 연락처(`_fill_margins`).
- **카드 내용 채우기·에디토리얼 디자인**: 3단 디자인이 사진 위에 본문 첫 줄만 보이던 것을 본문 전체(그라데이션 위 흰 글자)로, 소속·연락처는 표지·마지막 카드만(가운데는 쪽 번호), 안내 카드는 라벨 줄. 공감형 팩에 '마음의 신호' 체크 카드 추가(진단 표현 금지). 새 디자인 `editorial`(`cards/layout_editorial.py`, layout `ed`) — Stitch 시안 1안(`docs/design/stitch_시안1_카드뉴스.jpg`)의 머리줄·코랄 머리말·흰 칸 목록·요약 띠를 옮김(시안 속 문구는 지어낸 것이라 쓰지 않음), 카드 비율을 따름. 카드 종류 팩 9종의 기본 디자인과 `DEFAULT_ID`를 editorial로 바꿈(이미 기획한 글·사용자 팩은 그대로).
- **에디토리얼 계열 확장**: 변형 `editorial-dark`(진초록 바탕)·`editorial-serif`(제목 고운바탕)·`editorial-photo`(큰 사진, 본문 자리 먼저 확보) — `DesignTemplate.variant`. 배색(@navy 등)도 그대로 적용. 쇼츠는 에디토리얼이면 카드를 9:16으로 직접 그림(위 120·아래 240px UI 가림 영역 비움, `ShortsRendererService.ED_SAFE_*`, 높이에 맞춰 글자·칸을 최대 1.25배). 그 밖의 내장 디자인은 이름 앞 '(이전)'으로 목록 뒤에(지우지 않음, `design_templates.is_legacy`).
- 다음: 통합 점검(실제 앱 화면·Windows 빌드), 당근 채널(2차), 뉴스 큐레이션(2차).
