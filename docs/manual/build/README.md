# 사용자 설명서 다시 만들기

`docs/manual/온자람_OSMU_사용자설명서.pptx`는 아래 순서로 만들었습니다. 화면이 바뀌면 같은 순서로 다시 만들면 됩니다.

1. **시범 데이터**: `OSMU_DATA_DIR=/tmp/osmu_manual_data python seed_demo.py`
   — 실제 사진·내담자 정보·API 키 없이 시범 글 5개(AI·합성 이미지만)를 만듭니다. 실제 데이터 폴더는 건드리지 않습니다.
   (방 사진은 Stitch가 만든 AI 이미지 `/tmp/edsh/stitch_trust.png`를 썼습니다 — 없으면 `art()`로 만든 그림으로 바꾸세요.)
2. **앱 띄우기**: `OSMU_DATA_DIR=/tmp/osmu_manual_data flet run --web --port 8560 flet_app/main.py`
3. **캡처**: `python cap.py s_main.json` · `s_del.json` · `s_unsaved.json`(Playwright, 1280×860, 1.5배) → `/tmp/manual_build/shots/*.png`
   (클릭 좌표는 화면 배치 기준이라 화면이 바뀌면 좌표를 고쳐야 합니다.)
   그다음 `python cap_upload.py` — 쇼츠용 동영상 올리기(확인 창 → 진행 창, 업로드 속도를 늦춰 퍼센트가 보이게)와 대본 펼친 화면.
   영상은 사람이 없는 합성 영상으로 만듭니다:
   `ffmpeg -f lavfi -i "gradients=s=1080x1920:speed=0.02:c0=0x7A9E87:c1=0xEFE7DA:c2=0x4A7C59" -vf "noise=alls=10:allf=t,format=yuv420p" -t 20 -r 30 -c:v libx264 -b:v 20M /tmp/manual_build/vid/예시_영상.mp4`
4. **그림**: `OSMU_DATA_DIR=/tmp/osmu_manual_data python make_img.py` — 캡처를 `img/*.jpg`로, 시범 글의 카드를 예시 띠로,
   쇼츠 장면 예시는 `docs/design/v9_쇼츠_글자중심_*.png`에서(`img/`는 gitignore).
5. **슬라이드**: `NODE_PATH=<pptxgenjs가 설치된 node_modules> SKILL_DIR=<pptx 스킬 폴더> node build.js out.pptx` →
   `python fix_fonts.py out.pptx "Malgun Gothic"` (테마의 한글 글꼴·글자 언어 ko-KR 지정 — 빠지면 일부 환경에서 한글이 안 보임).
6. **확인**: 이 Mac의 LibreOffice는 한글을 그리지 못하므로 PowerPoint로 PDF를 내보내 확인했습니다
   (PowerPoint는 /tmp 파일을 열지 못하므로 저장소 안에 잠깐 복사해서 열고, 확인 뒤 지웁니다).

글꼴은 Windows 기본 '맑은 고딕(Malgun Gothic)'을 씁니다.
