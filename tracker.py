#!/usr/bin/env python3
"""
Reliable Selenium price tracker (headless Chrome) for dynamic sites
Usage: python tracker.py urls.txt
"""

import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

PAGE_LOAD_TIMEOUT = 15
HISTORY_FILE = "price_history.csv"

# Common price-related class names
PRICE_CLASS_NAMES = [
    "price",
    "product-price",
    "product_price",
    "sales",
    "sale-price",
    "current-price",
]


def setup_driver() -> webdriver.Chrome:
    """Create headless Chrome driver with timeout and realistic user-agent."""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver


def extract_price(driver: webdriver.Chrome) -> Optional[str]:
    """
    Extract price from the page using multiple strategies:
    1. Wait for span[@itemprop='price'] (dynamic content, Ralph Lauren, Shopify)
    2. Common price-related class names
    3. Any element containing $ in text
    4. Regex fallback in page source
    """
    # 1. Wait for semantic price span
    try:
        el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//span[@itemprop='price']"))
        )
        text = el.get_attribute("content") or el.text
        if text:
            price = _parse_price_from_text(text)
            if price:
                return price
    except TimeoutException:
        pass
    except WebDriverException:
        pass

    # 2. Class-based search
    for name in PRICE_CLASS_NAMES:
        try:
            selector = f"[class*='{name}']"
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                text = (el.text or "").strip()
                if not text:
                    continue
                price = _parse_price_from_text(text)
                if price is not None:
                    return price
        except WebDriverException:
            continue

    # 3. Any element with $ in text
    try:
        elements = driver.find_elements(By.XPATH, "//*[contains(text(), '$')]")
        for el in elements:
            text = (el.text or "").strip()
            if not text or len(text) > 30:
                continue
            price = _parse_price_from_text(text)
            if price is not None:
                return price
    except WebDriverException:
        pass

    # 4. Regex fallback in page source
    html = driver.page_source
    price = _price_from_regex(html)
    if price is not None:
        return price

    return None


def _parse_price_from_text(text: str) -> Optional[str]:
    """Extract first numeric price from text like '$129.00' or '129.00'."""
    match = re.search(r"\$?\s*(\d{1,3}(?:,\d{3})*\.?\d{2}|\d+\.\d{2})", text)
    if match:
        raw = match.group(1).replace(",", "")
        if re.match(r"^\d+\.?\d*$", raw):
            return raw
    return None


def _price_from_regex(html: str) -> Optional[str]:
    """Regex fallback for embedded JS/JSON prices."""
    patterns = [
        r'"price"\s*:\s*["\']?([0-9]+\.?[0-9]*)',
        r"\$\s*([0-9]+\.?[0-9]*)",
        r"data-price=['\"]?([0-9]+\.?[0-9]*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            raw = match.group(1).replace(",", "")
            if re.match(r"^\d+\.?\d*$", raw):
                return raw
    return None


def load_urls(path: Path) -> list[str]:
    """Read URLs from file, one per line, skip empty lines and comments (#)."""
    urls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def append_history(url: str, price: str, history_path: Path) -> None:
    """Append one row to CSV; create file with header if needed."""
    file_exists = history_path.exists()
    with open(history_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "url", "price"])
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        writer.writerow([ts, url, price])


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
    driver = None

    try:
        driver = setup_driver()
        for i, url in enumerate(urls, start=1):
            try:
                driver.get(url)
            except TimeoutException:
                print(f"[{i}] Error: Page load timed out")
                print(f"    {url}")
                continue
            except WebDriverException as e:
                print(f"[{i}] Error: {e}")
                print(f"    {url}")
                continue

            price = extract_price(driver)
            if price is None:
                print(f"Could not find price for: {url}")
                continue

            print(f"[{i}] ${price}   {url}")
            append_history(url, price, history_path)

        print(f"\nHistory appended to {HISTORY_FILE}")
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
