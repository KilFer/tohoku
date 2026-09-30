from pathlib import Path

import pytest

from tohoku.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        karakeep_url="http://karakeep.test",
        karakeep_api_key="kk",
        trilium_url="http://trilium.test",
        trilium_etapi_token="tt",
        openrouter_api_key="or",
        openrouter_model="vision/model",
        openrouter_text_model="text/model",
        google_places_api_key="gp",
        data_dir=tmp_path / "data",
        whisper_download_root=tmp_path / "models",
        destinos_file=Path(__file__).parent / "fixtures" / "destinos.yaml",
    )
