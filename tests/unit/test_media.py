from PIL import Image

from helpers import make_image, make_video
from tohoku.media.audio import extract_audio, has_audio, probe_duration
from tohoku.media.images import resize_image
from tohoku.media.keyframes import dedupe_similar, extract_keyframes, pick_evenly
from tohoku.media.subtitles import vtt_to_text


def test_extract_audio(tmp_path):
    video = make_video(tmp_path / "v.mp4")
    wav = extract_audio(video, tmp_path / "out" / "a.wav")
    assert wav is not None and wav.exists()
    assert has_audio(video)
    assert 2.5 <= probe_duration(video) <= 3.5


def test_extract_audio_without_audio_track(tmp_path):
    video = make_video(tmp_path / "v.mp4", with_audio=False)
    assert extract_audio(video, tmp_path / "a.wav") is None


def test_keyframes_one_per_scene(tmp_path):
    video = make_video(tmp_path / "v.mp4", colors=("red", "blue", "green"))
    frames = extract_keyframes(video, tmp_path / "frames", max_frames=6)
    colors = {Image.open(f).convert("RGB").resize((1, 1)).getpixel((0, 0)) for f in frames}
    assert len(frames) == 3
    assert len(colors) == 3


def test_keyframes_static_video_collapses_duplicates(tmp_path):
    video = make_video(tmp_path / "v.mp4", colors=("red",), seconds=3)
    assert len(extract_keyframes(video, tmp_path / "frames", max_frames=6)) == 1


def test_keyframes_respect_max(tmp_path):
    video = make_video(tmp_path / "v.mp4", colors=("red", "blue", "green", "yellow", "white", "black", "purple", "orange"))
    assert len(extract_keyframes(video, tmp_path / "frames", max_frames=4)) == 4


def test_pick_evenly():
    assert pick_evenly(list(range(10)), 3) == [0, 4, 9]
    assert pick_evenly([1, 2], 5) == [1, 2]
    assert pick_evenly([1, 2, 3], 1) == [1]


def test_dedupe_similar(tmp_path):
    a = make_image(tmp_path / "a.png", size=(64, 64), color="red")
    b = make_image(tmp_path / "b.png", size=(64, 64), color="red")
    c = make_image(tmp_path / "c.png", size=(64, 64), color="blue")
    assert dedupe_similar([a, b, c]) == [a, c]


def test_resize_image(tmp_path):
    src = make_image(tmp_path / "big.png", size=(2000, 1500))
    out = resize_image(src, tmp_path / "small" / "x.jpg", 1024)
    with Image.open(out) as im:
        assert im.format == "JPEG"
        assert max(im.size) == 1024


def test_vtt_to_text():
    vtt = """WEBVTT
Kind: captions
Language: es

00:00:00.000 --> 00:00:01.500
Hoy vamos a <c>Fushimi Inari</c>

00:00:01.500 --> 00:00:03.000
Hoy vamos a <c>Fushimi Inari</c>

2
00:03.000 --> 00:04.000
en Kioto
"""
    assert vtt_to_text(vtt) == "Hoy vamos a Fushimi Inari en Kioto"
