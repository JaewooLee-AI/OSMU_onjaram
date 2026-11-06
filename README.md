# 온자람 OSMU

주식회사 온자람(사회적기업)을 위한 원소스 멀티유즈 콘텐츠 앱. 메모와 사진 한 벌에서 네이버 블로그·카드뉴스·쇼츠
콘텐츠를 만들고 온자람 브랜드 규칙(보이스 트랙, 금기어, 비식별 원칙)으로 검수합니다. Windows 설치형 데스크톱 앱(Flet)입니다.

- 설계: [docs/설계안_온자람_OSMU_v0.1.md](docs/설계안_온자람_OSMU_v0.1.md)
- 개발 규칙: [CLAUDE.md](CLAUDE.md)

```bash
pip install -r requirements.txt
python flet_app/main.py
python -m pytest tests
```

현재 상태: 블로그 파이프라인(OSMU_cjc 기반)이 온자람 킷으로 동작하도록 정리 중입니다. 카드뉴스·쇼츠 이식은 다음 단계입니다.
API 키는 앱 ⚙️ 설정에서 입력하며 저장소에 포함되지 않습니다.
