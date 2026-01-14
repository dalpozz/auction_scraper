# Auction Scraper

Scrapes apartment auctions from astalegale.net for the city of Turin.

## Filters

- Location: Turin (Torino), Italy
- Max budget: €100,000
- Auction date: within next 3 months
- Excludes past auctions

## Setup

```bash
poetry install
```

## Usage

```bash
poetry run python scraper.py
```

Results are saved to `auctions_torino.json`.

## Configuration

Edit `scraper.py` to change filters:

```python
scraper = AstaLegaleScraper(
    max_budget=100000,    # Maximum price in EUR
    city="torino",        # City name
    months_ahead=3,       # Months to look ahead
)
```

## Limitations

astalegale.net is JavaScript-rendered (Nuxt.js). The current implementation uses HTTP requests which may not capture dynamically loaded content. For full functionality, install Chrome/Chromium and the scraper will use Selenium automatically.
