# Auction Scraper

Scrapes apartment auctions from astalegale.net for Italian cities.

## Features

- Filters by city, budget, and auction date range
- Detects Turin neighborhoods (zone) from addresses
- Excludes past auctions
- Outputs results to CSV

## Setup

```bash
poetry install
```

## Usage

```bash
poetry run python scraper.py
```

### Options

```
--budget BUDGET   Maximum budget in EUR (default: 150000)
--city CITY       City to search (default: torino)
--months MONTHS   Months ahead to search (default: 3)
--output OUTPUT   Output CSV file (default: auctions_torino.csv)
```

### Examples

```bash
# Search with default settings (Turin, €150k, 3 months)
poetry run python scraper.py

# Search with €80k budget
poetry run python scraper.py --budget 80000

# Search 6 months ahead, save to custom file
poetry run python scraper.py --months 6 --output results.csv
```

## Output

Results are saved to CSV with columns:
- address
- zone (Turin neighborhood)
- property_type
- auction_date
- base_price
- tribunal
- reference
- url
- description
