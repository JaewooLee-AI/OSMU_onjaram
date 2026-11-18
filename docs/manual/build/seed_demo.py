"""설명서 캡처용 시범 데이터(실제 사진·내담자 정보·API 키 없음). OSMU_DATA_DIR=/tmp/osmu_manual_data 로 실행."""
import os
import sys

sys.path.insert(0, "/Users/jwlee/project/OSMU_onjaram")
assert os.environ.get("OSMU_DATA_DIR") == "/tmp/osmu_manual_data"

from PIL import Image, ImageDraw, ImageFilter

from core import repo, storage
from core.brand_seed import seed_if_empty
from core.db import init_db

init_db()
seed_if_empty()


def art(name, c1, c2, c3):
    """사람·글자가 없는 추상 그림(설명서용)."""
    img = Image.new("RGB", (1600, 1200), c1)
    d = ImageDraw.Draw(img)
    for i in range(7):
        r = 260 + i * 70
        d.ellipse([1100 - r, 700 - r, 1100 + r, 700 + r], outline=c2, width=26)
    d.ellipse([180, 160, 640, 620], fill=c3)
    img = img.filter(ImageFilter.GaussianBlur(3))
    p = f"/tmp/manual_build/{name}.jpg"
    img.save(p, quality=90)
    with open(p, "rb") as f:
        return storage.save_upload(f.read(), f"{name}.jpg")


if os.path.isfile("/tmp/edsh/stitch_trust.png"):       # Stitch가 만든 AI 이미지(실제 사진 아님)
    with open("/tmp/edsh/stitch_trust.png", "rb") as f:
        room = storage.save_upload(f.read(), "ai_room.jpg")
else:                                                   # 없으면 합성 그림
    room = art("room", "#EFE7DA", "#C9B79C", "#7A9E87")
calm = art("calm", "#DCE7DE", "#A9C4B0", "#E07A5F")
navy = art("navy", "#E3E8EF", "#9DB0C8", "#4A7C59")

kits = repo.list_brand_kits()
b2c, b2b = kits[0]["id"], (kits[1]["id"] if len(kits) > 1 else kits[0]["id"])

BLOG = f"""안녕하세요, 마음성장파트너 주식회사 온자람입니다.

한 해의 끝자락이 다가오면 마음이 바빠집니다. 남은 일정을 챙기다 보면 어깨와 턱에 힘이 들어간 채 하루를 보내기도 합니다.

[IMAGE: {room}]

## 1. 긴장은 애쓰고 있다는 신호입니다
중요한 일을 앞두고 몸이 긴장하는 것은 자연스러운 반응입니다. 잘 해내고 싶은 마음이 클수록 부담도 함께 커집니다.

## 2. 오늘 해 볼 수 있는 작은 실천
첫째, 숨을 길게 내쉬며 어깨의 힘을 빼 봅니다.
둘째, 잠들기 전 30분은 화면을 멀리합니다.
셋째, 오늘 해낸 일 하나를 적어 봅니다.

## 3. 혼자 버겁다면 함께 이야기해요
마음이 계속 무겁다면 가까운 사람이나 상담 기관과 이야기를 나누는 것도 좋은 방법입니다.
"""

a = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="연말 긴장·불안 — 몸과 마음의 신호, 작은 실천 3가지")
repo.update_campaign(
    a["id"], brand_kit_id=b2c, status="draft", title="연말에 몸이 굳는다면, 마음이 보내는 신호입니다",
    content=BLOG, post_type="column", storage_file_paths=[room], card_photo_paths=[calm],
    naver_hashtags=["#온자람", "#마음돌봄", "#연말스트레스", "#창원심리상담", "#감정돌봄", "#마음노트", "#숨고르기"],
    instagram_caption="한 해의 끝, 어깨에 힘이 들어가 있진 않나요?\n오늘은 숨을 길게 내쉬고, 해낸 일 하나를 적어 보세요.",
    instagram_hashtags=["#마음돌봄", "#온자람", "#연말"],
    guardrail_report={"compliance_pass": True, "score": 94, "strengths": ["보편 심리교육 내용으로 썼습니다"],
                      "related_posts": [{"title": "시험 앞둔 마음 다독이기", "date": "2026-10-13"}]},
)

b = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="학부모 대상 '아이 마음 읽기' 교육 안내")
repo.update_campaign(
    b["id"], brand_kit_id=b2b, status="ready_to_publish", title="[온자람 소식] 학부모 '아이 마음 읽기' 교육 안내",
    content="안녕하세요, 마음성장파트너 주식회사 온자람입니다.\n\n아이의 마음을 읽는 대화법을 함께 배우는 교육을 안내합니다.\n\n## 1. 이런 분께 권해요\n아이와 대화가 자꾸 끊긴다고 느끼는 보호자\n\n## 2. 신청 방법\n전화 또는 네이버 예약으로 신청해 주세요.\n",
    post_type="notice", card_photo_paths=[navy],
    guardrail_report={"compliance_pass": True, "score": 91},
)

c = repo.insert_campaign(source_type="manual", status="awaiting_media",
                         memo="직장인 스트레스 관리 특강 후기 — 참여 기관 이름은 빼고, 실습(호흡·감정 기록) 위주로")
repo.update_campaign(c["id"], brand_kit_id=b2b, post_type="review", title="")

d = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="불면 — 잠들기 전 습관")
repo.update_campaign(
    d["id"], brand_kit_id=b2c, status="draft", title="잠이 오지 않는 밤, 이렇게 해 보세요",
    content="안녕하세요, 마음성장파트너 주식회사 온자람입니다.\n\n잠들기 어려운 밤이 이어지면 낮 동안의 컨디션도 흔들립니다.\n",
    post_type="column",
    guardrail_report={"compliance_pass": False, "score": 68,
                      "llm_issues": ["'이 방법이면 불면이 사라집니다'처럼 효과를 단정하는 표현이 있습니다"]},
)

e = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="가을 감정 돌봄 워크숍 후기")
repo.update_campaign(e["id"], brand_kit_id=b2c, title="가을, 감정에 이름 붙이기 워크숍을 마치며", content="(게시 완료된 글)\n",
                     post_type="review")
repo.mark_published(e["id"])

# 카드·쇼츠(규칙 기반 기획 — AI 호출 없음)
from cards import shorts_script
from flet_app import outputs
from flet_app.views.card_studio import render_storyboard, save_storyboard

sb, _ = outputs.plan_for_campaign(a["id"], type_id="empathy", design_id="editorial", use_ai=False, count=5)
render_storyboard(a["id"], sb)
scenes, _ = shorts_script.convert(sb, b2c, 45)
shorts_script.apply_to_storyboard(sb, scenes)
save_storyboard(a["id"], sb)

sb2, _ = outputs.plan_for_campaign(b["id"], type_id="event_notice", design_id="report", use_ai=False, count=4)
render_storyboard(b["id"], sb2)
for cc in repo.list_campaigns():
    repo.set_campaign_brand_kit(cc["id"], cc["brand_kit_id"])
print("ok", a["id"], b["id"])
