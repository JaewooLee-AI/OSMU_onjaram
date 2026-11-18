"""설명서 추가 캡처: 쇼츠용 동영상 올리기 진행 창(느린 연결 흉내) + 대본 펼친 화면."""
import time
from playwright.sync_api import sync_playwright
VID = "/tmp/manual_build/vid/예시_영상.mp4"
S = "/tmp/manual_build/shots/"
with sync_playwright() as p:
    b = p.chromium.launch(channel="chromium")
    pg = b.new_page(viewport={"width": 1280, "height": 860}, device_scale_factor=1.5)
    pg.goto("http://127.0.0.1:8560/"); time.sleep(7)
    pg.mouse.click(695, 540); time.sleep(4)          # 대시보드 → 첫 글
    pg.mouse.click(55, 175); time.sleep(6)           # 카드·쇼츠
    pg.mouse.click(1043, 400); time.sleep(2.5)       # 확인 창
    with pg.expect_file_chooser(timeout=60000) as fc:
        pg.mouse.click(808, 541)
    cdp = pg.context.new_cdp_session(pg)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 20,
             "downloadThroughput": 50_000_000, "uploadThroughput": 2_500_000})
    fc.value.set_files(VID)
    time.sleep(9)
    pg.screenshot(path=S + "32_upload_progress.png"); print("shot progress")
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
    for _ in range(90):
        time.sleep(2)
        if "올렸습니다" in pg.content() or "올렸" in (pg.inner_text("body") or ""):
            break
    time.sleep(3)
    pg.screenshot(path=S + "33_upload_done.png"); print("shot done")
    pg.mouse.move(1000, 600)
    for _ in range(4):
        pg.mouse.wheel(0, 1200); time.sleep(1.2)
    pg.mouse.click(745, 733); time.sleep(3)          # 대본 보기·고치기
    pg.mouse.wheel(0, 700); time.sleep(1.5)
    pg.screenshot(path=S + "13_studio4.png"); print("shot script")
    b.close()
