thonimport argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from extractors.listings_parser import scrape_search_url
from outputs.exporter import export_results

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def load_config(path: Optional[Path]) -> Dict[str, Any]:
    if not path:
        return {}

    if not path.exists():
        logging.warning("Config file %s not found. Using defaults.", path)
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            config = json.load(f)
        if not isinstance(config, dict):
            logging.warning("Config file %s does not contain a JSON object.", path)
            return {}
        return config
    except Exception as exc:
        logging.error("Failed to read config file %s: %s", path, exc)
        return {}

def read_input_urls(path: Path) -> List[str]:
    if not path.exists():
        logging.error("Input file %s not found.", path)
        return []

    urls: List[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            urls.append(stripped)

    if not urls:
        logging.warning("No URLs found in %s.", path)

    return urls

def load_previous_results(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        logging.info("Previous output file %s not found. Delta mode will treat all listings as new.", path)
        return []

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        logging.warning("Previous results file %s did not contain a JSON array.", path)
        return []
    except Exception as exc:
        logging.error("Failed to load previous results from %s: %s", path, exc)
        return []

def build_listing_id(listing: Dict[str, Any]) -> str:
    # Prefer a stable URL, fall back to title+address.
    url = listing.get("listing_url") or listing.get("url") or ""
    if url:
        return str(url)
    title = listing.get("title") or ""
    address = listing.get("address") or ""
    return f"{title}|{address}".strip()

def apply_delta_mode(
    current: List[Dict[str, Any]],
    previous: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    prev_index: Dict[str, Dict[str, Any]] = {}
    for item in previous:
        prev_index[build_listing_id(item)] = item

    curr_ids = {build_listing_id(item) for item in current}
    prev_ids = set(prev_index.keys())

    new_ids = curr_ids - prev_ids
    delisted_ids = prev_ids - curr_ids

    results: List[Dict[str, Any]] = []

    for item in current:
        listing_id = build_listing_id(item)
        status = "new" if listing_id in new_ids else "present"
        item = dict(item)
        item["apify_monitoring_status"] = status
        results.append(item)

    for listing_id in delisted_ids:
        prev_item = dict(prev_index[listing_id])
        prev_item["apify_monitoring_status"] = "delisted"
        results.append(prev_item)

    return results

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape immobilienscout24.de search results from one or more search URLs."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/inputs.sample.txt"),
        help="Path to a text file with one search URL per line.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/sample_output.json"),
        help="Path to the output file (JSON/CSV/HTML depending on --format).",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv", "html"],
        default="json",
        help="Output format.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("src/config/settings.example.json"),
        help="Path to a JSON config file with scraper & export settings.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Override max pages to scrape per URL (otherwise taken from config).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Override delay (in seconds) between page requests.",
    )
    parser.add_argument(
        "--delta",
        action="store_true",
        help="Enable delta mode to mark new and delisted listings.",
    )
    parser.add_argument(
        "--previous-output",
        type=Path,
        default=None,
        help="Path to previous output JSON for delta mode (defaults to --output).",
    )
    parser.add_argument(
        "--proxy",
        type=str,
        default=None,
        help="HTTP/HTTPS proxy URL (e.g. http://user:pass@host:port). Overrides config.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)

def build_session_config(
    config: Dict[str, Any],
    args: argparse.Namespace,
) -> Dict[str, Any]:
    user_agent = config.get(
        "user_agent",
        "Mozilla/5.0 (compatible; immobilienscout24-scraper/1.0; +https://example.com)",
    )
    headers = {
        "User-Agent": user_agent,
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    }

    proxies_config = config.get("proxies", {})
    proxy_from_args = args.proxy
    proxies = None
    if proxy_from_args:
        proxies = {"http": proxy_from_args, "https": proxy_from_args}
    elif isinstance(proxies_config, dict) and proxies_config:
        proxies = proxies_config

    max_pages = args.max_pages if args.max_pages is not None else int(config.get("max_pages", 5))
    delay = args.delay if args.delay is not None else float(config.get("delay_between_requests", 1.0))
    timeout = float(config.get("timeout_seconds", 20.0))

    return {
        "headers": headers,
        "proxies": proxies,
        "max_pages": max_pages,
        "delay": delay,
        "timeout": timeout,
    }

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)

    config = load_config(args.config)
    session_cfg = build_session_config(config, args)

    urls = read_input_urls(args.input)
    if not urls:
        logging.error("No URLs to scrape. Exiting.")
        return 1

    all_results: List[Dict[str, Any]] = []

    for idx, url in enumerate(urls, start=1):
        logging.info("Scraping URL %d/%d: %s", idx, len(urls), url)
        try:
            listings = scrape_search_url(
                search_url=url,
                max_pages=session_cfg["max_pages"],
                delay=session_cfg["delay"],
                headers=session_cfg["headers"],
                proxies=session_cfg["proxies"],
                timeout=session_cfg["timeout"],
            )
            logging.info("Found %d listings for URL %s", len(listings), url)
            all_results.extend(listings)
        except Exception as exc:
            logging.error("Failed to scrape URL %s: %s", url, exc, exc_info=args.verbose)
        finally:
            if idx < len(urls) and session_cfg["delay"] > 0:
                time.sleep(session_cfg["delay"])

    if args.delta:
        previous_path = args.previous_output or args.output
        previous_results = load_previous_results(previous_path)
        all_results = apply_delta_mode(all_results, previous_results)
    else:
        for item in all_results:
            if "apify_monitoring_status" not in item:
                item["apify_monitoring_status"] = "new"

    if not all_results:
        logging.warning("No listings were scraped. Output file will still be created but empty.")

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        export_results(all_results, args.format, args.output)
        logging.info("Exported %d listings to %s (%s format).", len(all_results), args.output, args.format)
    except Exception as exc:
        logging.error("Failed to export results: %s", exc)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())