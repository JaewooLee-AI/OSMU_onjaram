"""주식회사 온자람 브랜드 킷 시드 — 첫 실행 때 한 번만 DB에 들어가는 기본값.

값은 지어낸 것이 아니라 `info/온자람 OSMU 브랜드킷 분석.docx`(회사 문서)와 사용자가 알려준 값에서
옮긴 것입니다. 문서에 없는 값(홈페이지·블로그 ID·인스타그램·동읍 거점 번지 등)은 비워 두고,
⚙️ 설정과 🧵 브랜드 킷 화면에서 담당자가 채웁니다. 이 저장소는 공개이므로 개인 연락처·대표자 개인정보·
내담자 사례는 넣지 않습니다(사업자 공개 정보만).

보이스 트랙(문서 §2.1)은 킷 두 개로 둡니다.
- 트랙 A 「공감·회복」: B2C 개인 내담자·지역 주민용 (카드뉴스·쇼츠·블로그 공감 칼럼)
- 트랙 B 「전문·신뢰」: 기업 EAP·학교·관공서·기관용 (블로그 전문 정보글)
글마다 어느 킷으로 쓸지 고르는 기존 구조를 그대로 씁니다.

컴플라이언스: 심리상담 기관의 위험은 치료·완치 약속(의료법 제56조, 표시·광고의 공정화에 관한 법률)과
낙인·공포를 주는 표현입니다. 금기어 사전(BLACKLIST_MAP)과 감사 프롬프트(ai_workers/guardrail.py)가
이 기준입니다. 법률 기준은 실서비스 전 법무 검토가 필요합니다.

`seed_if_empty()`는 DB가 비어 있을 때 첫 실행에서 한 번만 킷과 회사 공통 값을 채웁니다. 그 뒤로는
🧵 브랜드 킷 화면이 원본이며 이 파일은 다시 적용되지 않으므로, 관리자가 고친 내용을 덮어쓰지 않습니다.
이미 저장된 문구를 한 번만 고쳐야 할 때는 SEED_FIXES를 씁니다.
"""
from __future__ import annotations

from core import repo

# --- visual identity --------------------------------------------------------
# 문서 §3 비주얼 토큰. Flet 테마(flet_app/theme.py)가 이 값을 그대로 씁니다.
BRAND_COLORS = {
    "primary": "#4A7C59",      # 세이지 그린 — 자람·회복 (B2C 주조색)
    "primary_dark": "#35593F", # 세이지 그린을 어둡게 한 파생색(문서에 없는 값 — 필요하면 조정)
    "secondary": "#2C4A6F",    # 트러스트 네이비 — 전문·신뢰 (B2B/B2G 주조색)
    "accent": "#E07A5F",       # 마인드 코랄 — 온기·CTA
    "mint": "#F0ECE1",         # 소프트 오트 — 보조 배경(키 이름은 기존 코드 호환용)
    "bg": "#FAF8F5",           # 웜 크림 — 기본 배경
    "text": "#2B2D2F",         # 차콜 — 본문
    "text_muted": "#6E7378",   # 뮤트 그레이 — 캡션
}

BRAND_NAME = "주식회사 온자람"
SUB_BRAND = "온자람심리상담센터"
HOMEPAGE = ""
NAVER_BLOG_ID = "onjaram"   # 공개 블로그 주소 blog.naver.com/onjaram
INSTAGRAM_HANDLE = ""
PHONE = "055-255-1365"
EMAIL = "onjaram@naver.com"
ADDRESS = "경남 창원시 성산구 반송로82번길 29, 1층"
INDUSTRY = "심리상담·정신재활 · 근로자지원프로그램(EAP) · 정신건강·감정관리 교육 (사회적기업)"

SLOGAN_MAIN = "온전한 나를 찾는 여정에 함께하는 마음성장파트너"
SLOGAN_SUB = "당신의 마음이 쉬어가는 곳"

# --- 트랙 A: 공감·회복 -----------------------------------------------------

PERSONA = (
    "당신의 마음이 쉬어가는 곳, 마음성장파트너 온자람 전문 상담진의 목소리로 이야기합니다. "
    "독자가 겪는 정서적 고통을 특별하지 않은 보편적 경험으로 받아들이며(정상화), 판단하거나 훈계하지 않습니다. "
    "개별 내담자 사례는 쓰지 않고, 누구에게나 도움이 되는 심리교육 내용으로 풀어 씁니다. "
    "치료나 완치를 약속하는 표현은 쓰지 않고, 혼자 해결하기 어려운 마음의 문제는 상담이라는 안전한 선택지가 있다고 부드럽게 안내합니다."
)

TONE_AND_MANNER = """- 수용적·공감적인 어조로, 호흡이 짧고 따뜻한 구어체 종결어미(~해요, ~인가요?, ~괜찮습니다)를 씁니다.
- 한 문장은 40자 안팎에서 끊고, 한 문단은 2~3문장까지만 씁니다. 같은 뜻을 두 번 말하지 않습니다.
- 독자가 겪는 일상의 마음 고충에 공감하는 서론으로 시작하고, 그 감정이 이상한 것이 아님을 알려 줍니다.
- 브랜드 어휘를 자연스럽게 사용합니다: 온전한 나, 마음성장파트너, 마음이 쉬어가는 곳, 회복의 여정, 감정 돌봄, 안전한 공간, 작은 용기.
- 낙인이나 공포를 주는 표현(정신병, 문제아, 방치하면 큰일 납니다, 무조건 고쳐드립니다, 중증 환자 등)을 쓰지 않습니다.
- 치료·완치·효과 보장을 약속하거나 암시하는 표현을 쓰지 않습니다.
- 개별 내담자의 나이·시기·상황이 드러나는 사례를 쓰지 않고, 보편적인 심리교육 내용으로 바꿔 씁니다.
- 수치·가격·인증은 팩트 목록에 있는 것만 씁니다.
- 글 주제가 상담·예약과 직접 이어질 때에만 글 끝에 부드러운 안내 한 문장을 남깁니다."""

CORE_FACTS = [
    "주식회사 온자람(부설기관 온자람심리상담센터)은 경상남도 창원시를 거점으로 심리상담·정신재활 서비스, 근로자지원프로그램(EAP), 정신건강·감정관리 교육을 제공하는 인증 사회적기업(제2025-139호)입니다.",
    "브랜드 이름 '온자람'은 결핍이나 왜곡 없이 본연의 모습을 회복한다는 '온전한 나'와, 끊임없이 자라난다는 '자람'이 합쳐진 말입니다.",
    "내담자를 치료받아야 할 환자로 대상화하지 않고, 우울·불안·스트레스 등 마음의 문제를 회복하고 자신을 깊이 이해하도록 동행하는 '마음성장파트너'를 지향합니다.",
    "메인 슬로건은 '온전한 나를 찾는 여정에 함께하는 마음성장파트너', 서브 슬로건은 '당신의 마음이 쉬어가는 곳'과 '혼자 해결하기 어려운 마음의 문제 상담소'입니다.",
    "심리상담은 1회 50분 80,000원이며 청년·5회기 등록 등 할인 혜택이 있고, 평균 15회기로 진행됩니다.",
    "상담 절차는 네이버 예약 또는 전화 문의 후 상담사 배정 → 첫 상담 진행 후 계약 여부 논의 → 개인 맞춤형 회기 진행 순서입니다.",
    "교육 서비스는 자체교육이 1회기 1인 50,000원이고, 기관 출장교육은 강사비 규정에 따라 협의합니다.",
    "근로자지원프로그램(EAP)은 임직원 심리검사·분석보고서·개인상담·조직교육으로 구성되며 가격은 협의합니다.",
    "성산구 거점은 경남 창원시 성산구 반송로82번길 29, 1층이고(원이대로 716 대동메디칼 6층에도 거점이 있습니다), 의창구 동읍 거점은 주남로71번길에 있습니다.",
    "대표전화는 055-255-1365, 이메일은 onjaram@naver.com이며 예약은 네이버 예약으로 받습니다.",
    "경상남도창원교육지원청(Wee센터), 마산동부·중부경찰서, 의령경찰서, 창원중독관리통합지원센터, 굿네이버스(해외아동 1:1 결연 후원), 창원시사회적경제지원센터 등과 지역사회 협력 네트워크를 맺고 있습니다.",
]

TERMINOLOGY = {
    "온자람": "주식회사 온자람. 사회적기업 인증 제2025-139호. 상호는 '온자람'으로 붙여 씁니다.",
    "온자람심리상담센터": "주식회사 온자람의 부설기관. 붙여 씁니다.",
    "마음성장파트너": "브랜드 페르소나. 내담자를 환자로 대상화하지 않고 성장 여정에 동행한다는 뜻입니다. 붙여 씁니다.",
    "온전한 나": "결핍이나 왜곡 없이 본연의 모습을 회복한다는 브랜드 핵심 어휘.",
    "회복의 여정": "치료나 완치가 아니라 스스로 회복해 가는 과정을 뜻합니다.",
    "감정 돌봄": "감정을 억누르지 않고 살피는 일. '감정 관리'보다 부드러운 표현으로 씁니다.",
    "안전한 공간": "판단받지 않고 이야기할 수 있는 상담 공간을 뜻합니다.",
    "근로자지원프로그램(EAP)": "임직원 심리검사·분석보고서·개인상담·조직교육. 처음에는 '근로자지원프로그램(EAP)'으로 풀어 쓰고 이후 'EAP'로 줄일 수 있습니다.",
    "마음약국·감정쓰레기통·힐링 썬캐처": "온자람 체험 프로그램 이름(고유명사). 이름일 뿐이며 실제 약·처방·치료를 뜻하지 않습니다. 효과를 말하지 않고 체험 소감만 씁니다.",
    "심리상담": "'치료'라고 쓰지 않습니다. 상담은 마음을 돌보고 회복을 돕는 과정으로 서술합니다.",
    "정신재활": "정신건강 문제를 가진 분의 일상·사회 복귀를 돕는 서비스. 낙인 없이 '마음의 회복'과 함께 씁니다.",
}

# 문서 §4.1·§4.4의 지역 거점 × 타깃·증상 × 솔루션 키워드 규칙에서 옮긴 시드 키워드.
SEO_KEYWORDS = [
    "창원 성산구 심리상담",
    "창원 청년 우울 불안 상담",
    "창원 기업 EAP 직무스트레스 검사",
    "창원 동읍 심리상담센터",
    "동읍 아동청소년 심리상담",
    "의창구 학부모 양육 상담",
    "창원 심리상담",
    "온자람",
]

# --- 트랙 B: 전문·신뢰 -----------------------------------------------------

TRACK_B_PERSONA = (
    "생애주기별 정신재활 및 조직 심리 솔루션 전문 사회적기업 (주)온자람의 목소리로 이야기합니다. "
    "기업 인사담당자·학교·관공서·복지기관 담당자에게 심리학적·임상적 근거와 체계적인 진행 과정을 "
    "단정하고 명확한 문어체(~합니다, ~제공합니다, ~지원합니다)로 설명합니다. "
    "치료나 효과를 보장하는 표현은 쓰지 않고, 확인된 서비스 구성과 지역사회 협력 실적만 근거로 삼습니다."
)

TRACK_B_TONE = """- 단정하고 명확한 문어체(~합니다, ~제공합니다, ~지원합니다)를 씁니다.
- 한 문장은 50자 안팎에서 끊고, 한 문단은 2~3문장까지만 씁니다.
- 프로세스의 완결성을 강조합니다. 예: 직무스트레스·정신건강·성격특성 검사 → 정량적·체계적 분석보고서 → 개인상담·조직교육.
- 전문 어휘를 사용합니다: 생애주기 맞춤형, 근로자지원프로그램(EAP), 직무스트레스 진단 및 분석보고서, 정신재활 서비스, 감정조절 및 스트레스 관리, 지역사회 정신건강 안전망, 사회적 가치 환원.
- 협력 기관·인증·가격은 팩트 목록에 있는 것만 씁니다. 기관 이름을 과장하거나 추정해서 쓰지 않습니다.
- 치료·완치·효과 보장을 약속하거나 암시하는 표현을 쓰지 않습니다.
- 개별 내담자나 개별 기관의 비공개 정보를 쓰지 않습니다.
- 글 끝에는 문의 방법(전화·이메일·네이버 예약)을 담백하게 안내합니다."""

TRACK_B_SEO = [
    "창원 기업 EAP 직무스트레스 검사",
    "창원 EAP 근로자지원프로그램",
    "창원 기관 출장교육 정신건강",
    "창원 성산구 심리상담",
    "창원 동읍 심리상담센터",
    "온자람",
]

KIT_PRESETS = {
    "track_a": {
        "name": "공감·회복 (B2C)",
        "label": "개인 내담자·지역 주민용 — 카드뉴스·쇼츠·블로그 공감 칼럼",
        "default_name": "공감·회복 (B2C)",
        "industry": INDUSTRY,
        "persona": PERSONA,
        "tone_and_manner": TONE_AND_MANNER,
        "core_facts": CORE_FACTS,
        "terminology": TERMINOLOGY,
        "seo_keywords": SEO_KEYWORDS,
        "non_target_keywords": ["온자람"],
        "few_shot_samples": [],
    },
    "track_b": {
        "name": "전문·신뢰 (B2B·B2G)",
        "label": "기업 EAP·학교·관공서·기관용 — 블로그 전문 정보글",
        "default_name": "전문·신뢰 (B2B·B2G)",
        "industry": "근로자지원프로그램(EAP)·기관 출장교육·정신재활 (사회적기업)",
        "persona": TRACK_B_PERSONA,
        "tone_and_manner": TRACK_B_TONE,
        "core_facts": CORE_FACTS,
        "terminology": TERMINOLOGY,
        "seo_keywords": TRACK_B_SEO,
        "non_target_keywords": ["온자람"],
        "few_shot_samples": [],
    },
}

# 낙인·공포 표현과 치료·효과 보장 표현을 결정론적으로 치환하는 사전(문서 §2.1의 금칙 어휘 +
# 의료법 제56조·표시광고법 기준). 여기 등록된 표현은 LLM이 무엇을 쓰든 발행 전 자동 치환됩니다.
# 치환 문구는 초안입니다 — 담당자가 🧵 브랜드 킷 화면에서 고칠 수 있습니다.
# (긴 항목이 먼저 매칭되도록 하는 처리는 ai_workers/guardrail.py에 있습니다.)
BLACKLIST_MAP = {
    "방치하면 큰일 납니다": "마음을 일찍 살피면 도움이 됩니다",
    "무조건 고쳐드립니다": "회복의 여정에 함께합니다",
    "정신병": "마음의 어려움",
    "문제아": "마음이 힘든 아이",
    "중증 환자": "깊은 어려움을 겪는 분",
    "완치 보장": "회복을 돕는 과정",
    "완치": "회복",
    "100% 치료": "회복을 돕는 과정",
    "치료 효과 보장": "회복을 돕는 과정",
    "치료 보장": "회복을 돕는 과정",
    "부작용 제로": "안전한 상담 환경",
}

FEW_SHOT_SAMPLES: list = []


def seed_if_empty() -> bool:
    """Populates the default kit (트랙 A), the 트랙 B kit and the company profile on first
    launch only. Returns True if seeded."""
    existing = repo.get_brand_kit()
    if existing.get("brand_name") or existing.get("persona"):
        return False

    repo.save_brand_kit(
        existing.get("id"),
        name=KIT_PRESETS["track_a"]["name"],
        brand_name=BRAND_NAME,
        sub_brand=SUB_BRAND,
        industry=INDUSTRY,
        homepage=HOMEPAGE,
        naver_blog_id=NAVER_BLOG_ID,
        instagram_handle=INSTAGRAM_HANDLE,
        phone=PHONE,
        email=EMAIL,
        address=ADDRESS,
        persona=PERSONA,
        tone_and_manner=TONE_AND_MANNER,
        core_facts=CORE_FACTS,
        terminology=TERMINOLOGY,
        seo_keywords=SEO_KEYWORDS,
        non_target_keywords=["온자람"],
        blacklist_map=BLACKLIST_MAP,
        few_shot_samples=FEW_SHOT_SAMPLES,
        guardrail_enabled=True,
        vision_enabled=True,
        vision_quality="economy",
    )
    repo.create_brand_kit(KIT_PRESETS["track_b"]["name"], copy_from=existing.get("id"), preset_key="track_b")
    return True


# One-time corrections to text an earlier version of this file seeded into
# existing Brand Kits. seed_if_empty() never touches a kit that already
# exists, so a fix to a seeded default would otherwise reach new installs
# only. Each (old, new) pair is applied once, and only where `old` is still
# present verbatim — i.e. the admin never edited that line — so admin edits
# are still never clobbered.
SEED_FIXES: list = []
_OBSOLETE_FACT_LINE = "__none__"
_SEED_FIXES_STATE_KEY = "brand_seed_fixes_applied"

# Same idea for the banned-term dictionary: entries added to BLACKLIST_MAP
# after a kit was seeded. Each key is added once, and only if the admin's
# dictionary doesn't already have it — an existing entry (with whatever
# replacement the admin chose) always wins.
SEED_BLACKLIST_ADDITIONS = {}


def apply_seed_fixes() -> int:
    """Applies SEED_FIXES to every kit's saved tone guide (보관된 킷 포함 — 되살렸을
    때 예전 문구가 돌아오면 안 되므로), removes obsolete mixed-keyword lines from
    core_facts, and applies SEED_BLACKLIST_ADDITIONS to the shared dictionary.
    Returns how many changes were made."""
    done = set((repo.get_app_state(_SEED_FIXES_STATE_KEY) or {}).get("done") or [])
    pending = [(old, new) for old, new in SEED_FIXES if old not in done]
    fact_marker = f"fact_remove:{_OBSOLETE_FACT_LINE}"
    remove_fact = fact_marker not in done
    applied = 0
    for kit in repo.list_brand_kits(include_archived=True):
        tone = kit.get("tone_and_manner") or ""
        changed = 0
        for old, new in pending:
            if old in tone:
                tone = tone.replace(old, new)
                changed += 1
        updates = {}
        if changed:
            updates["tone_and_manner"] = tone
            applied += changed
        if remove_fact:
            facts = list(kit.get("core_facts") or [])
            if _OBSOLETE_FACT_LINE in facts:
                updates["core_facts"] = [f for f in facts if f != _OBSOLETE_FACT_LINE]
                applied += 1
        if updates:
            repo.save_brand_kit(kit["id"], **updates)
    done.update(old for old, _ in pending)
    done.add(fact_marker)

    blacklist = dict(repo.get_company_profile().get("blacklist_map") or {})
    added = 0
    for term, replacement in SEED_BLACKLIST_ADDITIONS.items():
        marker = f"blacklist:{term}"
        if marker in done:
            continue
        if term not in blacklist:
            blacklist[term] = replacement
            added += 1
        done.add(marker)
    if added:
        repo.save_company_profile(blacklist_map=blacklist)

    repo.set_app_state(_SEED_FIXES_STATE_KEY, {"done": sorted(done)})
    return applied + added
