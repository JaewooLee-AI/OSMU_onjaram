"""Flet 웹 화면 캡처. 사용: python cap.py steps.json  — steps: [["wait",s],["click",x,y],["scroll",x,y,dy],["shot",name],["key",k],["type",t]]"""
import json, sys, time
from playwright.sync_api import sync_playwright
steps = json.load(open(sys.argv[1]))
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 860}, device_scale_factor=1.5)
    pg.goto("http://127.0.0.1:8560/")
    time.sleep(7)
    for s in steps:
        op = s[0]
        if op == "wait": time.sleep(s[1])
        elif op == "click": pg.mouse.click(s[1], s[2]); time.sleep(s[3] if len(s) > 3 else 2.5)
        elif op == "scroll": pg.mouse.move(s[1], s[2]); pg.mouse.wheel(0, s[3]); time.sleep(1.5)
        elif op == "key": pg.keyboard.press(s[1]); time.sleep(0.5)
        elif op == "type": pg.keyboard.type(s[1]); time.sleep(0.5)
        elif op == "shot": pg.screenshot(path=f"/tmp/manual_build/shots/{s[1]}.png"); print("shot", s[1])
    b.close()
