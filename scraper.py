#!/usr/bin/env python3
"""
Auction scraper for astalegale.net
Searches for apartments in Turin with budget <= 100,000 EUR
Filters auctions in the next 3 months, excludes past auctions

Uses the RSS feed endpoint for reliable data extraction.
"""

import csv
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests


@dataclass
class Auction:
    """Represents an auction listing"""
    title: str
    address: str
    zone: str
    description: str
    tribunal: str
    auction_date: Optional[datetime]
    base_price: float
    url: str
    reference: str
    property_type: str


# Turin neighborhoods mapped by street/area keywords
TORINO_ZONES = {
    # Centro
    "centro": ["piazza castello", "via roma", "via po", "piazza san carlo", "via garibaldi", "piazza vittorio"],
    "crocetta": ["crocetta", "via massena", "corso duca degli abruzzi", "politecnico"],
    "san salvario": ["san salvario", "via nizza", "via madama cristina", "via ormea"],
    "vanchiglia": ["vanchiglia", "lungo po", "corso san maurizio"],
    
    # Nord
    "barriera di milano": ["barriera di milano", "via cigna", "corso vercelli", "via bologna", "via leinì"],
    "rebaudengo": ["rebaudengo", "corso grosseto"],
    "falchera": ["falchera"],
    "madonna di campagna": ["madonna di campagna", "via stradella"],
    "lanzo": ["via lanzo"],
    "borgata vittoria": ["borgata vittoria", "corso grosseto"],
    "lucento": ["lucento", "via pianezza"],
    "vallette": ["vallette", "via dei mughetti"],
    "venaria": ["via venaria", "via venarìa"],
    
    # Sud  
    "lingotto": ["lingotto", "via nizza", "corso unione sovietica"],
    "mirafiori": ["mirafiori", "corso unione sovietica", "strada del drosso"],
    "santa rita": ["santa rita", "via tripoli", "via gorizia"],
    "pozzo strada": ["pozzo strada", "corso francia"],
    "parella": ["parella", "via servais"],
    
    # Est
    "aurora": ["aurora", "corso giulio cesare", "via cuneo", "porta palazzo"],
    "borgo po": ["borgo po", "corso moncalieri", "gran madre"],
    "madonna del pilone": ["madonna del pilone", "corso casale"],
    "sassi": ["sassi", "piazza sassi"],
    "superga": ["superga", "strada di superga"],
    
    # Ovest
    "san paolo": ["san paolo", "via di nanni", "via cibrario"],
    "cenisia": ["cenisia", "via cibrario", "corso francia"],
    "cit turin": ["cit turin", "corso francia", "via duchessa jolanda"],
    "campidoglio": ["campidoglio", "via cibrario"],
    "borgo san paolo": ["borgo san paolo", "via monginevro"],
    
    # Colline
    "collina": ["strada del mainero", "strada comunale", "collina", "precollina"],
    "gran madre": ["gran madre", "piazza gran madre"],
    
    # Altri
    "moncalieri": ["moncalieri"],
    "nichelino": ["nichelino"],
    "rivoli": ["rivoli"],
    "grugliasco": ["grugliasco"],
    "collegno": ["collegno"],
    "settimo": ["settimo"],
    "san mauro": ["san mauro"],
    "chieri": ["chieri", "riva presso chieri"],
}


class AstaLegaleScraper:
    """Scraper for astalegale.net auction listings using RSS feed"""
    
    BASE_URL = "https://www.astalegale.net"
    RSS_URL = "https://www.astalegale.net/Immobili/Rss"
    
    def __init__(self, max_budget: float = 150000, city: str = "torino", months_ahead: int = 3):
        self.max_budget = max_budget
        self.city = city.lower()
        self.months_ahead = months_ahead
        self.cutoff_date = datetime.now() + timedelta(days=months_ahead * 30)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml",
        })
    
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
    
    def _detect_zone(self, address: str, description: str = "") -> str:
        """Detect Turin neighborhood from address and description"""
        text = f"{address} {description}".lower()
        
        for zone, keywords in TORINO_ZONES.items():
            for keyword in keywords:
                if keyword in text:
                    return zone.title()
        
        return ""
    
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
        zone = self._detect_zone(address, desc_text)
        
        if base_price is None:
            return None
        
        return Auction(
            title=title,
            address=address,
            zone=zone,
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
        
        print(f"Scraping apartments in {self.city.title()}")
        print(f"Max budget: €{self.max_budget:,.2f}")
        print(f"Auction date range: now to {self.cutoff_date.strftime('%d/%m/%Y')}")
        print("-" * 60)
        
        url = self._build_rss_url()
        print(f"Fetching RSS feed: {url}")
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error fetching RSS feed: {e}")
            return []
        
        # Parse XML
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            print(f"Error parsing RSS feed: {e}")
            return []
        
        # Find all items
        items = root.findall(".//item")
        print(f"Found {len(items)} total listings")
        
        now = datetime.now()
        
        for item in items:
            auction = self._parse_rss_item(item)
            if auction is None:
                continue
            
            # Apply budget filter
            if auction.base_price > self.max_budget:
                continue
            
            # Apply date filters
            if auction.auction_date:
                # Skip past auctions
                if auction.auction_date < now:
                    continue
                # Skip auctions beyond cutoff
                if auction.auction_date > self.cutoff_date:
                    continue
            
            all_auctions.append(auction)
        
        # Sort by auction date
        all_auctions.sort(key=lambda a: a.auction_date or datetime.max)
        
        print(f"Found {len(all_auctions)} auctions matching criteria")
        return all_auctions
    
    def print_results(self, auctions: list[Auction]) -> None:
        """Print auction results"""
        print("\n" + "=" * 60)
        print(f"RESULTS: {len(auctions)} apartments in {self.city.title()}")
        print(f"Budget: up to €{self.max_budget:,.2f}")
        print(f"Auctions within next {self.months_ahead} months")
        print("=" * 60)
        
        if not auctions:
            print("\nNo apartments matching your criteria were found.")
            return
        
        for i, auction in enumerate(auctions, 1):
            print(f"\n[{i}] {auction.address}")
            if auction.zone:
                print(f"    Zone: {auction.zone}")
            print(f"    Type: {auction.property_type}")
            if auction.auction_date:
                print(f"    Auction Date: {auction.auction_date.strftime('%d/%m/%Y')}")
            print(f"    Base Price: €{auction.base_price:,.2f}")
            if auction.tribunal:
                print(f"    {auction.tribunal}")
            print(f"    Ref: {auction.reference}")
            print(f"    URL: {auction.url}")
    
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
        
        print(f"\nResults saved to {filename}")


def main():
    """Main entry point"""
    scraper = AstaLegaleScraper(
        city="torino",
        months_ahead=3,
    )
    
    auctions = scraper.scrape()
    scraper.print_results(auctions)
    
    if auctions:
        scraper.save_results(auctions)


if __name__ == "__main__":
    main()
