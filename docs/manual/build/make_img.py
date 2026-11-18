"""설명서 그림 준비: 캡처(shots/*.png) → img/*.jpg, 시범 글의 카드 PNG → 카드 예시 띠, 쇼츠 장면 예시(docs/design/v9_*).

사용: OSMU_DATA_DIR=/tmp/osmu_manual_data python make_img.py   (seed_demo.py·cap*.py 다음에)
"""
import glob
import os
import shutil

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SHOTS = "/tmp/manual_build/shots"
IMG = os.path.join(HERE, "img")
DATA = os.environ.get("OSMU_DATA_DIR", "/tmp/osmu_manual_data")
os.makedirs(IMG, exist_ok=True)

for p in sorted(glob.glob(os.path.join(SHOTS, "*.png"))):
    Image.open(p).convert("RGB").save(os.path.join(IMG, os.path.basename(p)[:-4] + ".jpg"), quality=88)


def strip(files, name, h=540, gap=20):
    ims = [Image.open(f).convert("RGB") for f in files]
    ims = [im.resize((round(im.width * h / im.height), h), Image.LANCZOS) for im in ims]
    out = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) - 1), h), "white")
    x = 0
    for im in ims:
        out.paste(im, (x, 0))
        x += im.width + gap
    out.save(os.path.join(IMG, name + ".jpg"), quality=90)
    print(name, out.size)


# 시범 글 두 개의 카드(첫 글 = 에디토리얼 5장, 둘째 = 신뢰 리포트 4장)
dirs = sorted(glob.glob(os.path.join(DATA, "exports", "cards", "*", "*")), key=lambda d: len(glob.glob(d + "/slide_*.png")), reverse=True)
for d in dirs:
    files = sorted(glob.glob(d + "/slide_*.png"))
    strip(files, "cards_ed" if len(files) == 5 else "cards_rp")

for src, name in (("v9_쇼츠_글자중심_공감.png", "shorts_typo_ed"), ("v9_쇼츠_글자중심_신뢰.png", "shorts_typo_rp")):
    Image.open(os.path.join(ROOT, "docs", "design", src)).convert("RGB").save(os.path.join(IMG, name + ".jpg"), quality=90)
print("ok", len(os.listdir(IMG)))
