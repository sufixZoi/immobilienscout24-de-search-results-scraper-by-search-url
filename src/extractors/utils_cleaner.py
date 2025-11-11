thonimport re
from typing import Any, Dict

from bs4 import Tag

def clean_text(text: Any) -> str:
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def parse_price(text: str) -> str:
    """
    Return the price string as-is but trimmed.
    You could extend this to parse numeric values if needed.
    """
    return clean_text(text)

def parse_address(text: str) -> str:
    """
    Normalize the address field.
    """
    return clean_text(text)

def parse_energy_info(text: str) -> str:
    """
    Extract a substring that looks like an energy label, e.g. 'B, 68 kWh/(m²·a)'.
    """
    if not text:
        return ""
    # Look for kWh/(m²
    match = re.search(r"[A-G][,\s]+[\d,.]+\s*kWh/\(m².?a\)", text)
    if match:
        return clean_text(match.group(0))
    # Fallback: try to find a single energy class (A+, A, B, etc.)
    match = re.search(r"\bA\+{0,2}|[B-G]\b", text)
    if match:
        return clean_text(match.group(0))
    return ""

def parse_construction_date(text: str) -> str:
    """
    Look for a year-like pattern in the text.
    """
    if not text:
        return ""
    match = re.search(r"\b(18|19|20)\d{2}\b", text)
    return match.group(0) if match else ""

def parse_transportation(text: str) -> str:
    """
    Return any substring that hints at proximity to transport, otherwise return the input text if short.
    """
    if not text:
        return ""
    keywords = ["Bahnhof", "Bus", "U-Bahn", "S-Bahn", "Tram", "Straßenbahn", "train", "bus", "metro"]
    if any(k.lower() in text.lower() for k in keywords):
        return text
    # If nothing obvious is found but text is short, treat it as transportation-related meta.
    if len(text) <= 120:
        return text
    return ""

def extract_contact_details(container: Tag) -> Dict[str, str]:
    """
    Try to extract contact email/phone if present in the container.
    On search result pages this is often missing; we just do our best.
    """
    info: Dict[str, str] = {"email": "", "phone": ""}

    # Email via mailto:
    mail_link = container.find("a", href=True)
    if mail_link and isinstance(mail_link["href"], str) and "mailto:" in mail_link["href"]:
        email = mail_link["href"].split("mailto:", 1)[-1]
        info["email"] = email.strip()

    # Try to find something that looks like a phone number.
    text = clean_text(container.get_text(" "))
    phone_match = re.search(r"(\+?\d[\d\s()/\-]{6,})", text)
    if phone_match:
        info["phone"] = phone_match.group(0).strip()

    return info