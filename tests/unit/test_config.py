import pytest
from pydantic import ValidationError

from japan_reader.config import Settings, Thresholds

REQUIRED = {
    "KARAKEEP_URL": "http://kk",
    "KARAKEEP_API_KEY": "k",
    "KARAKEEP_LIST_ID": "L",
    "TRILIUM_URL": "http://tr",
    "TRILIUM_ETAPI_TOKEN": "t",
    "OPENROUTER_API_KEY": "o",
    "OPENROUTER_MODEL": "vision/model",
    "GOOGLE_PLACES_API_KEY": "g",
}


def _set_required(monkeypatch):
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)


def test_settings_read_from_environment_with_defaults(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("REEL_KEYFRAMES_ENABLED", "false")

    s = Settings(_env_file=None)

    assert s.reel_keyframes_enabled is False
    assert s.whisper_model == "large-v3"
    assert s.whisper_compute_type == "int8"
    assert (s.keyframes_max, s.post_images_max, s.image_max_side) == (6, 10, 1024)
    assert s.max_video_duration_min == 15
    assert s.poll_interval_minutes == 10
    assert s.places_daily_limit == 150
    assert s.trilium_root_label == "jrRoot"
    assert s.text_model == "vision/model"
    assert s.thresholds == Thresholds(
        japan_min=0.4, japan_review=0.7, item_review=0.7, cosa_duplicate=0.85
    )


def test_text_model_can_be_overridden(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("OPENROUTER_TEXT_MODEL", "cheap/text")

    assert Settings(_env_file=None).text_model == "cheap/text"


def test_missing_required_setting_fails(monkeypatch):
    for key in REQUIRED:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
