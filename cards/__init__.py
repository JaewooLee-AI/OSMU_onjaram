"""카드뉴스 엔진 — ammasarang_card_shorts의 렌더러를 온자람 앱(SQLite 브랜드 킷)에 맞게 옮긴 것입니다.

- schema.py: 스토리보드(카드·쇼츠 장면) 스키마
- card_renderer.py: Pillow 기반 4:5(1080x1350) 카드 렌더러
- fonts.py: 무료(OFL) 글꼴 — cards/fonts, 직접 넣은 글꼴은 데이터 폴더의 fonts/custom
- design_templates.py: 카드 디자인 템플릿(레이아웃·색·글꼴)
- brand.py: DB 브랜드 킷 → 렌더러가 쓰는 BrandKit
"""
