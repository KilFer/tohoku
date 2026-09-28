import pytest

from japan_reader.sources import ContentHint, Platform, canonical_url, classify_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/shorts/abc123", (Platform.YOUTUBE, ContentHint.VIDEO)),
        ("https://youtube.com/watch?v=abc123", (Platform.YOUTUBE, ContentHint.VIDEO)),
        ("https://youtu.be/abc123", (Platform.YOUTUBE, ContentHint.VIDEO)),
        ("https://m.youtube.com/shorts/abc123?feature=share", (Platform.YOUTUBE, ContentHint.VIDEO)),
        ("https://www.instagram.com/reel/C1x2y3/", (Platform.INSTAGRAM, ContentHint.VIDEO)),
        ("https://www.instagram.com/reels/C1x2y3/", (Platform.INSTAGRAM, ContentHint.VIDEO)),
        ("https://www.instagram.com/some.user/reel/C1x2y3/", (Platform.INSTAGRAM, ContentHint.VIDEO)),
        ("https://instagram.com/p/C9z8/?igsh=xyz", (Platform.INSTAGRAM, ContentHint.POST)),
        ("https://www.instagram.com/some_user/p/C9z8/", (Platform.INSTAGRAM, ContentHint.POST)),
        ("https://www.tiktok.com/@u/video/1", None),
        ("https://www.instagram.com/some_user/", None),
    ],
)
def test_classify_url(url, expected):
    assert classify_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://youtu.be/abc123", "https://www.youtube.com/watch?v=abc123"),
        ("https://m.youtube.com/shorts/abc123?feature=share", "https://www.youtube.com/shorts/abc123"),
        ("https://www.youtube.com/watch?v=abc123&t=10", "https://www.youtube.com/watch?v=abc123"),
        ("https://instagram.com/p/C9z8/?igsh=xyz", "https://www.instagram.com/p/C9z8/"),
        ("https://www.instagram.com/u/reels/C1x2y3", "https://www.instagram.com/reel/C1x2y3/"),
    ],
)
def test_canonical_url(url, expected):
    assert canonical_url(url) == expected
