import argparse
import pathlib
import sys

from . import api, config, download
from .session import make as make_session, parse_cookie_string

VALID_FORMATS = [
    "mp3-v0", "mp3-320", "flac", "aac-hi",
    "vorbis", "alac", "wav", "aiff-lossless",
]

FORMAT_EXT = {
    "mp3-v0":       ".mp3",
    "mp3-320":      ".mp3",
    "flac":         ".flac",
    "aac-hi":       ".m4a",
    "vorbis":       ".ogg",
    "alac":         ".m4a",
    "wav":          ".wav",
    "aiff-lossless":".aiff",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="campground",
        description="Download albums from your Bandcamp library",
    )
    p.add_argument("url", help="Bandcamp album or track URL")
    p.add_argument(
        "-f", "--format", choices=VALID_FORMATS, metavar="FORMAT",
        help=f"Audio format ({', '.join(VALID_FORMATS)}). Default: flac",
    )
    p.add_argument("-o", "--output", metavar="DIR", help="Output directory")
    p.add_argument("--cookies", metavar="STRING", help="Cookie string copied from browser dev tools")
    p.add_argument(
        "--cookies-file", dest="cookies_file", metavar="FILE",
        help="Path to a file containing the cookie string",
    )
    return p


def resolve_cookies(cfg: config.Config) -> dict:
    cookie_str = cfg.cookies
    if not cookie_str and cfg.cookies_file:
        path = pathlib.Path(cfg.cookies_file).expanduser()
        if not path.exists():
            sys.exit(f"Cookies file not found: {path}")
        cookie_str = path.read_text().strip()
    if not cookie_str:
        sys.exit(
            "No cookies provided. Supply them via --cookies, --cookies-file, or config file.\n\n"
            "To get your cookie string:\n"
            "  1. Log in to bandcamp.com in your browser\n"
            "  2. Open Dev Tools (Cmd+Option+I on Mac) → Network tab\n"
            "  3. Refresh the page and click any bandcamp.com request\n"
            "  4. Copy the full value of the 'Cookie:' request header"
        )
    return parse_cookie_string(cookie_str)


def safe_filename(title: str, fmt: str) -> str:
    stem = "".join(c if c.isalnum() or c in " -_." else "_" for c in title)
    return f"{stem.strip()}{FORMAT_EXT[fmt]}"


def main():
    args = build_parser().parse_args()
    cfg = config.merge(config.load(), args)

    cookies = resolve_cookies(cfg)
    session = make_session(cookies)

    print("Authenticating...")
    try:
        fan_id = api.get_fan_id(session)
    except Exception as e:
        sys.exit(f"Authentication failed — your cookies may have expired.\n{e}")

    target_url = args.url.rstrip("/")
    print(f"Searching collection for {target_url}...")

    item, redownload_url = api.find_item(session, fan_id, target_url)
    if not item:
        sys.exit(f"Not found in your collection: {target_url}")

    title = f"{item['band_name']} - {item['item_title']}"
    print(f"Found: {title}")

    if not redownload_url:
        sys.exit("This item has no download URL.")

    fmt = cfg.format
    print(f"Fetching {fmt} download link...")
    try:
        downloads = api.get_download_urls(session, redownload_url)
    except Exception as e:
        sys.exit(f"Could not fetch download page: {e}")

    if fmt not in downloads:
        available = ", ".join(downloads.keys())
        sys.exit(f"Format '{fmt}' not available. Available formats: {available}")

    entry = downloads[fmt]
    print(f"  Size: {entry.get('size_mb', 'unknown')}")

    filename = safe_filename(title, fmt)
    dest = cfg.output_dir
    print(f"Downloading to {dest / filename}...")

    try:
        path = download.fetch(session, entry["url"], dest, filename)
    except Exception as e:
        sys.exit(f"Download failed: {e}")

    print(f"Saved: {path}")
