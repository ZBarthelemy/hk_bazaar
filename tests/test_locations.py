"""HK location normalization tests."""

from hk_bazaar.utils.hk_locations import normalize_location


def test_wong_tai_sin() -> None:
    raw, district, region = normalize_location("Pickup at Wong Tai Sin MTR")
    assert district == "Wong Tai Sin"
    assert region == "Kowloon"


def test_kennedy_town() -> None:
    _, district, region = normalize_location("Kennedy Town pickup")
    assert district == "Central and Western"
    assert region == "Hong Kong Island"


def test_chinese_district() -> None:
    _, district, _ = normalize_location("觀塘地鐵站面交")
    assert district == "Kwun Tong"