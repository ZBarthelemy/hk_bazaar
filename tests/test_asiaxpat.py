"""asiaXPAT scraper parser tests."""

from pathlib import Path

from hk_bazaar.scrapers.asiaxpat import enrich_from_detail, index_url, parse_index_page

FIXTURES = Path(__file__).parent / "fixtures"


def test_index_url_includes_search_query() -> None:
    assert index_url("https://hongkong.asiaxpat.com", page=1, query="iphone") == (
        "https://hongkong.asiaxpat.com/classifieds?q=iphone"
    )
    assert index_url("https://hongkong.asiaxpat.com/", page=2, query="iphone") == (
        "https://hongkong.asiaxpat.com/classifieds?q=iphone&page=2"
    )


def test_parse_index_page() -> None:
    html = (FIXTURES / "asiaxpat_index.html").read_text()
    listings = parse_index_page(html, base_url="https://hongkong.asiaxpat.com")
    assert len(listings) == 2
    ids = {item.external_id for item in listings}
    assert ids == {"9991", "9992"}
    free = next(item for item in listings if item.external_id == "9992")
    assert free.price == 0.0


def test_enrich_from_detail() -> None:
    index_html = (FIXTURES / "asiaxpat_index.html").read_text()
    stub = parse_index_page(index_html, base_url="https://hongkong.asiaxpat.com")[0]
    detail_html = (FIXTURES / "asiaxpat_detail.html").read_text()
    enriched = enrich_from_detail(stub, detail_html, base_url="https://hongkong.asiaxpat.com")
    assert enriched.price == 500.0
    assert enriched.category_raw == "electronics"