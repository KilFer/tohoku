import pytest

from japan_reader.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        karakeep_url="http://karakeep.test",
        karakeep_api_key="kk",
        karakeep_list_id="L1",
        trilium_url="http://trilium.test",
        trilium_etapi_token="tt",
        openrouter_api_key="or",
        openrouter_model="vision/model",
        openrouter_text_model="text/model",
        google_places_api_key="gp",
        data_dir=tmp_path / "data",
        whisper_download_root=tmp_path / "models",
    )
