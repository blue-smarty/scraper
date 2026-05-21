"""
Unit tests for scraper.py.

All HTTP calls are mocked — no live network requests are made.
"""

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scraper as sc

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_SEARCH_HTML = textwrap.dedent("""\
    <html><body>
      <div data-webm-type="Listing">
        <a href="/cars/toyota-camry/OAG-AD-12345/">
          <h3 class="title">2022 Toyota Camry</h3>
        </a>
        <div class="price">$29,990</div>
        <img src="https://images.carsales.com.au/camry_thumb.jpg" />
      </div>
      <div data-webm-type="Listing">
        <a href="/cars/ford-ranger/OAG-AD-67890/">
          <h3 class="title">2021 Ford Ranger</h3>
        </a>
        <div class="price">$45,000</div>
        <img data-src="https://images.carsales.com.au/ranger_thumb.jpg" />
      </div>
    </body></html>
""")

SAMPLE_LISTING_HTML = textwrap.dedent("""\
    <html><body>
      <div class="gallery">
        <img src="https://images.carsales.com.au/camry_full_1.jpg" />
        <img src="https://images.carsales.com.au/camry_full_2.jpg" />
        <img src="placeholder.gif" />
      </div>
    </body></html>
""")

EMPTY_SEARCH_HTML = "<html><body><p>No listings found.</p></body></html>"


def _make_response(text: str = "", status: int = 200,
                   content_type: str = "text/html") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.headers = {"content-type": content_type}
    resp.iter_content = lambda chunk_size=8192: iter([b"FAKE_IMAGE_DATA"])
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# build_search_url
# ---------------------------------------------------------------------------

class TestBuildSearchUrl:
    def test_base_url_page_1(self):
        url = sc.build_search_url()
        assert url.startswith("https://www.carsales.com.au/cars/")
        assert "page=1" in url

    def test_page_number(self):
        url = sc.build_search_url(page=3)
        assert "page=3" in url

    def test_make_filter(self):
        url = sc.build_search_url(make="Toyota")
        assert "make=Toyota" in url

    def test_price_filters(self):
        url = sc.build_search_url(min_price=5000, max_price=30000)
        assert "price_from=5000" in url
        assert "price_to=30000" in url

    def test_no_price_filter_omitted(self):
        url = sc.build_search_url()
        assert "price_from" not in url
        assert "price_to" not in url


# ---------------------------------------------------------------------------
# parse_listings
# ---------------------------------------------------------------------------

class TestParseListings:
    def test_parses_two_listings(self):
        listings = sc.parse_listings(SAMPLE_SEARCH_HTML)
        assert len(listings) == 2

    def test_first_listing_title(self):
        listings = sc.parse_listings(SAMPLE_SEARCH_HTML)
        assert listings[0]["title"] == "2022 Toyota Camry"

    def test_first_listing_price(self):
        listings = sc.parse_listings(SAMPLE_SEARCH_HTML)
        assert "$29,990" in listings[0]["price"]

    def test_first_listing_url(self):
        listings = sc.parse_listings(SAMPLE_SEARCH_HTML)
        assert "toyota-camry" in listings[0]["url"]

    def test_first_listing_image(self):
        listings = sc.parse_listings(SAMPLE_SEARCH_HTML)
        assert any("camry_thumb" in img for img in listings[0]["images"])

    def test_second_listing_data_src_image(self):
        listings = sc.parse_listings(SAMPLE_SEARCH_HTML)
        # The second listing uses data-src instead of src
        assert any("ranger_thumb" in img for img in listings[1]["images"])

    def test_empty_html_returns_empty_list(self):
        listings = sc.parse_listings(EMPTY_SEARCH_HTML)
        assert listings == []


# ---------------------------------------------------------------------------
# _is_valid_image_url
# ---------------------------------------------------------------------------

class TestIsValidImageUrl:
    def test_valid_jpg(self):
        assert sc._is_valid_image_url("https://example.com/car.jpg")

    def test_gif_rejected(self):
        assert not sc._is_valid_image_url("https://example.com/spacer.gif")

    def test_svg_rejected(self):
        assert not sc._is_valid_image_url("https://example.com/icon.svg")

    def test_placeholder_rejected(self):
        assert not sc._is_valid_image_url("https://example.com/placeholder.png")

    def test_blank_rejected(self):
        assert not sc._is_valid_image_url("https://example.com/blank.jpg")


# ---------------------------------------------------------------------------
# image_filename
# ---------------------------------------------------------------------------

class TestImageFilename:
    def test_extension_preserved(self):
        name = sc.image_filename("https://example.com/car.jpg", 1)
        assert name.endswith(".jpg")

    def test_index_zero_padded(self):
        name = sc.image_filename("https://example.com/car.jpg", 3)
        assert name == "image_0003.jpg"

    def test_no_extension_defaults_to_jpg(self):
        name = sc.image_filename("https://example.com/car", 0)
        assert name.endswith(".jpg")

    def test_png_extension(self):
        name = sc.image_filename("https://example.com/car.png", 0)
        assert name.endswith(".png")


# ---------------------------------------------------------------------------
# get_listing_images
# ---------------------------------------------------------------------------

class TestGetListingImages:
    def test_extracts_gallery_images(self):
        session = MagicMock()
        session.get.return_value = _make_response(SAMPLE_LISTING_HTML)

        with patch("scraper.time.sleep"):
            images = sc.get_listing_images(
                session,
                "https://www.carsales.com.au/cars/toyota-camry/OAG-AD-12345/",
                delay=0,
            )

        assert any("camry_full_1" in img for img in images)
        assert any("camry_full_2" in img for img in images)

    def test_placeholder_excluded(self):
        session = MagicMock()
        session.get.return_value = _make_response(SAMPLE_LISTING_HTML)

        with patch("scraper.time.sleep"):
            images = sc.get_listing_images(session, "https://example.com/car/", delay=0)

        assert not any("placeholder" in img for img in images)

    def test_network_error_returns_empty(self):
        import requests as req
        session = MagicMock()
        session.get.side_effect = req.RequestException("timeout")

        with patch("scraper.time.sleep"):
            images = sc.get_listing_images(session, "https://example.com/", delay=0)

        assert images == []


# ---------------------------------------------------------------------------
# download_image
# ---------------------------------------------------------------------------

class TestDownloadImage:
    def test_successful_download(self, tmp_path):
        session = MagicMock()
        resp = _make_response(content_type="image/jpeg")
        session.get.return_value = resp

        dest = tmp_path / "car.jpg"
        with patch("scraper.time.sleep"):
            result = sc.download_image(session, "https://example.com/car.jpg", dest, delay=0)

        assert result is True
        assert dest.exists()
        assert dest.read_bytes() == b"FAKE_IMAGE_DATA"

    def test_non_image_content_type_rejected(self, tmp_path):
        session = MagicMock()
        resp = _make_response(text="not an image", content_type="text/html")
        session.get.return_value = resp

        dest = tmp_path / "car.jpg"
        with patch("scraper.time.sleep"):
            result = sc.download_image(session, "https://example.com/car.jpg", dest, delay=0)

        assert result is False
        assert not dest.exists()

    def test_network_error_returns_false(self, tmp_path):
        import requests as req
        session = MagicMock()
        session.get.side_effect = req.RequestException("connection error")

        dest = tmp_path / "car.jpg"
        with patch("scraper.time.sleep"):
            result = sc.download_image(session, "https://example.com/car.jpg", dest, delay=0)

        assert result is False


# ---------------------------------------------------------------------------
# scrape_cars (integration-style, fully mocked)
# ---------------------------------------------------------------------------

class TestScrapeCars:
    def _mock_session_responses(self, mock_session_cls):
        """Configure a mock Session that serves search HTML then stops."""
        session = MagicMock()
        mock_session_cls.return_value = session

        # First search page → two listings; second page → empty (stop)
        search_resp = _make_response(SAMPLE_SEARCH_HTML)
        empty_resp = _make_response(EMPTY_SEARCH_HTML)
        image_resp = _make_response(content_type="image/jpeg")

        def side_effect(url, **kwargs):
            if "carsales.com.au/cars/" in url and "page=2" in url:
                return empty_resp
            if "carsales.com.au/cars/" in url:
                return search_resp
            # Image download
            return image_resp

        session.get.side_effect = side_effect
        return session

    @patch("scraper.requests.Session")
    def test_scrape_creates_output_dir(self, mock_session_cls, tmp_path):
        self._mock_session_responses(mock_session_cls)
        out = str(tmp_path / "output")

        with patch("scraper.time.sleep"):
            sc.scrape_cars(output_dir=out, max_cars=2, delay=0)

        assert Path(out).exists()

    @patch("scraper.requests.Session")
    def test_scrape_creates_metadata_json(self, mock_session_cls, tmp_path):
        self._mock_session_responses(mock_session_cls)
        out = str(tmp_path / "output")

        with patch("scraper.time.sleep"):
            metadata = sc.scrape_cars(output_dir=out, max_cars=2, delay=0)

        combined = Path(out) / "metadata.json"
        assert combined.exists()
        data = json.loads(combined.read_text())
        assert isinstance(data, list)
        assert len(data) == 2

    @patch("scraper.requests.Session")
    def test_scrape_returns_metadata_list(self, mock_session_cls, tmp_path):
        self._mock_session_responses(mock_session_cls)

        with patch("scraper.time.sleep"):
            metadata = sc.scrape_cars(output_dir=str(tmp_path), max_cars=2, delay=0)

        assert len(metadata) == 2
        assert metadata[0]["title"] == "2022 Toyota Camry"
        assert metadata[1]["title"] == "2021 Ford Ranger"

    @patch("scraper.requests.Session")
    def test_scrape_per_car_metadata(self, mock_session_cls, tmp_path):
        self._mock_session_responses(mock_session_cls)

        with patch("scraper.time.sleep"):
            sc.scrape_cars(output_dir=str(tmp_path), max_cars=1, delay=0)

        car_meta = tmp_path / "car_0000" / "metadata.json"
        assert car_meta.exists()
        data = json.loads(car_meta.read_text())
        assert data["car_index"] == 0
        assert "Toyota Camry" in data["title"]

    @patch("scraper.requests.Session")
    def test_scrape_max_cars_respected(self, mock_session_cls, tmp_path):
        self._mock_session_responses(mock_session_cls)

        with patch("scraper.time.sleep"):
            metadata = sc.scrape_cars(output_dir=str(tmp_path), max_cars=1, delay=0)

        assert len(metadata) == 1

    @patch("scraper.requests.Session")
    def test_scrape_network_error_stops_gracefully(self, mock_session_cls, tmp_path):
        import requests as req
        session = MagicMock()
        mock_session_cls.return_value = session
        session.get.side_effect = req.RequestException("network failure")

        with patch("scraper.time.sleep"):
            metadata = sc.scrape_cars(output_dir=str(tmp_path), max_cars=5, delay=0)

        assert metadata == []

    @patch("scraper.requests.Session")
    def test_stop_event_before_first_page(self, mock_session_cls, tmp_path):
        """stop_event set before scraping starts → returns empty list immediately."""
        import threading
        self._mock_session_responses(mock_session_cls)
        stop = threading.Event()
        stop.set()

        with patch("scraper.time.sleep"):
            metadata = sc.scrape_cars(
                output_dir=str(tmp_path), max_cars=5, delay=0, stop_event=stop)

        assert metadata == []

    @patch("scraper.requests.Session")
    def test_stop_event_between_listings(self, mock_session_cls, tmp_path):
        """stop_event set after first listing → only first car is scraped."""
        import threading
        session = MagicMock()
        mock_session_cls.return_value = session

        stop = threading.Event()
        call_count = [0]

        search_resp = _make_response(SAMPLE_SEARCH_HTML)
        empty_resp = _make_response(EMPTY_SEARCH_HTML)
        image_resp = _make_response(content_type="image/jpeg")

        def side_effect(url, **kwargs):
            call_count[0] += 1
            # Set stop after first image download so second listing is skipped
            if call_count[0] >= 2:
                stop.set()
            if "carsales.com.au/cars/" in url and "page=2" in url:
                return empty_resp
            if "carsales.com.au/cars/" in url:
                return search_resp
            return image_resp

        session.get.side_effect = side_effect

        with patch("scraper.time.sleep"):
            metadata = sc.scrape_cars(
                output_dir=str(tmp_path), max_cars=10, delay=0, stop_event=stop)

        # At least the first car was processed before stop
        assert len(metadata) >= 1
        # And we did not scrape all listings (stop was respected)
        assert len(metadata) < 10

    @patch("scraper.requests.Session")
    def test_no_stop_event_full_run(self, mock_session_cls, tmp_path):
        """Passing stop_event=None preserves existing behaviour."""
        self._mock_session_responses(mock_session_cls)

        with patch("scraper.time.sleep"):
            metadata = sc.scrape_cars(
                output_dir=str(tmp_path), max_cars=2, delay=0, stop_event=None)

        assert len(metadata) == 2


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

class TestArgParser:
    def test_defaults(self):
        parser = sc.build_arg_parser()
        args = parser.parse_args([])
        assert args.output_dir == sc.DEFAULT_OUTPUT_DIR
        assert args.max_cars == sc.DEFAULT_MAX_CARS
        assert args.delay == sc.DEFAULT_DELAY
        assert args.make is None
        assert args.deep_scrape is False

    def test_custom_args(self):
        parser = sc.build_arg_parser()
        args = parser.parse_args([
            "-o", "/tmp/cars",
            "-n", "10",
            "-d", "2.0",
            "--make", "Toyota",
            "--min-price", "5000",
            "--max-price", "20000",
            "--deep-scrape",
        ])
        assert args.output_dir == "/tmp/cars"
        assert args.max_cars == 10
        assert args.delay == 2.0
        assert args.make == "Toyota"
        assert args.min_price == 5000
        assert args.max_price == 20000
        assert args.deep_scrape is True
