"""앱 화면 글꼴(flet_app/assets/fonts): 파일이 있고 OFL 라이선스 원문이 같이 있어야 한다."""
import os

from flet_app.theme import APP_FONT, APP_FONTS, build_theme

ASSETS = os.path.join(os.path.dirname(__file__), "..", "flet_app", "assets")


def test_app_font_is_bundled_with_its_license():
    rel = APP_FONTS[APP_FONT]
    assert os.path.isfile(os.path.join(ASSETS, rel))
    lic = os.path.join(ASSETS, "fonts", f"OFL-{APP_FONT}.txt")
    assert "SIL OPEN FONT LICENSE" in open(lic, encoding="utf-8").read().upper()
    assert build_theme().font_family == APP_FONT
