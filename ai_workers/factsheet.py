"""글이 담아야 하는데 메모에는 없는 사실들.

Two separate failures, three weeks apart, turned out to be the same failure.

The first: a 강사과정 모집 글 generated three times — 내용 우선, 균형, 노출
우선 — read well, stayed on subject, and was useless as an announcement. No
date, no fee, no capacity, no way to apply. The memo was one line, so there
was nothing else to write. Giving the post more room made it worse: '내용
우선' raised the length target to 1500자 and the model spent the space on
brand facts, because those were the only concrete things available to it.
Measured over the batch it carried the highest brand-fact density of the
three modes (5.1 per 1000자 against 균형's 3.4).

The second: a 돌답례품 post scored 0% on search-intent coverage. The buyer
searching 돌답례품 wants a price, a minimum order quantity, a lead time, a
size, and a way to order. The post had none of them — again because the memo
had none of them. This one is worse than it looks, because the goal is search
exposure: Naver's DIA weighs how long a reader stays, so a post that ranks
for 돌답례품 and answers nothing gets its ranking taken back.

Neither is fixable by the content modes, which trade keyword pressure against
subject room. The binding constraint in both is that facts the reader needs
were never collected. This module collects them.

Nothing here is inferred or defaulted: an empty field stays empty and the
draft prompt is told, in the same terms core_facts uses, not to invent it. A
공지 that quietly acquires a plausible 수강료, or a product post that invents
a 최소 주문 수량, is worse than one that omits it — an LLM's number becomes a
promise the company has to honour or retract.

Fields are never required. '2026년 9월 24일부터 27일까지 추석 연휴입니다' is a
finished 공지 carrying one field; a 임시 휴무, a 배송 지연, a 팝업 종료 each
carry a different two or three. Which fields a post needs is decided by what
kind of post it is, and the only one who knows that is the person writing it.
"""
from __future__ import annotations

import re

from typing import Dict, List, Tuple

Field = Tuple[str, str, str]  # (key, 라벨, placeholder)


class Sheet:
    """One set of structured facts — 공지용, 서비스·신청용."""

    def __init__(self, key: str, title: str, hint: str, fields: List[Field]):
        self.key = key
        self.title = title
        self.hint = hint
        self.fields = fields
        self.labels: Dict[str, str] = {k: label for k, label, _ in fields}


NOTICE = Sheet(
    key="notice",
    title="📣 공지 정보",
    hint=(
        "연휴·휴무 안내, 강좌 모집, 행사·팝업 공지처럼 **독자에게 알려야 할 사실이 있는 "
        "글**에 채우세요. **해당하는 항목만** 채우면 됩니다 — 전부 채울 필요도, 정해진 "
        "조합도 없습니다. 예를 들어 추석 연휴 안내는 일시 하나로 충분합니다."
    ),
    fields=[
        ("when", "일시", "예: 2026년 9월 24일(목) ~ 9월 27일(일) / 10월 14일 10:00~13:00"),
        ("where", "장소", "예: 온자람 성산구 상담센터 (경남 창원시 성산구 반송로82번길 29, 1층)"),
        ("who", "대상", "예: 기업 인사담당자, 학부모, 마음돌봄 교육 수강 희망자"),
        ("capacity", "정원", "예: 12명 (선착순 마감)"),
        ("price", "비용", "예: 1인 18만원 (재료비·키트 포함)"),
        ("how", "신청 방법", "예: 네이버 폼으로 신청 후 안내 문자 수신"),
        ("link", "신청 링크", "예: https://…"),
        ("deadline", "마감", "예: 2026년 10월 7일(화) 18:00"),
        ("contact", "문의", "예: 055-255-1365 / onjaram@naver.com"),
    ],
)

# 온자람은 물건이 아니라 상담·교육·EAP 서비스를 안내합니다. 같은 구조(저장 키는 그대로)에서 항목 이름만
# 서비스에 맞춰 두었습니다 — 이용 요금, 최소 인원·회기, 진행 일정, 시간·형식, 구성, 맞춤 진행, 신청 방법.
PRODUCT = Sheet(
    key="product",
    title="🧾 서비스·신청 정보",
    hint=(
        "상담 프로그램·EAP·교육 과정처럼 **독자가 알아보고 신청하려고 검색해서 들어오는 글**에 채우세요. "
        "검색으로 들어온 사람이 요금과 신청 방법을 못 찾으면 바로 나가고, 네이버는 그 "
        "이탈을 순위에 반영합니다. **해당하는 항목만** 채우면 됩니다."
    ),
    fields=[
        ("price", "이용 요금", "예: 1회 50분 ○○원 / 기관 협약은 별도 문의"),
        ("moq", "최소 인원·회기", "예: 5명 이상 단체 / 4회기부터 진행"),
        ("lead_time", "진행 기간·일정", "예: 신청 후 1주 이내 일정 안내 / 월 2회 운영"),
        ("size", "시간·진행 방식", "예: 1회 50분 / 교육 1회기 2시간 / 대면·비대면"),
        ("options", "구성·옵션", "예: 개인상담·EAP·기관 출장교육 등 서비스 구성"),
        ("custom", "맞춤 진행", "예: 기관 요구에 맞춘 맞춤 교육 가능"),
        ("order", "신청 방법·접수처", "예: 네이버 예약 https://… / 전화 055-255-1365"),
    ],
)

SHEETS: Dict[str, Sheet] = {s.key: s for s in (NOTICE, PRODUCT)}

# 항목이 본문에 살아남았다고 볼 토큰 일치 비율 — coverage() 참고.
MATCH_RATIO = 0.6

# 이 개수 미만이면 '알릴 것이 적은 글'로 봅니다 — is_brief() 참고.
BRIEF_FIELD_COUNT = 4


def clean(sheet: Sheet, fields: Dict[str, str] | None) -> Dict[str, str]:
    """Drops blanks and unknown keys, preserving the sheet's field order."""
    given = fields or {}
    out: Dict[str, str] = {}
    for key, _, _ in sheet.fields:
        value = (given.get(key) or "").strip()
        if value:
            out[key] = value
    return out


def filled(sheet: Sheet, fields: Dict[str, str] | None) -> bool:
    """A post carries a sheet because someone filled it in, not because of a
    separate type flag — one less thing to keep in sync."""
    return bool(clean(sheet, fields))


def is_brief(sheet: Sheet, fields: Dict[str, str] | None) -> bool:
    """Too little to say to justify a length target?

    '내용 우선' asks for 1500자. That is right for a 모집 공고 carrying nine
    facts and wrong for a 연휴 안내 carrying one: the first 추석 연휴 안내
    generated this way came out at 848자, of which the actual announcement was
    three sentences and the rest was ATUM 소개 and the 조합 인증·수상 이력 — the brand-padding failure these fields exist to
    fix, reappearing from the other direction.

    A 연휴·휴무 안내 carries one to three fields; a 모집·행사 공고 carries five
    or more. BRIEF_FIELD_COUNT sits in that gap. It is a threshold, so it will
    occasionally be wrong, but the cost of the other error — a two-line notice
    inflated to 1500자 of brand copy — is the one that actually gets published.
    """
    return 0 < len(clean(sheet, fields)) < BRIEF_FIELD_COUNT


def is_brief_overall(pairs) -> bool:
    """`is_brief` across every sheet a post carries.

    A post with two notice fields and five product fields has plenty to say;
    judging each sheet on its own would call it brief on the notice side and
    strip the length target from a post that needed it.
    """
    total = sum(len(clean(sheet, given)) for sheet, given in pairs)
    return 0 < total < BRIEF_FIELD_COUNT


def coverage(sheet: Sheet, content: str, fields: Dict[str, str] | None) -> Dict[str, object]:
    """Which supplied facts actually survived into the finished post.

    Deterministic and report-only, in the same spirit as the keyword density
    check: the pipeline rewrites a body for keyword counts, but silently
    re-writing dates and prices is not something an LLM should be trusted
    with. The marketer is shown what went missing and fixes it in the editor.

    A value counts as present when it appears verbatim, or when most of its
    tokens do. Verbatim alone is too strict: a marketer types '씨제이씨 서초
    본점' and the draft writes '서초 본점', the same fact. Requiring every
    token is wrong the other way — '2026년 10월 14일(화) 10:00~13:00' almost
    never survives whole. MATCH_RATIO is the line between those, tuned so that
    dropping the year or the time from a date reads as a real omission while
    dropping a qualifier from a place name does not.
    """
    present = clean(sheet, fields)
    if not present:
        return {"checked": False, "missing": [], "found": [], "missing_labels": []}

    body = content or ""
    # 공백을 지우고 맞춰봅니다. 담당자는 '1만원 미만', '5만원'이라고 적고 모델은
    # '1만 원 미만', '5만 원'이라고 쓰는데, 한국어에서 이건 표기 차이일 뿐 다른
    # 사실이 아닙니다. 첫 5건 테스트에서 누락으로 잡힌 항목의 절반이 이것 하나
    # 때문이었고, 본문에 멀쩡히 들어 있는 가격을 빠졌다고 경고하고 있었습니다.
    squeezed = re.sub(r"\s", "", body)
    found, missing = [], []
    for key, value in present.items():
        tokens = {t for t in _tokens(value) if len(t) > 1}
        if not tokens:
            # 한 글자짜리만 남는 값은 판정할 근거가 없습니다. 조사·단위 한 글자는
            # 아무 본문에나 걸려서 있으나 없으나 '있음'이 됩니다.
            found.append(key)
            continue
        hit = value in body or (
            len([t for t in tokens if _token_in(t, squeezed)]) / len(tokens) >= MATCH_RATIO
        )
        (found if hit else missing).append(key)

    return {
        "checked": True,
        "found": found,
        "missing": missing,
        "missing_labels": [sheet.labels[k] for k in missing],
    }


def _token_in(token: str, squeezed_body: str) -> bool:
    """토큰이 본문에 있는가. 조사가 붙은 형태도 같은 말로 봅니다.

    담당자는 '가발에 관심있는 누구나'처럼 조사를 붙여 적고, 본문은 '가발'로
    씁니다. 마지막 한 글자를 떼고 한 번 더 보는 것으로 대부분의 조사(에, 를,
    의, 로…)를 흡수합니다. 두 글자 토큰까지 자르면 한 글자가 되어 아무 데나
    걸리므로 세 글자부터만 자릅니다.
    """
    if token in squeezed_body:
        return True
    return len(token) >= 3 and token[:-1] in squeezed_body


def _tokens(value: str) -> List[str]:
    out, buf = [], []
    for ch in value:
        if ch.isalnum():
            buf.append(ch)
        elif buf:
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return out
