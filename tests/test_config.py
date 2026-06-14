from app.core.config import AppSettings


def test_app_settings_defaults():
    s = AppSettings()
    assert s.name == "arch-fastapi"
    assert s.env == "dev"
    assert s.host == "0.0.0.0"
    assert s.port == 8000
    assert s.debug is False
    assert s.log_level == "INFO"
