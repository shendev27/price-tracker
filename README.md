# Price Tracker

Minimalistic web scraper that fetches product prices from ecommerce URLs (e.g. Patagonia, Polo Ralph Lauren) and logs price history over time.

## Requirements

- Python 3.8+
- `requests`, `beautifulsoup4`

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
python tracker.py urls.txt
```

`urls.txt` should contain one product URL per line. Empty lines and lines starting with `#` are ignored.

Example `urls.txt`:

```
https://www.patagonia.com/product/example
https://www.ralphlauren.com/product/example
```

## Output

- **Console**: For each URL, prints the current price and the URL, e.g.  
  `[1] $39.99   https://example.com/product1`  
  If the price cannot be found:  
  `Could not find price for: <url>`
- **CSV**: Appends one row per URL to `price_history.csv` with columns:  
  `timestamp,url,price`  
  The file is created automatically on first run. Existing rows are never overwritten; new runs always append.

## Project Structure

```
price-tracker/
├── tracker.py          # Main script
├── requirements.txt    # Python dependencies
├── urls.txt            # Your list of product URLs (edit this)
├── price_history.csv   # Auto-created; do not edit by hand
└── README.md
```

## Price Extraction

The script tries several strategies to find a price in the page HTML:

- Meta tags: `product:price:amount`, `itemprop="price"`
- Elements with price-related class names (e.g. `price`, `product-price`, `sales`)
- JSON embedded in the page (e.g. `"price": "129.00"`)

If a site changes its markup, you can extend `extract_price()` in `tracker.py` with new patterns.

## Error Handling

- **Timeouts**: Request timeout is 15 seconds; a clear message is printed on timeout.
- **Invalid URLs / connection errors**: Reported with a short message.
- **403 / 429**: Message suggests the site may require headers or anti-bot handling.
- **Missing price**: Prints `Could not find price for: <url>` and skips appending to the CSV.

The script does not run on a schedule; it runs only when you execute `python tracker.py urls.txt`.
