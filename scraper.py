#!/usr/bin/env python3
"""
Car image scraper for carsales.com.au — Australia's leading car sale website.

Searches for car listings, extracts image URLs, downloads images, and saves
per-listing metadata (title, price, listing URL) as JSON files.

Usage:
    python scraper.py [options]

Examples:
    # Scrape 50 cars (default) into ./car_images/
    python scraper.py

    # Scrape 20 Toyota listings, deep-scrape gallery pages
    python scraper.py --make Toyota -n 20 --deep-scrape

    # Scrape into a custom output directory with a longer delay
    python scraper.py -o /data/cars -n 100 -d 2.0
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.carsales.com.au"
SEARCH_URL = f"{BASE_URL}/cars/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-AU,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DEFAULT_OUTPUT_DIR = "car_images"
DEFAULT_DELAY = 1.5       # seconds between HTTP requests
DEFAULT_MAX_CARS = 50

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def fetch_page(session: requests.Session, url: str) -> str:
    """Fetch a URL and return the response text.  Raises on HTTP errors."""
    logger.debug("GET %s", url)
    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def build_search_url(page: int = 1, make: str = None,
                     min_price: int = None, max_price: int = None) -> str:
    """Return the carsales.com.au search URL for the given filters."""
    params: dict = {"page": page}
    if make:
        params["make"] = make
    if min_price is not None:
        params["price_from"] = min_price
    if max_price is not None:
        params["price_to"] = max_price
    return f"{SEARCH_URL}?{urlencode(params)}"

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_listings(html: str) -> list[dict]:
    """
    Parse car listing cards from a carsales.com.au search results page.

    Returns a list of dicts with keys: title, price, url, images.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = _find_listing_cards(soup)
    logger.info("Found %d listing cards on page", len(cards))

    listings = []
    for card in cards:
        listing = _parse_card(card)
        if listing.get("images") or listing.get("url"):
            listings.append(listing)
    return listings


def _find_listing_cards(soup: BeautifulSoup) -> list:
    """Locate listing card elements using several fallback strategies."""
    # Primary: data-webm-type attribute used by carsales
    cards = soup.find_all("div", attrs={"data-webm-type": "Listing"})
    if cards:
        return cards

    # Secondary: <article> tags with "listing" in the class
    cards = soup.find_all(
        "article",
        class_=lambda c: c and "listing" in c.lower(),
    )
    if cards:
        return cards

    # Tertiary: <div> tags with "listing" in the class
    cards = soup.find_all(
        "div",
        class_=lambda c: c and "listing" in c.lower(),
    )
    return cards


def _parse_card(card) -> dict:
    """Extract title, price, url, and thumbnail images from one listing card."""
    listing: dict = {}

    # --- URL ---
    link = card.find("a", href=True)
    if link:
        href = link["href"]
        listing["url"] = href if href.startswith("http") else urljoin(BASE_URL, href)

    # --- Title ---
    title_elem = card.find(
        ["h2", "h3", "h4"],
        class_=lambda c: c and "title" in c.lower(),
    ) or card.find(
        "a",
        class_=lambda c: c and "title" in c.lower(),
    )
    if title_elem:
        listing["title"] = title_elem.get_text(strip=True)

    # --- Price ---
    price_elem = card.find(
        class_=lambda c: c and "price" in c.lower()
    )
    if price_elem:
        listing["price"] = price_elem.get_text(strip=True)

    # --- Thumbnail images ---
    images = []
    for img in card.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
        )
        if src and _is_valid_image_url(src):
            url = src if src.startswith("http") else urljoin(BASE_URL, src)
            if url not in images:
                images.append(url)
    listing["images"] = images

    return listing


def _is_valid_image_url(url: str) -> bool:
    """Return True if the URL looks like a real car image (not a placeholder)."""
    lower = url.lower()
    if lower.endswith(".gif") or lower.endswith(".svg"):
        return False
    if "placeholder" in lower or "spacer" in lower or "blank" in lower:
        return False
    return True

# ---------------------------------------------------------------------------
# Deep-scrape: visit individual listing pages for full-size gallery images
# ---------------------------------------------------------------------------


def get_listing_images(session: requests.Session, listing_url: str,
                       delay: float = DEFAULT_DELAY) -> list[str]:
    """
    Visit a single listing page and return all gallery image URLs found.
    Falls back to an empty list on network errors.
    """
    time.sleep(delay)
    try:
        html = fetch_page(session, listing_url)
    except requests.RequestException as exc:
        logger.warning("Failed to fetch listing %s: %s", listing_url, exc)
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Prefer a dedicated gallery element
    gallery = soup.find(
        id=lambda i: i and "gallery" in i.lower()
    ) or soup.find(
        class_=lambda c: c and "gallery" in c.lower()
    )
    search_area = gallery if gallery else soup

    image_urls: list[str] = []
    for img in search_area.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
        )
        if src and _is_valid_image_url(src):
            url = src if src.startswith("http") else urljoin(BASE_URL, src)
            if "thumbnail" not in url.lower() and url not in image_urls:
                image_urls.append(url)

    return image_urls

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_image(session: requests.Session, url: str,
                   output_path: Path, delay: float = DEFAULT_DELAY) -> bool:
    """
    Download a single image to *output_path*.
    Returns True on success, False on failure.
    """
    time.sleep(delay)
    try:
        response = session.get(url, headers=HEADERS, timeout=30, stream=True)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to download %s: %s", url, exc)
        return False

    content_type = response.headers.get("content-type", "")
    if "image" not in content_type:
        logger.warning(
            "URL does not appear to be an image: %s (%s)", url, content_type
        )
        return False

    with open(output_path, "wb") as fh:
        for chunk in response.iter_content(chunk_size=8192):
            fh.write(chunk)

    logger.info("Downloaded: %s", output_path)
    return True


def image_filename(url: str, index: int) -> str:
    """Generate a safe, zero-padded filename from an image URL and index."""
    ext = os.path.splitext(urlparse(url).path)[1] or ".jpg"
    return f"image_{index:04d}{ext}"

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def scrape_cars(
    output_dir: str = DEFAULT_OUTPUT_DIR,
    max_cars: int = DEFAULT_MAX_CARS,
    delay: float = DEFAULT_DELAY,
    make: str = None,
    min_price: int = None,
    max_price: int = None,
    deep_scrape: bool = False,
) -> list[dict]:
    """
    Scrape car images from carsales.com.au.

    Args:
        output_dir:  Root directory for downloaded images and metadata files.
        max_cars:    Stop after processing this many car listings.
        delay:       Seconds to sleep between HTTP requests (be polite!).
        make:        Optional car make filter (e.g. "Toyota").
        min_price:   Optional minimum price in AUD.
        max_price:   Optional maximum price in AUD.
        deep_scrape: Visit each listing's detail page for full-resolution
                     gallery images (slower but more images per car).

    Returns:
        List of metadata dicts, one per scraped car.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    all_metadata: list[dict] = []
    image_count = 0
    car_count = 0
    page = 1

    logger.info(
        "Starting scrape — output: %s, max cars: %d, deep-scrape: %s",
        output_dir, max_cars, deep_scrape,
    )

    while car_count < max_cars:
        url = build_search_url(page=page, make=make,
                               min_price=min_price, max_price=max_price)
        logger.info("Fetching search results page %d: %s", page, url)

        try:
            html = fetch_page(session, url)
        except requests.RequestException as exc:
            logger.error("Failed to fetch search page %d: %s", page, exc)
            break

        time.sleep(delay)
        listings = parse_listings(html)

        if not listings:
            logger.info("No more listings on page %d — stopping.", page)
            break

        for listing in listings:
            if car_count >= max_cars:
                break

            car_dir = output_path / f"car_{car_count:04d}"
            car_dir.mkdir(exist_ok=True)

            # Choose image source: listing page gallery or thumbnail
            if deep_scrape and listing.get("url"):
                images = get_listing_images(session, listing["url"], delay=delay)
            else:
                images = listing.get("images", [])

            downloaded: list[str] = []
            for idx, img_url in enumerate(images):
                dest = car_dir / image_filename(img_url, idx)
                if download_image(session, img_url, dest, delay=delay):
                    downloaded.append(str(dest))
                    image_count += 1

            meta = {
                "car_index": car_count,
                "title": listing.get("title", ""),
                "price": listing.get("price", ""),
                "url": listing.get("url", ""),
                "images_downloaded": downloaded,
            }
            all_metadata.append(meta)

            with open(car_dir / "metadata.json", "w") as fh:
                json.dump(meta, fh, indent=2)

            car_count += 1
            logger.info(
                "Processed car %d/%d: %s",
                car_count, max_cars, listing.get("title", "Unknown"),
            )
            time.sleep(delay)

        page += 1

    # Save a combined metadata file at the root of the output directory
    combined_path = output_path / "metadata.json"
    with open(combined_path, "w") as fh:
        json.dump(all_metadata, fh, indent=2)

    logger.info(
        "Done! Scraped %d cars, downloaded %d images. Metadata: %s",
        car_count, image_count, combined_path,
    )
    return all_metadata

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape car images from carsales.com.au — "
            "Australia's leading car sale website."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save images and metadata",
    )
    parser.add_argument(
        "-n", "--max-cars",
        type=int,
        default=DEFAULT_MAX_CARS,
        help="Maximum number of car listings to scrape",
    )
    parser.add_argument(
        "-d", "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help="Delay in seconds between HTTP requests",
    )
    parser.add_argument(
        "--make",
        default=None,
        help="Filter by car make (e.g. Toyota, Ford, Honda)",
    )
    parser.add_argument(
        "--min-price",
        type=int,
        default=None,
        metavar="AUD",
        help="Minimum price filter in AUD",
    )
    parser.add_argument(
        "--max-price",
        type=int,
        default=None,
        metavar="AUD",
        help="Maximum price filter in AUD",
    )
    parser.add_argument(
        "--deep-scrape",
        action="store_true",
        help="Visit each listing page for full-size gallery images (slower)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    scrape_cars(
        output_dir=args.output_dir,
        max_cars=args.max_cars,
        delay=args.delay,
        make=args.make,
        min_price=args.min_price,
        max_price=args.max_price,
        deep_scrape=args.deep_scrape,
    )


if __name__ == "__main__":
    main()
