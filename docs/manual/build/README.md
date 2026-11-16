# 사용자 설명서 다시 만들기

`docs/manual/온자람_OSMU_사용자설명서.pptx`는 아래 순서로 만들었습니다. 화면이 바뀌면 같은 순서로 다시 만들면 됩니다.

1. **시범 데이터**: `OSMU_DATA_DIR=/tmp/osmu_manual_data python seed_demo.py`
   — 실제 사진·내담자 정보·API 키 없이 시범 글 5개(AI·합성 이미지만)를 만듭니다. 실제 데이터 폴더는 건드리지 않습니다.
   (방 사진은 Stitch가 만든 AI 이미지 `/tmp/edsh/stitch_trust.png`를 썼습니다 — 없으면 `art()`로 만든 그림으로 바꾸세요.)
2. **앱 띄우기**: `OSMU_DATA_DIR=/tmp/osmu_manual_data flet run --web --port 8560 flet_app/main.py`
3. **캡처**: `python cap.py s_main.json` · `s_del.json` · `s_unsaved.json`(Playwright, 1280×860, 1.5배) → `shots/*.png`
   (클릭 좌표는 화면 배치 기준이라 화면이 바뀌면 좌표를 고쳐야 합니다.)
4. **슬라이드**: `node build.js out.pptx`(pptxgenjs, 이미지는 `img/*.jpg`) → `python fix_fonts.py out.pptx "Malgun Gothic"`
   (테마의 한글 글꼴·글자 언어 ko-KR 지정 — 빠지면 일부 환경에서 한글이 안 보임).
5. **확인**: 이 Mac의 LibreOffice는 한글을 그리지 못하므로 PowerPoint로 PDF를 내보내 확인했습니다.

글꼴은 Windows 기본 '맑은 고딕(Malgun Gothic)'을 씁니다.
