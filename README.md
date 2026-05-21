# scraper

Scrapes car pictures for datasets from **[carsales.com.au](https://www.carsales.com.au)** — Australia's leading car sale website.

## Features

- Searches carsales.com.au for car listings
- Downloads car images to a local directory
- Saves per-listing metadata (title, price, listing URL) as JSON files
- Optional filters: car make, min/max price
- Optional **deep-scrape** mode: visits each listing's gallery page for full-resolution images
- Configurable request delay to be polite to the server
- Gracefully handles network errors and skips non-image responses

## Requirements

- Python 3.10+
- [requests](https://pypi.org/project/requests/)
- [beautifulsoup4](https://pypi.org/project/beautifulsoup4/)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

```
python scraper.py [options]
```

| Option | Default | Description |
|---|---|---|
| `-o`, `--output-dir` | `car_images` | Directory to save images and metadata |
| `-n`, `--max-cars` | `50` | Maximum number of car listings to scrape |
| `-d`, `--delay` | `1.5` | Seconds between HTTP requests |
| `--make` | *(all)* | Filter by car make (e.g. `Toyota`) |
| `--min-price` | *(none)* | Minimum price filter in AUD |
| `--max-price` | *(none)* | Maximum price filter in AUD |
| `--deep-scrape` | off | Visit each listing page for full gallery images |
| `-v`, `--verbose` | off | Enable DEBUG logging |

### Examples

```bash
# Scrape 50 cars (default) into ./car_images/
python scraper.py

# Scrape 20 Toyota listings with full gallery images
python scraper.py --make Toyota -n 20 --deep-scrape

# Scrape into a custom directory with price range
python scraper.py -o /data/cars -n 100 --min-price 5000 --max-price 30000

# Scrape with a longer delay to be more polite
python scraper.py -d 3.0 -n 50
```

## Output structure

```
car_images/
├── metadata.json          ← combined metadata for all scraped cars
├── car_0000/
│   ├── metadata.json      ← title, price, URL for this listing
│   ├── image_0000.jpg
│   └── image_0001.jpg
├── car_0001/
│   ├── metadata.json
│   └── image_0000.jpg
└── ...
```

Each `metadata.json` looks like:

```json
{
  "car_index": 0,
  "title": "2022 Toyota Camry Ascent Sport",
  "price": "$34,990",
  "url": "https://www.carsales.com.au/cars/toyota/camry/...",
  "images_downloaded": ["car_images/car_0000/image_0000.jpg"]
}
```

## Running tests

```bash
pip install pytest
pytest tests/
```
