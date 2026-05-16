import html as html_module
import json
import re
from urllib.parse import urlparse, urlunparse

from curl_cffi import requests

from .session import HEADERS

COLLECTION_SUMMARY_URL  = "https://bandcamp.com/api/fan/2/collection_summary"
COLLECTION_ITEMS_URL    = "https://bandcamp.com/api/fancollection/1/collection_items"


def get_fan_id(session: requests.Session) -> int:
    resp = session.get(COLLECTION_SUMMARY_URL, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()["fan_id"]


def iter_collection(session: requests.Session, fan_id: int, page_size: int = 50):
    """Yield (item, redownload_url) pairs, paginating until exhausted."""
    token = "9999999999::a::"
    while True:
        payload = {"fan_id": fan_id, "older_than_token": token, "count": page_size}
        data = session.post(COLLECTION_ITEMS_URL, json=payload, headers=HEADERS).json()
        redownload_urls = data.get("redownload_urls", {})
        for item in data.get("items", []):
            yield item, redownload_urls.get(f"p{item['sale_item_id']}")
        if not data.get("more_available"):
            break
        token = data["last_token"]


def find_item(session: requests.Session, fan_id: int, target_url: str):
    """Return (item, redownload_url) for the first collection item matching target_url."""
    target = normalise_url(target_url)
    checked = 0
    for item, redownload_url in iter_collection(session, fan_id):
        if normalise_url(item.get("item_url", "")) == target:
            return item, redownload_url
        checked += 1
        if checked % 50 == 0:
            print(f"  ({checked} items searched...)")
    return None, None


def find_item_by_id(session: requests.Session, fan_id: int, sale_item_id: int):
    """Return (item, redownload_url) for a known sale_item_id, stopping as soon as found."""
    for item, redownload_url in iter_collection(session, fan_id):
        if item["sale_item_id"] == sale_item_id:
            return item, redownload_url
    return None, None


def normalise_url(url: str) -> str:
    """Normalise to https, strip query string and fragment, lowercase."""
    p = urlparse(url.strip())
    return urlunparse(p._replace(scheme="https", query="", fragment="")).rstrip("/").lower()


def get_download_urls(session: requests.Session, redownload_url: str) -> dict:
    """Return the downloads dict from a signed redownload URL (format name → {url, size_mb, …})."""
    resp = session.get(redownload_url, headers=HEADERS)
    resp.raise_for_status()
    blobs = re.findall(r'data-blob="([^"]{20,})"', resp.text)
    if not blobs:
        raise RuntimeError("Could not find data blob on download page")
    blob = json.loads(html_module.unescape(blobs[0]))
    items = blob.get("digital_items", [])
    if not items:
        raise RuntimeError("No downloadable items on this page")
    return items[0].get("downloads", {})
