import os

import pytest

from japan_reader.clients.karakeep import KarakeepClient
from japan_reader.clients.trilium import TriliumClient
from japan_reader.config import Settings
from japan_reader.media.audio import extract_audio
from japan_reader.media.downloaders import YtDlpDownloader
from japan_reader.sources import Platform
from japan_reader.stages.transcribe import WhisperTranscriber
from japan_reader.trilium_layout import GEO_MAP_TEMPLATE, init_layout

pytestmark = pytest.mark.integration


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"falta la variable {name}")
    return value


@pytest.fixture
def live() -> Settings:
    return Settings()


def test_trilium_test_tree_and_geomap(live):
    label = _env("JR_TEST_ROOT_LABEL")
    trilium = TriliumClient(live.trilium_url, live.trilium_etapi_token)

    layout = init_layout(trilium, label)

    mapa = trilium.get_note(layout.mapa)
    assert mapa.type == "book"
    assert GEO_MAP_TEMPLATE in mapa.relations("template")


def test_karakeep_test_list_is_readable(live):
    list_id = _env("JR_TEST_LIST_ID")
    list(KarakeepClient(live.karakeep_url, live.karakeep_api_key).list_bookmarks(list_id))


def test_ytdlp_downloads_public_short(tmp_path):
    media = YtDlpDownloader(None, 900).download(_env("JR_TEST_SHORT_URL"), Platform.YOUTUBE, tmp_path)
    assert media.videos and media.videos[0].stat().st_size > 0


def test_whisper_transcribes_short(tmp_path, live):
    media = YtDlpDownloader(None, 900).download(_env("JR_TEST_SHORT_URL"), Platform.YOUTUBE, tmp_path / "raw")
    audio = extract_audio(media.videos[0], tmp_path / "a.wav")
    model = os.environ.get("JR_TEST_WHISPER_MODEL", "small")
    text, _ = WhisperTranscriber(model, "int8", live.whisper_download_root, 6).transcribe(audio)
    assert text.strip()
