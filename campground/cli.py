import argparse
import os
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


def safe_name(title: str) -> str:
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in title).strip()


def safe_filename(title: str, fmt: str) -> str:
    return f"{safe_name(title)}{FORMAT_EXT[fmt]}"


HELP = """
campground — download albums from your Bandcamp library

Usage:
  campground <url> [options]

Options:
  -f, --format FORMAT      Audio format (default: flac)
                           Choices: mp3-v0, mp3-320, flac, aac-hi,
                                    vorbis, alac, wav, aiff-lossless
  -o, --output DIR         Output directory (default: current directory)
  --cookies STRING         Cookie string from browser dev tools
  --cookies-file FILE      Path to a file containing the cookie string

Examples:
  campground https://artist.bandcamp.com/album/title
  campground https://artist.bandcamp.com/album/title --format mp3-320
  campground https://artist.bandcamp.com/album/title --output ~/Downloads

Setup (one-time):
  campground uses your browser session cookies to authenticate.

  1. Log in to bandcamp.com in your browser
  2. Open Dev Tools (Cmd+Option+I) → Network tab
  3. Refresh the page and click any bandcamp.com request
  4. Copy the full value of the Cookie: request header

  Then either pass it directly:
    campground <url> --cookies "your_cookie_string"

  Or save it to ~/.config/campground/config.toml:
    [bandcamp]
    cookies = "your_cookie_string"

    [download]
    format = "flac"
    output_dir = "~/Music/Bandcamp"  # optional
"""


def main():
    if len(sys.argv) == 1:
        print(HELP.strip())
        sys.exit(0)

    try:
        _run()
    except KeyboardInterrupt:
        print("\nCancelled.")
        os._exit(130)


def _run():
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

    name = safe_name(title)
    dest = cfg.output_dir

    if cfg.output_dir_explicit:
        dest.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {entry.get('size_mb', '')} to {dest}...")

    try:
        path = download.fetch_and_extract(session, entry["url"], dest, safe_filename(title, fmt), name)
    except Exception as e:
        sys.exit(f"Download failed: {e}")

    print(f"Saved: {path}")
