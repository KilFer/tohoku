from builders import make_ctx, make_fetch
from japan_reader.stages.transcribe import TranscribeStage


class FakeTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio):
        self.calls.append(audio.name)
        return f"texto de {audio.name}", "ja"


def _ctx_with_audio(tmp_path, names, **fetch_kwargs):
    ctx = make_ctx(tmp_path)
    for name in names:
        path = ctx.workdir / "audio" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"wav")
    ctx.results["fetch"] = make_fetch(audio_files=[f"audio/{n}" for n in names], **fetch_kwargs)
    return ctx


def test_manual_subtitles_are_used_when_long_enough(tmp_path):
    transcriber = FakeTranscriber()
    ctx = _ctx_with_audio(tmp_path, ["00.wav"], subtitles="uno dos tres cuatro cinco seis")

    result = TranscribeStage(transcriber).run(ctx)

    assert result.origin == "subtitulos"
    assert result.text == "uno dos tres cuatro cinco seis"
    assert transcriber.calls == []
    assert not (ctx.workdir / "audio" / "00.wav").exists()


def test_whisper_when_no_useful_subtitles(tmp_path):
    ctx = _ctx_with_audio(tmp_path, ["00.wav"], subtitles="hola")

    result = TranscribeStage(FakeTranscriber()).run(ctx)

    assert result.origin == "whisper"
    assert result.text == "texto de 00.wav"
    assert result.language == "ja"
    assert not (ctx.workdir / "audio" / "00.wav").exists()


def test_carousel_with_several_videos_is_labelled(tmp_path):
    ctx = _ctx_with_audio(tmp_path, ["00.wav", "01.wav"])

    result = TranscribeStage(FakeTranscriber()).run(ctx)

    assert result.text == "[Elemento 1] texto de 00.wav\n[Elemento 2] texto de 01.wav"


def test_no_audio_is_skipped(tmp_path):
    ctx = make_ctx(tmp_path, fetch=make_fetch(images=["images/00.jpg"]))
    result = TranscribeStage(FakeTranscriber()).run(ctx)
    assert result.origin == "none" and result.text == ""
