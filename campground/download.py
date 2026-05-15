import pathlib
import re

from curl_cffi import requests

from .session import HEADERS


def fetch(session: requests.Session, url: str, dest_dir: pathlib.Path, fallback_name: str) -> pathlib.Path:
    dest_dir.mkdir(parents=True, exist_ok=True)

    resp = session.get(url, headers=HEADERS, stream=True)
    resp.raise_for_status()

    filename = _filename_from_headers(resp.headers) or fallback_name
    filepath = dest_dir / filename

    total = int(resp.headers.get("content-length", 0))
    received = 0

    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
                received += len(chunk)
                _print_progress(filename, received, total)

    print()
    return filepath


def _filename_from_headers(headers) -> str:
    cd = headers.get("content-disposition", "")
    match = re.search(r'filename="([^"]+)"', cd)
    return match.group(1) if match else ""


def _print_progress(filename: str, received: int, total: int):
    mb = received / 1_048_576
    if total:
        pct = received * 100 // total
        print(f"\r  {filename}: {pct}% ({mb:.1f} MB)", end="", flush=True)
    else:
        print(f"\r  {filename}: {mb:.1f} MB", end="", flush=True)
