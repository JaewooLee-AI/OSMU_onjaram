// 온자람 OSMU 사용자 설명서 (pptxgenjs, 구조화된 덱: 테마·레이아웃·섹션)
const pptxgen = require("pptxgenjs");
const path = require("path");
const { applyTheme } = require(path.join(process.env.SKILL_DIR, "scripts/apply_theme.js"));

const IMG = (n) => path.join(__dirname, "img", n + ".jpg");
const OUT = process.argv[2] || path.join(__dirname, "온자람_OSMU_사용자설명서.pptx");

const THEME = {
  name: "Onjaram OSMU",
  headFontFace: process.env.QA_FONT || "Malgun Gothic",
  bodyFontFace: process.env.QA_FONT || "Malgun Gothic",
  colors: {
    dk1: "1F2A24", lt1: "FFFFFF", dk2: "26372C", lt2: "F3F6F3",
    accent1: "4A7C59", accent2: "2C4A6F", accent3: "E07A5F", accent4: "F0ECE1",
    accent5: "8FB39A", accent6: "9DB0C8", hlink: "2C4A6F", folHlink: "4A7C59",
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.title = "온자람 OSMU 사용자 설명서";
pres.author = "주식회사 온자람";
pres.company = "주식회사 온자람";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const W = 13.333, H = 7.5;
const FOOT = "온자람 OSMU 사용자 설명서";

// ---------- 레이아웃 ----------
pres.defineSlideMaster({
  title: "TITLE",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.2, w: 11.7, h: 1.6, fontSize: 44, bold: true, color: C.background1, valign: "bottom", align: "left" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 3.95, w: 11.7, h: 1.2, fontSize: 20, color: C.accent5, valign: "top" }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "SECTION",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 2.3, y: 2.6, w: 10.2, h: 1.2, fontSize: 38, bold: true, color: C.background1, valign: "middle", align: "left" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 2.3, y: 3.8, w: 10.2, h: 1.2, fontSize: 18, color: C.accent5, valign: "top" }, text: "" } },
  ],
  slideNumber: { x: 12.3, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: C.accent5, align: "right" },
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 12.3, h: 0.7, fontSize: 28, bold: true, color: C.text2, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.5, y: 0.98, w: 12.3, h: 0.45, fontSize: 14, color: C.accent1, valign: "top", margin: 0 }, text: "" } },
    { text: { text: FOOT, options: { x: 0.5, y: 7.05, w: 6, h: 0.3, fontSize: 10, color: "7A877F", margin: 0 } } },
  ],
  slideNumber: { x: 12.3, y: 7.05, w: 0.55, h: 0.3, fontSize: 10, color: "7A877F", align: "right" },
});

let secTitle = "";
function section(title, sub, num) {
  pres.addSection({ title });
  secTitle = title;
  const s = pres.addSlide({ masterName: "SECTION", sectionTitle: secTitle });
  s.addShape(pres.shapes.OVAL, { x: 0.8, y: 2.75, w: 1.2, h: 1.2, fill: { color: C.accent3 }, line: { color: C.accent3 }, objectName: "섹션 번호 원" });
  s.addText(String(num), { x: 0.8, y: 2.75, w: 1.2, h: 1.2, fontSize: 36, bold: true, color: C.background1, align: "center", valign: "middle", isTextBox: true, objectName: "섹션 번호" });
  s.addText(title, { placeholder: "title" });
  s.addText(sub, { placeholder: "body" });
  return s;
}

// ---------- 화면 + 번호 설명 슬라이드 ----------
const SHOT = { x: 0.5, y: 1.55, w: 7.9 };
SHOT.h = SHOT.w * 860 / 1280;              // 5.31
function px(x, y) { return { x: SHOT.x + (x / 1280) * SHOT.w, y: SHOT.y + (y / 860) * SHOT.h }; }

function marker(slide, n, cx, cy) {
  const p = px(cx, cy), r = 0.34;
  slide.addShape(pres.shapes.OVAL, {
    x: p.x - r / 2, y: p.y - r / 2, w: r, h: r, fill: { color: C.accent3 }, line: { color: C.background1, width: 1.5 },
    shadow: { type: "outer", color: "000000", opacity: 0.25, blur: 3, offset: 1, angle: 90 }, objectName: `표시 ${n}`,
  });
  slide.addText(String(n), { x: p.x - r / 2, y: p.y - r / 2, w: r, h: r, fontSize: 12, bold: true, color: C.background1,
    align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: `표시 번호 ${n}` });
}

function shotSlide({ title, sub, shot, items, tip }) {
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: secTitle });
  s.addText(title, { placeholder: "title" });
  s.addText(sub || "", { placeholder: "body" });
  s.addImage({ path: IMG(shot), x: SHOT.x, y: SHOT.y, w: SHOT.w, h: SHOT.h, objectName: "화면 캡처", altText: title + " 화면" });
  s.addShape(pres.shapes.RECTANGLE, { x: SHOT.x, y: SHOT.y, w: SHOT.w, h: SHOT.h, fill: { type: "none" }, line: { color: "C9D3CC", width: 0.75 }, objectName: "캡처 테두리" });
  items.forEach((it, i) => { if (it.at) marker(s, i + 1, it.at[0], it.at[1]); });

  // 오른쪽 설명
  const X = 8.75, Wd = 4.1;
  const tipH = tip ? 0.95 : 0;
  const avail = (SHOT.y + SHOT.h) - SHOT.y - (tip ? tipH + 0.15 : 0);
  const rowH = avail / items.length;
  items.forEach((it, i) => {
    const y = SHOT.y + i * rowH;
    s.addShape(pres.shapes.OVAL, { x: X, y: y + 0.03, w: 0.34, h: 0.34, fill: { color: C.accent3 }, line: { color: C.accent3 }, objectName: `설명 번호 원 ${i + 1}` });
    s.addText(String(i + 1), { x: X, y: y + 0.03, w: 0.34, h: 0.34, fontSize: 12, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText([
      { text: it.h, options: { bold: true, fontSize: 14, color: C.text2, breakLine: true } },
      { text: it.d, options: { fontSize: 12, color: "3F4A43" } },
    ], { x: X + 0.45, y: y - 0.02, w: Wd - 0.45, h: rowH, valign: "top", margin: 0, paraSpaceAfter: 2, isTextBox: true, objectName: `설명 ${i + 1}` });
  });
  if (tip) {
    const ty = SHOT.y + SHOT.h - tipH;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: X, y: ty, w: Wd, h: tipH, rectRadius: 0.08, fill: { color: C.background2 }, line: { color: "D5E0D8", width: 0.75 }, objectName: "도움말 상자" });
    s.addText([{ text: "도움말  ", options: { bold: true, color: C.accent1 } }, { text: tip, options: { color: "3F4A43" } }],
      { x: X + 0.15, y: ty + 0.05, w: Wd - 0.3, h: tipH - 0.1, fontSize: 12, valign: "middle", margin: 0, isTextBox: true, objectName: "도움말" });
  }
  return s;
}

// =============================== 표지 ===============================
pres.addSection({ title: "표지" });
secTitle = "표지";
{
  const s = pres.addSlide({ masterName: "TITLE", sectionTitle: secTitle });
  s.addShape(pres.shapes.OVAL, { x: 9.6, y: -1.2, w: 5, h: 5, fill: { color: C.accent1, transparency: 55 }, line: { color: C.accent1, transparency: 100 }, objectName: "장식 원 1" });
  s.addShape(pres.shapes.OVAL, { x: 11.2, y: 4.6, w: 2.6, h: 2.6, fill: { color: C.accent3, transparency: 20 }, line: { color: C.accent3, transparency: 100 }, objectName: "장식 원 2" });
  s.addText("온자람 OSMU 사용자 설명서", { placeholder: "title" });
  s.addText("메모 한 벌로 블로그 · 카드뉴스 · 쇼츠까지 — 화면 따라 하기", { placeholder: "body" });
  s.addText("주식회사 온자람 · 2026년 11월판", { x: 0.8, y: 6.4, w: 8, h: 0.4, fontSize: 14, color: C.accent5, margin: 0, isTextBox: true, objectName: "판 정보" });
}

// 이 앱으로 하는 일
pres.addSection({ title: "한눈에 보기" });
secTitle = "한눈에 보기";
{
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: secTitle });
  s.addText("이 앱으로 하는 일", { placeholder: "title" });
  s.addText("메모와 사진을 한 번 넣으면, 블로그 글을 쓰고 그 글로 카드뉴스와 쇼츠까지 만듭니다", { placeholder: "body" });
  const steps = [
    ["메모·사진", "주제·하고 싶은 말을\n짧게 적고 사진을 올림", C.accent4, C.text2],
    ["블로그 글", "AI가 온자람 말투로 쓰고\n상담 윤리 기준으로 검수", C.accent1, C.background1],
    ["카드뉴스", "글을 4~6장 카드로\n나눠 그림", C.accent1, C.background1],
    ["쇼츠 영상", "카드로 대본을 만들고\n음성·자막을 붙임", C.accent1, C.background1],
    ["네이버 게시", "크롬 창에 자동 입력,\n마지막 [발행]만 직접", C.accent2, C.background1],
  ];
  const bw = 2.2, gap = 0.3, x0 = (W - (steps.length * bw + (steps.length - 1) * gap)) / 2, y0 = 2.2;
  steps.forEach(([h, d, fill, ink], i) => {
    const x = x0 + i * (bw + gap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: y0, w: bw, h: 2.4, rectRadius: 0.12, fill: { color: fill }, line: { color: fill }, objectName: `단계 ${i + 1}` });
    s.addText(String(i + 1), { x: x + 0.2, y: y0 + 0.2, w: 0.5, h: 0.5, fontSize: 22, bold: true, color: ink === C.text2 ? C.accent3 : C.accent4, margin: 0, isTextBox: true });
    s.addText([{ text: h, options: { bold: true, fontSize: 20, color: ink, breakLine: true } }, { text: d, options: { fontSize: 13, color: ink } }],
      { x: x + 0.2, y: y0 + 0.8, w: bw - 0.4, h: 1.5, valign: "top", margin: 0, paraSpaceAfter: 6, isTextBox: true });
    if (i < steps.length - 1) s.addShape(pres.shapes.RIGHT_ARROW, { x: x + bw + 0.04, y: y0 + 1.05, w: 0.22, h: 0.3, fill: { color: C.accent3 }, line: { color: C.accent3 }, objectName: `화살표 ${i + 1}` });
  });
  const notes = [
    ["글마다 골라서", "블로그만, 카드뉴스만, 셋 다 — 워크벤치의 '이번에 만들 것'에서 고릅니다."],
    ["비용 확인 먼저", "AI 이미지·음성처럼 비용이 드는 작업은 예상 금액을 보여 주고 물어본 뒤 실행합니다."],
    ["사람이 마지막 확인", "검수 결과·동의 체크를 거치고, 네이버 [발행] 버튼은 사람이 누릅니다."],
  ];
  notes.forEach(([h, d], i) => {
    const x = 0.9 + i * 4.0;
    s.addShape(pres.shapes.OVAL, { x, y: 5.25, w: 0.42, h: 0.42, fill: { color: C.accent3 }, line: { color: C.accent3 }, objectName: `요점 ${i + 1}` });
    s.addText("✓", { x, y: 5.25, w: 0.42, h: 0.42, fontSize: 16, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText([{ text: h, options: { bold: true, fontSize: 15, color: C.text2, breakLine: true } }, { text: d, options: { fontSize: 12, color: "3F4A43" } }],
      { x: x + 0.55, y: 5.2, w: 3.3, h: 1.4, valign: "top", margin: 0, isTextBox: true });
  });
}

shotSlide({
  title: "화면 구성 — 왼쪽 메뉴 7개", sub: "모든 일은 왼쪽 메뉴에서 시작합니다. 메뉴를 옮겨도 지금 작업 중인 글은 그대로 열립니다",
  shot: "01_dashboard",
  items: [
    { at: [55, 40], h: "대시보드", d: "준비 상태·진행 현황·이번 달 AI 비용" },
    { at: [55, 110], h: "워크벤치", d: "메모를 쓰고 블로그 글을 만들고 고치는 곳" },
    { at: [55, 175], h: "카드·쇼츠", d: "카드뉴스를 크게 보며 다듬고 쇼츠 영상 만들기" },
    { at: [55, 240], h: "보관함", d: "지난 글 검색·보관·용량 정리" },
    { at: [55, 305], h: "브랜드 킷", d: "회사 소개·말투·금기어 등 AI가 따르는 기준" },
    { at: [55, 370], h: "네이버 게시", d: "블로그에 반자동으로 올리기" },
    { at: [55, 435], h: "설정 · 토큰", d: "AI 연결·카드 디자인·사용량·데이터 옮기기" },
  ],
});

// =============================== 1. 준비 ===============================
section("처음 한 번: 준비하기", "AI 연결 → 브랜드 킷 확인 → 기본 생성 대상. 한 번 해 두면 다음부터는 메모만 쓰면 됩니다", 1);

shotSlide({
  title: "AI 연결하기 (Google 키 하나로)", sub: "설정 → 🤖 AI 연결·모델 — 키를 넣으면 쓸 수 있는 모델과 공식 가격을 불러와 추천합니다",
  shot: "19_set_ai",
  items: [
    { at: [187, 237], h: "첫 탭 'AI 연결·모델'", d: "설정 화면의 첫 탭입니다. 다른 탭은 필요할 때만 엽니다." },
    { at: [173, 397], h: "Google API 키 붙여넣기", d: "Google AI Studio에서 받은 키를 붙여 넣습니다. 키는 암호화되어 이 PC에만 저장됩니다." },
    { at: [187, 441], h: "[키 확인하고 모델·가격 불러오기]", d: "글쓰기·AI 이미지·음성 모델을 추천해 줍니다. 목록에서 바꿀 수 있고 [적용]을 누르면 끝납니다." },
    { at: [167, 475], h: "지금 설정 확인", d: "각 기능에 어떤 모델이 지정됐는지 한 줄로 보여 줍니다." },
    { at: [167, 576], h: "고급 설정", d: "Claude·GPT를 쓰거나 단가를 직접 넣을 때만 펼칩니다." },
  ],
  tip: "대시보드 맨 위 '먼저 준비할 것이 있습니다' 상자가 사라지면 준비 완료입니다.",
});

shotSlide({
  title: "브랜드 킷 — AI가 따르는 회사 기준", sub: "글마다 이 내용이 AI에 그대로 전달됩니다. 사실(가격·인증·연락처)은 여기 적힌 것만 씁니다",
  shot: "16_brandkit",
  items: [
    { at: [153, 203], h: "킷 목록", d: "공감·회복(B2C)과 전문·신뢰(B2B·B2G) 두 킷이 기본입니다. 글마다 맞는 킷을 고릅니다." },
    { at: [160, 293], h: "새 킷 만들기·복제·이름 변경", d: "새 사업 분야가 생기면 킷을 복제해 고칩니다. 삭제는 '보관'이라 되살릴 수 있습니다." },
    { at: [153, 433], h: "업종·사업 분야", d: "이 킷이 다루는 분야. 키워드 추천과 글의 배경 설명에 쓰입니다." },
    { at: [153, 512], h: "브랜드 페르소나", d: "누구의 목소리로 쓰는지 정합니다." },
    { at: [153, 640], h: "톤앤매너 가이드", d: "말투·문장 길이·금지 표현을 줄마다 하나씩 적습니다." },
  ],
});

shotSlide({
  title: "브랜드 킷 — 핵심 팩트와 저장", sub: "아래로 내리면 핵심 팩트·용어집·키워드·금기어(회사 공통)가 이어집니다",
  shot: "17_brandkit2",
  items: [
    { at: [147, 349], h: "핵심 팩트", d: "가격·회기·연락처·거점 주소처럼 글에 들어가도 되는 사실. 문서에 없는 값은 비워 둡니다." },
    { at: [147, 783], h: "용어집·키워드·금기어", d: "바른 표기와 피할 표현(치료·완치 등)을 정합니다. 금기어는 자동으로 바꿔 씁니다." },
    { h: "두 개의 저장 버튼", d: "[킷 저장]은 이 킷의 값, [회사 공통 저장]은 기업명·연락처·금기어처럼 모든 킷에 쓰는 값입니다." },
    { h: "저장 안 하고 떠나면?", d: "다른 메뉴나 킷으로 가려 할 때 '저장하고 이동 / 저장 안 하고 이동'을 묻습니다." },
  ],
});

shotSlide({
  title: "기본 생성 대상과 쇼츠 길이", sub: "설정 → 📣 생성 채널 — 워크벤치 [만들기]의 처음 체크 상태를 정합니다",
  shot: "22_set_channels",
  items: [
    { at: [167, 363], h: "기본 생성 대상", d: "블로그·카드뉴스·쇼츠 중 평소에 만드는 것을 체크합니다. 글마다 바꿀 수 있습니다." },
    { at: [160, 515], h: "쇼츠 대본 기본 길이", d: "20·30·45·60초. 카드 수가 많으면 목표보다 길어질 수 있고, 그때는 안내가 나옵니다." },
    { at: [160, 592], h: "기본 생성 대상 저장", d: "누르면 다음 글부터 적용됩니다." },
    { at: [167, 751], h: "블로그와 함께 만들 SNS 글", d: "인스타그램 캡션을 같이 만들지 정합니다. 끄면 그만큼 AI 비용이 들지 않습니다." },
  ],
});

// =============================== 2. 글 만들기 ===============================
section("글 만들기 — 워크벤치", "메모 → [만들기] → 결과 확인 → 고치기 → 게시 대기열", 2);

shotSlide({
  title: "대시보드 — 오늘 할 일 한눈에", sub: "앱을 켜면 처음 나오는 화면입니다. 카드를 누르면 그 글이 워크벤치에서 열립니다",
  shot: "01_dashboard",
  items: [
    { at: [153, 133], h: "시작 점검", d: "AI 키·글쓰기 모델·대표 전화처럼 빠진 준비가 있으면 빨간 상자로 알려 줍니다." },
    { at: [153, 267], h: "내 블로그 현황·제안", d: "공개 블로그 글을 가져와 겹치는 주제·시즌 주제를 제안합니다(로그인 불필요)." },
    { at: [160, 400], h: "상태별 개수·AI 비용", d: "작업 중·초안 완료·게시 완료·게시 대기 개수와 이번 달 AI 비용(추정)." },
    { at: [587, 533], h: "진행 보드", d: "소재 대기 → 생성 중 → 초안 완료 → 게시 대기 → 게시 완료. 글을 누르면 워크벤치로." },
    { at: [1067, 624], h: "게시한 글 다시 열기", d: "게시 완료 칸은 누르면 네이버 글이 열리고, [작업 열기]·[카드·쇼츠]로 작업 화면에 갑니다." },
  ],
});

shotSlide({
  title: "새 글 시작 — 메모 쓰기", sub: "워크벤치 → [➕ 새 콘텐츠]. 짧은 메모만으로도 글을 만들 수 있습니다",
  shot: "05_wb_input",
  items: [
    { at: [1160, 97], h: "[➕ 새 콘텐츠] · 작업할 콘텐츠", d: "새 글을 만들거나, 왼쪽 목록에서 최근 글을 고릅니다. 지난 글은 📚 보관함에서 찾습니다." },
    { at: [153, 203], h: "브랜드 킷", d: "이 글의 분야에 맞는 킷을 고릅니다(공감·회복 / 전문·신뢰)." },
    { at: [153, 263], h: "제목 (선택)", d: "비워 두면 AI가 짓습니다." },
    { at: [153, 320], h: "담당자 메모", d: "주제와 꼭 넣을 내용. 개별 내담자의 나이·시기·상황은 쓰지 않습니다." },
    { at: [153, 468], h: "공지 정보 · 서비스·신청 정보", d: "일시·장소·비용처럼 정확해야 하는 값은 여기 칸에 넣습니다. 본문에 빠지면 알려 줍니다." },
    { at: [147, 545], h: "콘텐츠 모드", d: "내용 우선 / 균형(기본) / 노출 우선 — 검색 키워드를 얼마나 넣을지." },
  ],
});

shotSlide({
  title: "글 유형 · 서식 · 사진", sub: "아래로 내리면 글의 형식과 사진을 정합니다",
  shot: "06_wb_input2",
  items: [
    { at: [147, 177], h: "글 유형", d: "현장 후기 · 칼럼·마음 이야기 · 모집·안내. 고정 인사·소제목 구조·문의 안내가 유형에 맞게 붙습니다." },
    { at: [147, 403], h: "원고 서식", d: "굵게·형광·소제목·요약 상자를 얼마나 쓸지. 보통은 '킷 기본'으로 둡니다." },
    { at: [213, 688], h: "사진 추가", d: "올린 사진은 자동으로 줄여 저장되고, 본문에 [IMAGE: …] 자리로 들어갑니다." },
    { at: [153, 793], h: "사진 자리를 AI 이미지로 채우기", d: "사진이 없을 때 선택. 글을 만든 뒤 쓸 수 있고, 비용 확인 창을 거칩니다." },
  ],
  tip: "현장 후기에 사람이 나온 사진을 쓰면, 게시 전에 동의 확인 3항목을 체크해야 [게시]가 켜집니다.",
});

shotSlide({
  title: "이번에 만들 것 고르고 [만들기]", sub: "체크한 것만 만듭니다. 생성은 수십 초가 걸리며, 그동안 다른 메뉴로 가도 됩니다",
  shot: "07_wb_input3",
  items: [
    { at: [147, 469], h: "이번에 만들 것", d: "블로그(+인스타 캡션) · 카드뉴스 · 쇼츠 대본 중 고릅니다." },
    { at: [160, 659], h: "카드뉴스는 1장만", d: "요약 카드 한 장만 만들 때 켭니다." },
    { at: [273, 745], h: "[💾 저장]", d: "메모·설정만 저장합니다(만들지 않음)." },
    { at: [553, 745], h: "[🪄 만들기]", d: "블로그를 만들면 이 화면에 결과·완료 안내가, 카드·쇼츠만 만들면 카드·쇼츠 화면이 열립니다." },
    { at: [720, 168], h: "채널 시뮬레이터", d: "네이버 블로그·인스타그램에 올렸을 때 모습을 미리 봅니다. 다시 만들 때는 고친 내용이 바뀐다고 먼저 묻습니다." },
  ],
});

shotSlide({
  title: "결과 확인 — 게시 전 확인 상자", sub: "다 만들면 결과가 맨 위에 보이고, 메모·설정은 접혀 있습니다",
  shot: "02_wb_result",
  items: [
    { at: [160, 190], h: "메모·설정 · 다시 만들기", d: "메모를 고쳐 다시 만들려면 펼칩니다." },
    { at: [220, 247], h: "[🃏 카드·쇼츠 열기]", d: "같은 글의 카드뉴스·쇼츠 화면으로 바로 갑니다." },
    { at: [153, 352], h: "게시 전 확인", d: "검수·빠진 정보·동의 여부를 한곳에. 회색은 참고, 주황은 고칠 것." },
    { at: [193, 429], h: "네이버 본문 · 인스타 캡션 탭", d: "채널마다 결과를 따로 고칩니다." },
    { at: [167, 557], h: "본문 직접 고치기", d: "**굵게** ==형광== ## 소제목을 써도 됩니다. [IMAGE:] 줄을 옮기면 사진 위치가 바뀝니다." },
    { at: [767, 387], h: "미리보기", d: "고친 내용이 블로그에서 어떻게 보일지 바로 확인합니다." },
  ],
});

shotSlide({
  title: "태그 · 수정 요청 · 게시 대기열", sub: "본문 아래로 내리면 발행 태그와 'AI에게 고쳐 달라고 하기'가 있습니다",
  shot: "04_wb_result3",
  items: [
    { at: [160, 504], h: "발행 태그", d: "네이버에 붙일 태그. 띄어쓰기로 구분합니다." },
    { at: [173, 552], h: "[본문 저장]", d: "직접 고친 본문·태그를 저장합니다. 저장 안 하고 메뉴를 옮기면 물어봅니다." },
    { at: [173, 593], h: "복사해서 직접 붙여넣기", d: "자동 게시를 쓰지 않을 때 서식째 복사합니다." },
    { at: [160, 651], h: "수정 요청해서 다시 쓰기", d: "'도입부를 더 친근하게'처럼 적고 길이(그대로·20% 길게/짧게)를 골라 [수정 반영]." },
    { h: "🚀 네이버 게시 대기열로", d: "맨 아래 버튼. 고칠 것이 남아 있으면 목록을 보여 주고 한 번 더 묻습니다." },
  ],
});

shotSlide({
  title: "검수를 통과하지 못했을 때", sub: "상담 윤리·표현 검수에서 지적이 나오면 '게시 전 확인'이 주황색으로 바뀝니다",
  shot: "08_wb_fail",
  items: [
    { at: [153, 352], h: "게시 전 확인 — 고칠 것", d: "예: 효과를 단정하는 표현. 지적 내용은 화면 아래 '검수 결과'에 자세히 나옵니다." },
    { at: [160, 573], h: "본문에서 직접 고치기", d: "문장을 고쳐 [본문 저장]하거나, '수정 요청'에 '효과 단정 표현을 빼 줘'처럼 적습니다." },
    { h: "금지 표현 기준", d: "치료·완치·효과 보장, 낙인·공포 표현, 개별 내담자 사례는 쓰지 않습니다(브랜드 킷 금기어·가드레일)." },
    { h: "그래도 대기열에 넣으려면", d: "확인 창에서 [그래도 넣기]를 누를 수 있지만, 게시 전 사람이 꼭 확인합니다." },
  ],
});

// =============================== 3. 카드·쇼츠 ===============================
section("카드뉴스 · 쇼츠", "왼쪽 큰 미리보기를 보며 ①카드 만들기 → ②한 장씩 다듬기 → ③쇼츠 영상", 3);

shotSlide({
  title: "① 카드 만들기", sub: "카드·쇼츠 메뉴 — 종류·디자인만 고르고 한 번 누르면 됩니다",
  shot: "10_studio",
  items: [
    { at: [307, 53], h: "카드·쇼츠를 만들 글", d: "워크벤치에서 보던 글이 그대로 열립니다." },
    { at: [340, 373], h: "큰 미리보기", d: "실제 크기 그대로의 카드. 아래 화살표·썸네일로 넘겨 봅니다." },
    { at: [187, 787], h: "폴더 열기 · 다른 곳에 저장", d: "완성된 PNG를 바로 꺼내 인스타그램 등에 올립니다." },
    { at: [600, 179], h: "카드 종류 · 디자인", d: "종류(공감 사례형·교육 안내형 등)를 고르면 맞는 디자인이 따라옵니다." },
    { at: [600, 237], h: "배색 · 카드 크기", d: "브랜드 색 배색 5가지, 크기 4:5(기본)·3:4·1:1·9:16." },
    { at: [640, 521], h: "카드 장수 → [🃏 카드 만들기]", d: "1~8장. 다시 만들면 고친 카드가 바뀐다고 먼저 묻습니다." },
  ],
});

shotSlide({
  title: "② 한 장씩 다듬기", sub: "왼쪽에서 카드를 고르고, 오른쪽에서 글자·사진을 고친 뒤 [적용]",
  shot: "11_studio2",
  items: [
    { at: [587, 192], h: "제목", d: "*강조*로 감싼 말은 색으로 눈에 띕니다." },
    { at: [587, 253], h: "내용", d: "줄바꿈으로 항목을 나눕니다(목록 카드는 한 줄 = 한 칸)." },
    { at: [587, 312], h: "아래 한 줄", d: "카드 아래 요약 띠에 들어갈 문장." },
    { at: [587, 365], h: "사진", d: "(자동) · 올린 사진 중 하나 · 사진 없음 — 고른 카드는 자동 배치가 건드리지 않습니다." },
    { at: [587, 417], h: "말로 고치기", d: "'제목을 더 짧게', '배경을 연한 파란색으로'처럼 적고 [요청 실행](AI 글쓰기 모델 필요)." },
    { at: [587, 519], h: "[적용 (이 카드 다시 그리기)]", d: "그 카드만 다시 그립니다. 다른 메뉴로 가면 고친 글자는 자동 저장됩니다." },
  ],
});

shotSlide({
  title: "③ 쇼츠 영상", sub: "카드에서 대본을 만들고, 음성·자막·움직임을 붙여 9:16 영상으로",
  shot: "12_studio3",
  items: [
    { at: [587, 443], h: "목표 길이 · 목소리", d: "길이는 설정의 기본값으로 시작합니다. 목소리는 차분한 목소리 등에서 고릅니다." },
    { at: [587, 500], h: "사진 움직임 · 글자 움직임 · 장면 전환", d: "사진은 사진 칸 안에서만 움직이고, 목록 칸은 읽는 순간 하나씩 나타납니다." },
    { at: [593, 649], h: "AI로 내레이션 다듬기", d: "켜면 듣기 좋게 다듬습니다(AI 비용). 끄면 카드 문장 그대로." },
    { at: [593, 693], h: "[카드에서 대본 만들기] → 대본 보기·고치기", d: "문장을 중간에서 자르지 않고, 길면 알려 줍니다." },
    { at: [593, 799], h: "[🎬 쇼츠 영상 만들기]", d: "음성 예상 비용을 확인한 뒤 만듭니다(몇 분)." },
  ],
  tip: "카드를 고친 뒤에는 '카드가 바뀌었습니다' 안내가 뜹니다. 대본을 다시 만들고 영상을 만드세요.",
});

shotSlide({
  title: "디자인 고르기 — 두 가지 계열", sub: "공감·회복은 '온자람 에디토리얼', 전문·신뢰(기관 안내)는 '온자람 신뢰 리포트'",
  shot: "14_studio_report",
  items: [
    { at: [893, 179], h: "디자인 목록", d: "에디토리얼 4종(기본·어두운 배경·세리프 제목·큰 사진)과 신뢰 리포트 2종(크림·네이비)." },
    { at: [340, 400], h: "신뢰 리포트", d: "네이비 띠·번호 표 목록·라벨 표. 교육·특강 안내, 상담·신청 절차 카드의 기본값입니다." },
    { h: "예전 디자인", d: "시험용으로 만든 예전 디자인은 숨겨 두었습니다. 필요하면 설정 → 카드 종류·디자인 → '이전 디자인도 보기'." },
    { h: "쇼츠도 같은 디자인", d: "두 계열 모두 쇼츠를 같은 색·글꼴의 9:16 전용 화면으로 만듭니다." },
  ],
});

// 결과물 예시
{
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: secTitle });
  s.addText("결과물 예시 — 카드뉴스", { placeholder: "title" });
  s.addText("위: 온자람 에디토리얼(공감·회복) · 아래: 온자람 신뢰 리포트(전문·신뢰). AI 없이 규칙으로 기획한 예시입니다", { placeholder: "body" });
  const ew = 12.3, eh = ew * 540 / 2240;
  s.addImage({ path: IMG("cards_ed"), x: 0.5, y: 1.6, w: ew, h: eh, objectName: "에디토리얼 카드 예시", altText: "에디토리얼 카드 5장" });
  const rw = ew * (4 * 452 - 20) / 2240, rh = eh;
  s.addImage({ path: IMG("cards_rp"), x: 0.5, y: 1.75 + eh, w: rw, h: rh, objectName: "신뢰 리포트 카드 예시", altText: "신뢰 리포트 카드 4장" });
  s.addText([
    { text: "AI 글쓰기 모델을 연결하면", options: { bold: true, color: C.text2, breakLine: true } },
    { text: "카드 문장을 짧고 읽기 좋게 새로 써 줍니다. 위 예시는 블로그 문장을 그대로 나눠 담은 것입니다.", options: { color: "3F4A43" } },
  ], { x: 0.6 + rw + 0.3, y: 1.85 + eh, w: 12.3 - rw - 0.4, h: rh - 0.2, fontSize: 13, valign: "middle", margin: 0, isTextBox: true, objectName: "예시 설명" });
}
{
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: secTitle });
  s.addText("결과물 예시 — 쇼츠 장면", { placeholder: "title" });
  s.addText("지금 읽는 문장이 아래 큰 자막으로, 목록은 하나씩, 사진은 사진 칸 안에서만 움직입니다", { placeholder: "body" });
  const a = 12.3, ah = a * 480 / 1950;
  s.addImage({ path: IMG("editorial_shorts_scenes"), x: 0.5, y: 1.55, w: a, h: ah, objectName: "에디토리얼 쇼츠 장면", altText: "에디토리얼 쇼츠 장면 예시" });
  const b = a * 1540 / 1950 * 0.86, bh = b * 533 / 1540;
  s.addImage({ path: IMG("report_shorts_scenes"), x: 0.5, y: 1.7 + ah, w: b, h: bh, objectName: "신뢰 리포트 쇼츠 장면", altText: "신뢰 리포트 쇼츠 장면 예시" });
  s.addText([
    { text: "위·아래 빈 띠", options: { bold: true, color: C.text2, breakLine: true } },
    { text: "유튜브·인스타 버튼에 가려지는 자리라 일부러 비워 둡니다.", options: { color: "3F4A43", breakLine: true } },
    { text: " ", options: { breakLine: true } },
    { text: "로컬에서 확인할 것", options: { bold: true, color: C.text2, breakLine: true } },
    { text: "실제 음성 길이와 자막이 잘 맞는지 휴대폰으로 한 번 재생해 보세요.", options: { color: "3F4A43" } },
  ], { x: 0.8 + b, y: 1.8 + ah, w: 12.3 - b - 0.4, h: bh - 0.2, fontSize: 13, valign: "middle", margin: 0, isTextBox: true, objectName: "쇼츠 설명" });
}

// =============================== 4. 게시·관리 ===============================
section("게시와 관리", "네이버 반자동 게시 → 보관함에서 정리 → 실수 방지 장치", 4);

shotSlide({
  title: "네이버 블로그 반자동 게시", sub: "[지금 게시]를 누르면 크롬 창에 제목·본문·사진이 들어갑니다. [발행]은 그 창에서 직접",
  shot: "18_publish",
  items: [
    { at: [1053, 149], h: "네이버 로그인", d: "처음 한 번 로그인하면 이 PC에 저장됩니다. 언제든 [로그아웃]으로 지울 수 있습니다." },
    { at: [187, 252], h: "게시 대기 · 게시 완료", d: "워크벤치에서 '게시 대기열로' 보낸 글이 여기 모입니다." },
    { at: [173, 408], h: "콘텐츠 보기", d: "올릴 내용을 마지막으로 확인합니다." },
    { at: [333, 473], h: "[🚀 지금 게시]", d: "크롬 창이 열리고 자동으로 입력됩니다. 내용을 보고 그 창에서 [발행]." },
    { at: [693, 473], h: "[✅ 수동으로 완료]", d: "직접 붙여 넣어 올렸다면 눌러서 정리합니다." },
    { at: [173, 517], h: "네이버 글 주소", d: "넣어 두면 대시보드·보관함에서 바로 열 수 있습니다." },
  ],
});

shotSlide({
  title: "보관함 — 지난 글 찾기와 정리", sub: "작업 목록에는 최근 15개만 보입니다. 나머지는 여기서 검색합니다",
  shot: "15_library",
  items: [
    { at: [160, 124], h: "검색", d: "제목·메모·본문에서 찾습니다." },
    { at: [440, 124], h: "필터 · 정렬", d: "상태·보관 여부·브랜드 킷·라벨·내용(카드·쇼츠 유무) · 최근 만든 순 등." },
    { at: [167, 231], h: "게시 후 30일 지난 글 일괄 보관", d: "목록을 가볍게 합니다. 지우지 않고 '보관'만 합니다." },
    { at: [147, 264], h: "용량", d: "카드 그림·쇼츠 영상·AI 이미지·사진이 차지하는 크기." },
    { at: [1053, 327], h: "워크벤치 · 카드·쇼츠로 이동", d: "그 글을 바로 엽니다." },
    { at: [1219, 327], h: "⋮ 더 보기", d: "보관 · 라벨 · 용량 정리(카드 PNG·영상만) · 삭제." },
  ],
});

{
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: secTitle });
  s.addText("실수 방지 — 삭제 확인과 저장 안 한 수정", { placeholder: "title" });
  s.addText("되돌릴 수 없는 일은 항상 한 번 더 묻습니다", { placeholder: "body" });
  const w = 6.0, h = w * 860 / 1280;
  [["30_dlg_delete", "글 삭제", "[보관]은 목록에서만 치우고 보관함에서 되살릴 수 있습니다. [삭제]는 되돌릴 수 없으며, 체크하면 그 글의 카드 그림·쇼츠 영상 파일도 함께 지웁니다."],
   ["31_dlg_unsaved", "저장 안 한 수정", "본문·메모·브랜드 킷을 고친 채 다른 메뉴로 가면 고친 곳을 알려 주고 '저장하고 이동 / 저장 안 하고 이동 / 취소'를 묻습니다. 카드·쇼츠의 글자는 자동 저장됩니다."]]
    .forEach(([img, head, text], i) => {
      const x = 0.5 + i * (w + 0.3);
      s.addImage({ path: IMG(img), x, y: 1.55, w, h, objectName: head + " 화면", altText: head + " 확인 창" });
      s.addShape(pres.shapes.RECTANGLE, { x, y: 1.55, w, h, fill: { type: "none" }, line: { color: "C9D3CC", width: 0.75 } });
      s.addText([{ text: head, options: { bold: true, fontSize: 15, color: C.text2, breakLine: true } }, { text, options: { fontSize: 12, color: "3F4A43" } }],
        { x, y: 1.7 + h, w, h: 1.25, valign: "top", margin: 0, isTextBox: true, objectName: head + " 설명" });
    });
}

// =============================== 5. 설정·문제 해결 ===============================
section("설정 더 보기 · 문제 해결", "카드 종류·디자인, 사용량, PC 옮기기, 자주 묻는 질문", 5);

shotSlide({
  title: "카드 종류·디자인 관리", sub: "설정 → 🃏 카드 종류·디자인 — 장 구성과 디자인을 우리 회사에 맞게",
  shot: "21_set_cards",
  items: [
    { at: [160, 391], h: "카드 종류", d: "장 구성·작성 틀·AI 지침을 담은 묶음(공감 사례형·마음 체크리스트형 등)." },
    { at: [1067, 397], h: "미리보기", d: "샘플 문구로 실제 모양을 그려 봅니다. 디자인·배색을 바꿔 볼 수 있습니다." },
    { at: [1157, 400], h: "복제해서 수정", d: "내장 종류는 복제한 뒤 고치고, 상태를 '사용'으로 바꾸면 카드·쇼츠 목록에 나옵니다." },
    { at: [1160, 321], h: "JSON 가져오기", d: "다른 PC에서 만든 종류를 파일로 가져옵니다." },
    { h: "이전 디자인도 보기", d: "아래 '디자인' 칸의 스위치. 기본은 꺼져 있어 온자람 디자인만 보입니다." },
  ],
});

shotSlide({
  title: "AI 사용 금액 보기", sub: "설정 → 📈 사용량 — 등록한 단가와 환율로 계산한 예상치입니다",
  shot: "24_set_usage",
  items: [
    { at: [173, 427], h: "오늘 · 이번 달 · 전체 · 글 1건당", d: "실제 청구액은 Google·OpenAI 등 각 콘솔에서 확인하세요." },
    { at: [167, 513], h: "환율 · 월 예산", d: "예산을 넣으면 70%·90%에 이르렀을 때 대시보드·워크벤치에 알려 줍니다(생성을 막지는 않음)." },
    { at: [153, 685], h: "모델별 사용량", d: "어떤 모델에 얼마가 쓰였는지. 단가가 없는 모델은 '단가 미등록'으로 따로 셉니다." },
  ],
});

shotSlide({
  title: "데이터 옮기기 — 다른 PC로", sub: "설정 → 📦 데이터 옮기기 — 세팅과 작업 내용을 .osmu 파일 하나로",
  shot: "25_set_transfer",
  items: [
    { at: [171, 400], h: "옮길 항목 고르기", d: "브랜드 킷·회사 설정·모델 등록·AI 비용 설정·키워드 측정값·제목 이력." },
    { at: [171, 501], h: "API 키 (선택)", d: "체크하면 비밀번호로 암호화해 담습니다. 비밀번호는 파일과 다른 경로로 알려 주세요." },
    { at: [171, 751], h: "작업 내용", d: "글·사진·카드 그림·쇼츠 영상까지. 받는 PC에 없는 글만 더하고, 같은 글은 그대로 둡니다." },
    { at: [167, 805], h: "비밀번호 → 내보내기", d: "받는 PC에서는 같은 탭 아래 [📂 .osmu 파일 열기]로 가져옵니다." },
  ],
  tip: ".osmu 파일과 비밀번호를 함께 가진 사람은 키를 쓸 수 있습니다. 파일은 안전하게 전달하세요.",
});

// 자주 묻는 질문
{
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: secTitle });
  s.addText("자주 묻는 질문", { placeholder: "title" });
  s.addText("막히면 먼저 대시보드 맨 위 '시작 점검'을 보세요", { placeholder: "body" });
  const qa = [
    ["[만들기]가 회색이에요", "메모를 한 글자 이상 쓰면 켜집니다. 이미 '생성 중'인 글도 끝날 때까지 꺼져 있습니다."],
    ["AI 이미지·요청 실행 버튼이 꺼져 있어요", "설정 → AI 연결·모델에서 이미지 생성 모델(또는 글쓰기 모델)이 지정됐는지 확인합니다."],
    ["쇼츠 음성이 기계음 같아요", "'음성 내레이션' 모델이 없으면 무료 음성으로 대신합니다. 간편 설정에서 음성 모델을 적용하세요."],
    ["쇼츠가 목표 길이보다 길어요", "문장을 자르지 않기 때문입니다. 목표 길이를 늘리거나 'AI로 내레이션 다듬기'를 켜세요."],
    ["카드에 올린 사진이 안 들어가요", "디자인·종류마다 사진 칸 수가 정해져 있습니다. ② 다듬기의 '사진'에서 카드마다 고르세요."],
    ["작업하던 글이 안 보여요", "목록에는 최근 15개만 나옵니다. 📚 보관함에서 검색하세요(보관한 글은 '보관 필터')."],
  ];
  qa.forEach(([q, a], i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.5 + col * 6.25, y = 1.6 + row * 1.75;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 6.0, h: 1.55, rectRadius: 0.08, fill: { color: C.background2 }, line: { color: "D5E0D8", width: 0.75 }, objectName: `질문 상자 ${i + 1}` });
    s.addShape(pres.shapes.OVAL, { x: x + 0.2, y: y + 0.22, w: 0.42, h: 0.42, fill: { color: C.accent1 }, line: { color: C.accent1 } });
    s.addText("Q", { x: x + 0.2, y: y + 0.22, w: 0.42, h: 0.42, fontSize: 14, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText([{ text: q, options: { bold: true, fontSize: 15, color: C.text2, breakLine: true } }, { text: a, options: { fontSize: 12, color: "3F4A43" } }],
      { x: x + 0.8, y: y + 0.15, w: 5.0, h: 1.3, valign: "top", margin: 0, paraSpaceAfter: 4, isTextBox: true, objectName: `질문 ${i + 1}` });
  });
}

// 하루 작업 순서
{
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: secTitle });
  s.addText("정리 — 글 한 편 작업 순서", { placeholder: "title" });
  s.addText("익숙해지면 메모부터 게시까지 한 화면 흐름으로 끝납니다", { placeholder: "body" });
  const steps = [
    ["워크벤치 [➕ 새 콘텐츠]", "브랜드 킷·글 유형을 고르고 메모를 씁니다. 정확해야 하는 값은 공지·서비스 칸에."],
    ["[🪄 만들기]", "블로그·카드뉴스·쇼츠 중 필요한 것만 체크합니다."],
    ["게시 전 확인 → 본문 다듬기", "주황 항목을 고치고 [본문 저장]. 필요하면 '수정 요청'."],
    ["카드·쇼츠에서 다듬기", "카드를 넘겨 보며 글자·사진을 고치고 [적용], 쇼츠 대본 → 영상."],
    ["게시 대기열 → 네이버 게시", "[지금 게시] 후 크롬 창에서 직접 [발행]. 글 주소를 남겨 둡니다."],
    ["보관함에서 정리", "게시 후 30일 지난 글은 일괄 보관, 필요하면 용량 정리."],
  ];
  steps.forEach(([h, d], i) => {
    const y = 1.6 + i * 0.88;
    s.addShape(pres.shapes.OVAL, { x: 0.7, y, w: 0.6, h: 0.6, fill: { color: i === 4 ? C.accent2 : C.accent1 }, line: { color: C.background1 }, objectName: `순서 ${i + 1}` });
    s.addText(String(i + 1), { x: 0.7, y, w: 0.6, h: 0.6, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText([{ text: h, options: { bold: true, fontSize: 16, color: C.text2, breakLine: true } }, { text: d, options: { fontSize: 13, color: "3F4A43" } }],
      { x: 1.55, y: y - 0.06, w: 7.0, h: 0.8, valign: "middle", margin: 0, isTextBox: true, objectName: `순서 설명 ${i + 1}` });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 9.0, y: 1.6, w: 3.85, h: 5.15, rectRadius: 0.12, fill: { color: C.text2 }, line: { color: C.text2 }, objectName: "꼭 지킬 것 상자" });
  s.addText([
    { text: "꼭 지킬 것", options: { bold: true, fontSize: 18, color: C.background1, breakLine: true } },
    { text: " ", options: { fontSize: 8, breakLine: true } },
    { text: "개별 내담자의 나이·시기·상황은 쓰지 않습니다", options: { bullet: true, breakLine: true } },
    { text: "치료·완치·효과 보장 표현은 쓰지 않습니다", options: { bullet: true, breakLine: true } },
    { text: "가격·인증·연락처는 브랜드 킷의 사실만", options: { bullet: true, breakLine: true } },
    { text: "사람이 나온 사진은 동의를 확인한 것만", options: { bullet: true, breakLine: true } },
    { text: "[발행]은 사람이 마지막으로 확인하고 누릅니다", options: { bullet: true } },
  ], { x: 9.3, y: 1.85, w: 3.3, h: 4.7, fontSize: 13, color: C.background1, valign: "top", margin: 0, paraSpaceAfter: 8, isTextBox: true, objectName: "꼭 지킬 것" });
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
