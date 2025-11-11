thonimport logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

from .utils_cleaner import (
    clean_text,
    extract_contact_details,
    parse_address,
    parse_construction_date,
    parse_energy_info,
    parse_price,
    parse_transportation,
)

logger = logging.getLogger(__name__)

def _build_page_url(base_url: str, page: int) -> str:
    """
    Try to build a paginated URL by manipulating common 'pagenumber' or 'page' parameters.
    If none are present, append one.
    """
    if page == 1:
        return base_url

    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query))

    if "pagenumber" in query:
        query["pagenumber"] = str(page)
    elif "page" in query:
        query["page"] = str(page)
    else:
        query["pagenumber"] = str(page)

    new_query = urlencode(query, doseq=True)
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)

def _request_page(
    url: str,
    headers: Dict[str, str],
    proxies: Optional[Dict[str, str]],
    timeout: float,
) -> Optional[str]:
    try:
        resp = requests.get(url, headers=headers, proxies=proxies, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("Got status %s for %s", resp.status_code, url)
            return None
        return resp.text
    except requests.RequestException as exc:
        logger.error("HTTP error for %s: %s", url, exc)
        return None

def _find_listing_containers(soup: BeautifulSoup) -> List[Tag]:
    """
    Try a set of selectors that commonly match ads on immobilienscout24.de.
    If nothing is found, fall back to a generic heuristic.
    """
    selectors = [
        "article[data-id]",
        "article[data-obid]",
        "div.result-list-entry",
        "div.result-list__listing",
    ]
    containers: List[Tag] = []
    for selector in selectors:
        containers = list(soup.select(selector))
        if containers:
            logger.debug("Found %d listing containers using selector '%s'", len(containers), selector)
            break

    if not containers:
        # Generic fallback: look for articles with links to 'expose'
        for article in soup.find_all("article"):
            link = article.find("a", href=True)
            if link and "expose" in link["href"]:
                containers.append(article)

    return containers

def _extract_listing_from_container(container: Tag) -> Dict[str, Any]:
    listing: Dict[str, Any] = {}

    # Title
    title_tag = container.select_one("h2, h3, h5, .result-list-entry__brand-title, .result-list-entry__criteria")
    listing["title"] = clean_text(title_tag.get_text()) if title_tag else ""

    # URL (listing URL)
    link_tag = container.find("a", href=True)
    if link_tag:
        href = link_tag["href"]
        listing["listing_url"] = href

    # Description
    desc_tag = container.select_one(".result-list-entry__criteria .result-list-entry__primary-criterion, p")
    listing["description"] = clean_text(desc_tag.get_text()) if desc_tag else ""

    # Price
    price_tag = container.select_one(".result-list-entry__primary-criterion strong, .text-ellipsis, .result-list-entry__rent span, .result-list-entry__price span")
    price_text = clean_text(price_tag.get_text()) if price_tag else ""
    listing["price"] = parse_price(price_text)

    # Address / location
    addr_tag = container.select_one(".result-list-entry__address, .result-list-entry__criteria span, .result-list-entry__region")
    addr_text = clean_text(addr_tag.get_text()) if addr_tag else ""
    listing["address"] = parse_address(addr_text)

    # Energy info & construction date & transportation try to read from generic meta/info sections
    details_text_chunks: List[str] = []
    for css in [
        ".result-list-entry__criteria",
        ".result-list-entry__primary-criterion",
        ".result-list-entry__secondary-criterion",
    ]:
        for tag in container.select(css):
            txt = clean_text(tag.get_text())
            if txt:
                details_text_chunks.append(txt)

    details_text = " | ".join(details_text_chunks)

    listing["energyInformation"] = parse_energy_info(details_text)
    listing["constructionDate"] = parse_construction_date(details_text)
    listing["transportation"] = parse_transportation(details_text)

    # Publisher/contact info (may not be present in search results; try to guess)
    publisher_tag = container.select_one(".result-list-entry__contact-name, .result-list-entry__provider-logo, .result-list-entry__brand-title")
    listing["publisher"] = clean_text(publisher_tag.get_text()) if publisher_tag else ""

    contact = extract_contact_details(container)
    if contact.get("email"):
        listing["email"] = contact["email"]
    if contact.get("phone"):
        listing["phone"] = contact["phone"]

    return listing

def scrape_search_url(
    search_url: str,
    max_pages: int,
    delay: float,
    headers: Dict[str, str],
    proxies: Optional[Dict[str, str]],
    timeout: float,
) -> List[Dict[str, Any]]:
    """
    Scrape one immobilienscout24.de search results URL and return a list of listing dicts.
    """
    results: List[Dict[str, Any]] = []
    seen_ids = set()

    for page in range(1, max_pages + 1):
        page_url = _build_page_url(search_url, page)
        logger.info("Requesting page %d: %s", page, page_url)
        html = _request_page(page_url, headers=headers, proxies=proxies, timeout=timeout)
        if not html:
            if page == 1:
                logger.warning("No HTML returned for first page; stopping.")
            break

        soup = BeautifulSoup(html, "lxml")
        containers = _find_listing_containers(soup)

        if not containers:
            logger.info("No listing containers found on page %d. Assuming end of results.", page)
            break

        page_count = 0
        for container in containers:
            listing = _extract_listing_from_container(container)
            listing_id = listing.get("listing_url") or listing.get("title") or None
            if not listing_id:
                continue
            if listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)
            results.append(listing)
            page_count += 1

        logger.info("Extracted %d listings from page %d.", page_count, page)

        # Simple heuristic: if we see very few listings on a page, assume it's the last.
        if page_count == 0:
            logger.info("No listings on page %d. Stopping pagination.", page)
            break

        if page < max_pages and delay > 0:
            time.sleep(delay)

    return results