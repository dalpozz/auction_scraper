#!/usr/bin/env python3
"""
Auction scraper for astalegale.net
Searches for apartments in Turin with budget <= 100,000 EUR
Filters auctions in the next 3 months, excludes past auctions
"""

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup


@dataclass
class Auction:
    """Represents an auction listing"""
    title: str
    address: str
    tribunal: str
    auction_date: datetime
    base_price: float
    min_offer: Optional[float]
    url: str
    procedure: str


class AstaLegaleScraper:
    """Scraper for astalegale.net auction listings"""
    
    BASE_URL = "https://www.astalegale.net"
    
    def __init__(self, max_budget: float = 100000, city: str = "torino", months_ahead: int = 3):
        self.max_budget = max_budget
        self.city = city.lower()
        self.months_ahead = months_ahead
        self.cutoff_date = datetime.now() + timedelta(days=months_ahead * 30)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        
    def _build_search_url(self, page: int = 1) -> str:
        """Build the search URL with filters for Turin apartments"""
        params = [
            "categories=residenziali",
            "regioni=piemonte",
            "province=to",
            f"page={page}",
        ]
        return f"{self.BASE_URL}/immobili?{'&'.join(params)}"
    
    def _parse_price(self, price_text: str) -> Optional[float]:
        """Extract numeric price from text like '70.000,00 €'"""
        if not price_text:
            return None
        cleaned = price_text.replace("€", "").replace(" ", "").strip()
        cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    
    def _parse_date(self, date_text: str) -> Optional[datetime]:
        """Parse date from text like '17/03/2026 - 12:00' or 'Data asta: 17/03/2026'"""
        if not date_text:
            return None
        match = re.search(r"(\d{2}/\d{2}/\d{4})", date_text)
        if match:
            try:
                return datetime.strptime(match.group(1), "%d/%m/%Y")
            except ValueError:
                return None
        return None
    
    def _extract_auctions_from_page(self, html: str) -> list[Auction]:
        """Extract auction listings from page HTML"""
        auctions = []
        soup = BeautifulSoup(html, "lxml")
        
        # Find all auction card links
        card_links = soup.find_all("a", href=re.compile(r"/Aste/Detail/"))
        
        seen_urls = set()
        for link in card_links:
            href = link.get("href", "")
            if not href or href in seen_urls:
                continue
            
            # Get the card text content
            card_text = link.get_text(separator="\n", strip=True)
            lines = [l.strip() for l in card_text.split("\n") if l.strip()]
            
            if len(lines) < 2:
                continue
            
            # Skip if this is just a navigation link
            if len(lines) == 1 and len(lines[0]) < 20:
                continue
                
            seen_urls.add(href)
            
            # Parse card content
            title = ""
            address = ""
            tribunal = ""
            auction_date = None
            procedure = ""
            base_price = None
            min_offer = None
            
            for i, line in enumerate(lines):
                line_lower = line.lower()
                
                # Title is usually first meaningful line
                if not title and ("abitazione" in line_lower or "appartamento" in line_lower 
                                  or "civile" in line_lower or "economico" in line_lower):
                    title = line
                    # Address is usually next line
                    if i + 1 < len(lines):
                        address = lines[i + 1]
                
                if "tribunale" in line_lower:
                    tribunal = line
                    
                if "data asta:" in line_lower:
                    auction_date = self._parse_date(line)
                    
                if re.match(r"[A-Z]\.\w+\.", line) or "lotto" in line_lower:
                    if not procedure:
                        procedure = line
                        
                if "prezzo base:" in line_lower:
                    base_price = self._parse_price(line.replace("Prezzo base:", "").replace("prezzo base:", ""))
                    
                if "offerta minima:" in line_lower:
                    min_offer = self._parse_price(line.replace("Offerta minima:", "").replace("offerta minima:", ""))
            
            # Try to extract price from standalone price lines
            if base_price is None:
                for line in lines:
                    if "€" in line and "prezzo" not in line.lower() and "offerta" not in line.lower():
                        price = self._parse_price(line)
                        if price and price > 1000:
                            base_price = price
                            break
            
            # Skip if missing essential data
            if not auction_date or not base_price:
                continue
            
            # Check if address contains Turin
            address_lower = (address or "").lower()
            title_lower = (title or "").lower()
            
            # Filter for Turin city
            is_torino = ("torino" in address_lower or "torino" in title_lower or
                        "turin" in address_lower or "turin" in title_lower)
            
            if not is_torino:
                continue
            
            # Apply date filters
            now = datetime.now()
            
            # Skip past auctions
            if auction_date < now:
                continue
            
            # Skip auctions beyond cutoff date
            if auction_date > self.cutoff_date:
                continue
            
            # Skip if over budget
            if base_price > self.max_budget:
                continue
            
            auction = Auction(
                title=title or "Abitazione",
                address=address or "Torino",
                tribunal=tribunal,
                auction_date=auction_date,
                base_price=base_price,
                min_offer=min_offer,
                url=f"{self.BASE_URL}{href}",
                procedure=procedure,
            )
            auctions.append(auction)
        
        return auctions
    
    def _has_next_page(self, html: str, current_page: int) -> bool:
        """Check if there's a next page of results"""
        soup = BeautifulSoup(html, "lxml")
        # Look for pagination links
        next_page = current_page + 1
        pagination = soup.find("a", href=re.compile(f"page={next_page}"))
        return pagination is not None
    
    def scrape(self, max_pages: int = 20) -> list[Auction]:
        """Scrape auction listings matching the criteria"""
        all_auctions = []
        
        print(f"Starting scrape for apartments in {self.city.title()}")
        print(f"Max budget: €{self.max_budget:,.2f}")
        print(f"Auction date range: now to {self.cutoff_date.strftime('%d/%m/%Y')}")
        print("-" * 60)
        
        for page in range(1, max_pages + 1):
            url = self._build_search_url(page)
            print(f"Fetching page {page}...")
            
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
            except requests.RequestException as e:
                print(f"  Error fetching page {page}: {e}")
                break
            
            page_auctions = self._extract_auctions_from_page(response.text)
            
            if page_auctions:
                print(f"  Found {len(page_auctions)} matching auctions")
                all_auctions.extend(page_auctions)
            else:
                print(f"  No matching auctions on page {page}")
            
            # Check if there are more pages
            if not self._has_next_page(response.text, page):
                print("  Reached last page")
                break
            
            # Be polite to the server
            time.sleep(0.5)
        
        # Remove duplicates based on URL
        seen = set()
        unique_auctions = []
        for auction in all_auctions:
            if auction.url not in seen:
                seen.add(auction.url)
                unique_auctions.append(auction)
        
        # Sort by auction date
        unique_auctions.sort(key=lambda a: a.auction_date)
        
        return unique_auctions
    
    def print_results(self, auctions: list[Auction]) -> None:
        """Print auction results in a formatted way"""
        print("\n" + "=" * 60)
        print(f"RESULTS: {len(auctions)} apartments found in Turin")
        print(f"Budget: up to €{self.max_budget:,.2f}")
        print(f"Auctions within next {self.months_ahead} months")
        print("=" * 60)
        
        if not auctions:
            print("\nNo apartments matching your criteria were found.")
            print("\nTips:")
            print("- Try increasing the budget")
            print("- Extend the date range")
            print("- Check the website directly for new listings")
            return
        
        for i, auction in enumerate(auctions, 1):
            print(f"\n[{i}] {auction.title}")
            print(f"    Address: {auction.address}")
            print(f"    Auction Date: {auction.auction_date.strftime('%d/%m/%Y')}")
            print(f"    Base Price: €{auction.base_price:,.2f}")
            if auction.min_offer:
                print(f"    Min Offer: €{auction.min_offer:,.2f}")
            if auction.tribunal:
                print(f"    Tribunal: {auction.tribunal}")
            print(f"    URL: {auction.url}")
    
    def save_results(self, auctions: list[Auction], filename: str = "auctions_torino.json") -> None:
        """Save results to JSON file"""
        output = []
        for a in auctions:
            output.append({
                "title": a.title,
                "address": a.address,
                "tribunal": a.tribunal,
                "auction_date": a.auction_date.strftime("%d/%m/%Y"),
                "base_price": a.base_price,
                "min_offer": a.min_offer,
                "url": a.url,
                "procedure": a.procedure,
            })
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\nResults saved to {filename}")


def main():
    """Main entry point"""
    scraper = AstaLegaleScraper(
        max_budget=100000,
        city="torino",
        months_ahead=3,
    )
    
    auctions = scraper.scrape(max_pages=20)
    scraper.print_results(auctions)
    
    if auctions:
        scraper.save_results(auctions)


if __name__ == "__main__":
    main()
