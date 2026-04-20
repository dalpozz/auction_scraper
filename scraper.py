#!/usr/bin/env python3
"""
Auction scraper for astalegale.net
Searches for apartments with configurable budget and location filters.
Filters auctions in the next N months, excludes past auctions.

Uses the RSS feed endpoint for reliable data extraction.
Uses OpenStreetMap Nominatim API for zone/neighborhood detection.
"""

import argparse
import csv
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class Auction:
    """Represents an auction listing"""
    title: str
    address: str
    zone: str = ""
    description: str = ""
    tribunal: str = ""
    auction_date: Optional[datetime] = None
    base_price: float = 0.0
    url: str = ""
    reference: str = ""
    property_type: str = "Unknown"


class GeocodingService:
    """Service to detect neighborhood/zone from address using OpenStreetMap Nominatim"""

    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

    def __init__(self, cache_file: str = ".geocode_cache.json"):
        self.cache_file = Path(cache_file)
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": "AuctionScraper/1.0 (https://github.com/dalpozz/auction_scraper)",
        })
        self.cache: dict[str, str] = self._load_cache()

    def _load_cache(self) -> dict[str, str]:
        """Load cache from file if it exists"""
        if self.cache_file.exists():
            try:
                return json.loads(self.cache_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_cache(self) -> None:
        """Save cache to file"""
        try:
            self.cache_file.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            logger.warning(f"Failed to save geocode cache: {e}")

    def get_zone(self, address: str, city: str) -> str:
        """Get neighborhood/zone for an address using Nominatim API"""
        cache_key = f"{address}|{city}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        query = f"{address}, {city}, Italia"

        try:
            time.sleep(1)

            response = self.session.get(
                self.NOMINATIM_URL,
                params={
                    "q": query,
                    "format": "json",
                    "addressdetails": 1,
                    "limit": 1,
                },
                timeout=10,
            )
            response.raise_for_status()

            results = response.json()
            if results and "address" in results[0]:
                addr = results[0]["address"]
                zone = (
                    addr.get("suburb") or
                    addr.get("neighbourhood") or
                    addr.get("quarter") or
                    addr.get("city_district") or
                    ""
                )
                self.cache[cache_key] = zone
                self._save_cache()
                return zone

        except requests.RequestException as e:
            logger.warning(f"Geocoding request failed for '{query}': {e}")
        except (KeyError, IndexError, ValueError) as e:
            logger.warning(f"Geocoding parse error for '{query}': {e}")

        self.cache[cache_key] = ""
        return ""


class AstaLegaleScraper:
    """Scraper for astalegale.net auction listings using RSS feed"""

    BASE_URL = "https://www.astalegale.net"
    RSS_URL = "https://www.astalegale.net/Immobili/Rss"

    def __init__(self, max_budget: float = 150000, city: str = "torino", months_ahead: int = 3, include_undated: bool = False):
        if max_budget <= 0:
            raise ValueError("Budget must be a positive value")
        if months_ahead <= 0:
            raise ValueError("Months ahead must be a positive value")

        self.max_budget = max_budget
        self.city = city.lower()
        self.months_ahead = months_ahead
        self.include_undated = include_undated
        self.cutoff_date = datetime.now() + timedelta(days=months_ahead * 30)
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml",
        })
        self.geocoder = GeocodingService()
    
    def _build_rss_url(self) -> str:
        """Build the RSS feed URL with filters"""
        params = [
            "categories=residenziali",
            "regioni=piemonte",
            "province=to",
            f"comuni={self.city}",
        ]
        return f"{self.RSS_URL}?{'&'.join(params)}"
    
    def _parse_price(self, text: str) -> Optional[float]:
        """Extract price from text like 'Prezzo: 70.000,00 €'"""
        match = re.search(r"Prezzo:\s*([\d.,]+)\s*€", text)
        if match:
            price_str = match.group(1)
            # Italian format: 70.000,00 -> 70000.00
            cleaned = price_str.replace(".", "").replace(",", ".")
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None
    
    def _parse_auction_date(self, text: str) -> Optional[datetime]:
        """Extract auction date from text like 'Data asta: 17/03/2026 - 12:00'"""
        match = re.search(r"Data asta:\s*(\d{2}/\d{2}/\d{4})", text)
        if match:
            try:
                return datetime.strptime(match.group(1), "%d/%m/%Y")
            except ValueError:
                return None
        return None
    
    def _parse_property_type(self, text: str) -> str:
        """Extract property type from text like 'Tipologia: Abitazione di tipo civile'"""
        match = re.search(r"Tipologia:\s*([^-]+)", text)
        if match:
            return match.group(1).strip()
        return "Unknown"
    
    def _detect_zone(self, address: str) -> str:
        """Detect neighborhood from address using geocoding"""
        return self.geocoder.get_zone(address, self.city)
    
    def _extract_address_from_title(self, title: str) -> str:
        """Extract address from title (first part before ' - Lotto')"""
        parts = title.split(" - Lotto")
        if parts:
            return parts[0].strip()
        return title
    
    def _extract_tribunal(self, title: str) -> str:
        """Extract tribunal from title"""
        match = re.search(r"Tribunale di ([^-]+)", title)
        if match:
            return f"Tribunale di {match.group(1).strip()}"
        return ""
    
    def _extract_reference(self, title: str) -> str:
        """Extract reference number from title"""
        match = re.search(r"Rif\. #(\w+)", title)
        if match:
            return match.group(1)
        return ""
    
    def _parse_rss_item(self, item: ET.Element) -> Optional[Auction]:
        """Parse a single RSS item into an Auction object"""
        title_elem = item.find("title")
        desc_elem = item.find("description")
        link_elem = item.find("link")
        
        if title_elem is None or desc_elem is None or link_elem is None:
            return None
        
        title = title_elem.text or ""
        description = desc_elem.text or ""
        url = link_elem.text or ""
        
        # Extract data from description
        base_price = self._parse_price(description)
        auction_date = self._parse_auction_date(description)
        property_type = self._parse_property_type(description)
        
        # Extract data from title
        address = self._extract_address_from_title(title)
        tribunal = self._extract_tribunal(title)
        reference = self._extract_reference(title)
        
        # Detect neighborhood
        desc_text = description.split(" - Tipologia:")[0].strip()
        
        if base_price is None:
            return None
        
        return Auction(
            title=title,
            address=address,
            zone="",  # Will be populated later via geocoding
            description=desc_text,
            tribunal=tribunal,
            auction_date=auction_date,
            base_price=base_price,
            url=url,
            reference=reference,
            property_type=property_type,
        )
    
    def scrape(self) -> list[Auction]:
        """Scrape auction listings from RSS feed"""
        all_auctions = []

        logger.info(f"Scraping apartments in {self.city.title()}")
        logger.info(f"Max budget: €{self.max_budget:,.2f}")
        logger.info(f"Auction date range: now to {self.cutoff_date.strftime('%d/%m/%Y')}")

        url = self._build_rss_url()
        logger.info(f"Fetching RSS feed: {url}")
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error fetching RSS feed: {e}")
            return []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            logger.error(f"Error parsing RSS feed: {e}")
            return []

        items = root.findall(".//item")
        logger.info(f"Found {len(items)} total listings")
        
        now = datetime.now()
        
        for item in items:
            auction = self._parse_rss_item(item)
            if auction is None:
                continue
            
            # Apply budget filter
            if auction.base_price > self.max_budget:
                continue
            
            # Apply date filters
            if auction.auction_date is None:
                if not self.include_undated:
                    logger.debug(f"Skipping auction with unknown date: {auction.address}")
                    continue
            else:
                if auction.auction_date < now:
                    logger.debug(f"Skipping past auction: {auction.address}")
                    continue
                if auction.auction_date > self.cutoff_date:
                    logger.debug(f"Skipping auction beyond cutoff: {auction.address}")
                    continue
            
            all_auctions.append(auction)
        
        all_auctions.sort(key=lambda a: a.auction_date or datetime.max)

        logger.info(f"Found {len(all_auctions)} auctions matching criteria")

        if all_auctions:
            logger.info("Detecting zones via geocoding...")
            for auction in all_auctions:
                zone = self._detect_zone(auction.address)
                auction.zone = zone
        
        return all_auctions
    
    def print_results(self, auctions: list[Auction]) -> None:
        """Print auction results"""
        logger.info("=" * 60)
        logger.info(f"RESULTS: {len(auctions)} apartments in {self.city.title()}")
        logger.info(f"Budget: up to €{self.max_budget:,.2f}")
        logger.info(f"Auctions within next {self.months_ahead} months")
        logger.info("=" * 60)

        if not auctions:
            logger.info("No apartments matching your criteria were found.")
            return

        for i, auction in enumerate(auctions, 1):
            logger.info(f"[{i}] {auction.address}")
            if auction.zone:
                logger.info(f"    Zone: {auction.zone}")
            logger.info(f"    Type: {auction.property_type}")
            if auction.auction_date:
                logger.info(f"    Auction Date: {auction.auction_date.strftime('%d/%m/%Y')}")
            else:
                logger.info(f"    Auction Date: TBD")
            logger.info(f"    Base Price: €{auction.base_price:,.2f}")
            if auction.tribunal:
                logger.info(f"    {auction.tribunal}")
            logger.info(f"    Ref: {auction.reference}")
            logger.info(f"    URL: {auction.url}")
    
    def save_results(self, auctions: list[Auction], filename: str = "auctions_torino.csv") -> None:
        """Save results to CSV file"""
        with open(filename, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["address", "zone", "property_type", "auction_date", "base_price", "tribunal", "reference", "url", "description"])
            
            for a in auctions:
                writer.writerow([
                    a.address,
                    a.zone,
                    a.property_type,
                    a.auction_date.strftime("%d/%m/%Y") if a.auction_date else "",
                    a.base_price,
                    a.tribunal,
                    a.reference,
                    a.url,
                    a.description,
                ])
        
        logger.info(f"Results saved to {filename}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Scrape apartment auctions from astalegale.net")
    parser.add_argument("--budget", type=float, default=150000, help="Maximum budget in EUR (default: 150000)")
    parser.add_argument("--city", type=str, default="torino", help="City to search (default: torino)")
    parser.add_argument("--months", type=int, default=3, help="Months ahead to search (default: 3)")
    parser.add_argument("--output", type=str, default="auctions_torino.csv", help="Output CSV file (default: auctions_torino.csv)")
    parser.add_argument("--include-undated", action="store_true", help="Include auctions without scheduled date")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        scraper = AstaLegaleScraper(
            max_budget=args.budget,
            city=args.city,
            months_ahead=args.months,
            include_undated=args.include_undated,
        )
    except ValueError as e:
        logger.error(f"Invalid arguments: {e}")
        return 1

    auctions = scraper.scrape()
    scraper.print_results(auctions)

    if auctions:
        scraper.save_results(auctions, args.output)

    return 0


if __name__ == "__main__":
    exit(main())
