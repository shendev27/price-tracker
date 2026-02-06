#!/usr/bin/env python3
"""
Minimalistic price tracker: scrape product URLs and log price history.
Usage: python tracker.py urls.txt
"""

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

REQUEST_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}
HISTORY_FILE = "price_history.csv"


def extract_price(html: str) -> Optional[str]:
    """
    Try multiple strategies to extract product price from HTML.
    Returns price string (e.g. "129.00") or None if not found.
    """
    # 1. JSON-LD product schema (Patagonia, Ralph Lauren, etc.)
    price = _price_from_json_ld(html)
    if price is not None:
        return price

    soup = BeautifulSoup(html, "html.parser")

    # 2. Meta tags
    for meta in soup.find_all("meta", property=re.compile(r"product:price:amount", re.I)):
        content = meta.get("content")
        if content and _looks_like_price(content):
            return _normalize_price(content)
    for meta in soup.find_all("meta", itemprop="price"):
        content = meta.get("content")
        if content and _looks_like_price(content):
            return _normalize_price(content)

    # 3. Elements with price-related class names
    price_classes = ["price", "product-price", "product_price", "sales", "sale-price", "current-price"]
    for name in price_classes:
        for el in soup.find_all(class_=re.compile(re.escape(name), re.I)):
            text = el.get_text(strip=True)
            price = _parse_price_from_text(text)
            if price is not None:
                return price

    # 4. Fallback: regex for embedded JS/JSON (e.g. "price": "129.00")
    price = _price_from_regex(html)
    if price is not None:
        return price

    return None


def _price_from_json_ld(html: str) -> Optional[str]:
    """Parse <script type="application/ld+json"> and extract offers.price from Product schema."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        price = _find_price_in_ld(data)
        if price is not None:
            return price
    return None


def _find_price_in_ld(data: Any) -> Optional[str]:
    """Walk JSON-LD structure and return first Product offers.price."""
    if isinstance(data, dict):
        if data.get("@type") == "Product":
            offers = data.get("offers")
            if isinstance(offers, list):
                for o in offers:
                    price = _price_from_offers(o)
                    if price:
                        return price
            else:
                price = _price_from_offers(offers)
                if price:
                    return price
        # recurse through common graph structures
        for key in ("@graph", "itemListElement"):
            if key in data and isinstance(data[key], list):
                for item in data[key]:
                    price = _find_price_in_ld(item)
                    if price is not None:
                        return price
        # recurse all dict values
        for v in data.values():
            price = _find_price_in_ld(v)
            if price is not None:
                return price
    elif isinstance(data, list):
        for item in data:
            price = _find_price_in_ld(item)
            if price is not None:
                return price
    return None


def _price_from_offers(offers: Any) -> Optional[str]:
    """Extract price from offers (object or array of offers)."""
    if offers is None:
        return None
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        return None
    price = offers.get("price")
    if price is None:
        return None
    if isinstance(price, (int, float)):
        return _normalize_price(str(price))
    if isinstance(price, str) and _looks_like_price(price):
        return _normalize_price(price)
    return None


def _price_from_regex(html: str) -> Optional[str]:
    """Fallback: regex search for price in embedded JS/JSON."""
    patterns = [
        r'"price"\s*:\s*["\']([0-9]+\.?[0-9]*)["\']',
        r'"price"\s*:\s*([0-9]+\.?[0-9]*)',
        r'"product:price:amount"\s*:\s*["\']?([0-9]+\.?[0-9]*)',
        r'data-price=["\']([0-9]+\.?[0-9]*)["\']',
        r'itemprop="price"\s+content=["\']([0-9]+\.?[0-9]*)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            raw = match.group(1)
            if _looks_like_price(raw):
                return _normalize_price(raw)
    return None


def _looks_like_price(s: str) -> bool:
    s = s.strip().replace(",", "")
    return bool(re.match(r"^\d+\.?\d*$", s))


def _normalize_price(s: str) -> str:
    s = s.strip().replace(",", "")
    match = re.search(r"(\d+\.?\d*)", s)
    return match.group(1) if match else s


def _parse_price_from_text(text: str) -> Optional[str]:
    match = re.search(r"[\$€£]?\s*(\d+[.,]\d{2})", text)
    if match:
        return match.group(1).replace(",", ".")
    match = re.search(r"(\d+\.\d{2})", text)
    return match.group(1) if match else None


def fetch_page(url: str) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch URL and return (html, error_message).
    On success, error_message is None. On failure, html is None.
    """
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
    except requests.exceptions.Timeout:
        return None, "Request timed out"
    except requests.exceptions.ConnectionError:
        return None, "Connection error (check URL or network)"
    except requests.exceptions.RequestException as e:
        return None, f"Request failed: {e}"

    if resp.status_code == 403:
        return None, "Access forbidden (403). Site may require headers or anti-bot protection."
    if resp.status_code == 429:
        return None, "Too many requests (429). Site may be rate-limiting."
    if resp.status_code >= 400:
        return None, f"HTTP {resp.status_code}"

    return resp.text, None


def append_history(url: str, price: str, history_path: Path) -> None:
    """Append one row to price_history.csv. Create file and header if needed."""
    file_exists = history_path.exists()
    with open(history_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "url", "price"])
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        writer.writerow([ts, url, price])


def load_urls(path: Path) -> list[str]:
    """Read URLs from file, one per line, skip empty and comments."""
    urls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python tracker.py urls.txt", file=sys.stderr)
        sys.exit(1)

    urls_path = Path(sys.argv[1])
    if not urls_path.exists():
        print(f"File not found: {urls_path}", file=sys.stderr)
        sys.exit(1)

    urls = load_urls(urls_path)
    if not urls:
        print("No URLs found in file.", file=sys.stderr)
        sys.exit(1)

    history_path = Path(HISTORY_FILE)

    for i, url in enumerate(urls, start=1):
        html, err = fetch_page(url)
        if err:
            print(f"[{i}] Error: {err}")
            print(f"    {url}")
            continue

        price = extract_price(html)
        if price is None:
            print(f"Could not find price for: {url}")
            continue

        print(f"[{i}] ${price}   {url}")
        append_history(url, price, history_path)

    print(f"\nHistory appended to {HISTORY_FILE}")


if __name__ == "__main__":
    main()
