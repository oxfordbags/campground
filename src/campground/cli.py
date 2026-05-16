import argparse
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys

from . import api, config, db, download
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


def _bulk_parser(prog: str, description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description=description)
    p.add_argument(
        "-f", "--format", choices=VALID_FORMATS, metavar="FORMAT",
        help=f"Audio format ({', '.join(VALID_FORMATS)}). Default: flac",
    )
    p.add_argument("-o", "--output", metavar="DIR", help="Output directory")
    p.add_argument("--cookies", metavar="STRING", help="Cookie string from browser dev tools")
    p.add_argument(
        "--cookies-file", dest="cookies_file", metavar="FILE",
        help="Path to a file containing the cookie string",
    )
    p.add_argument(
        "--overwrite", action="store_true",
        help="Re-download items that already exist in the output directory",
    )
    return p


def build_download_parser() -> argparse.ArgumentParser:
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
    p.add_argument(
        "--overwrite", action="store_true",
        help="Replace an existing download if it already exists in the output directory",
    )
    return p


def build_sync_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="campground sync",
        description="Re-sync your full Bandcamp library to the local database",
    )
    p.add_argument("--cookies", metavar="STRING", help="Cookie string from browser dev tools")
    p.add_argument(
        "--cookies-file", dest="cookies_file", metavar="FILE",
        help="Path to a file containing the cookie string",
    )
    return p


def build_search_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="campground search",
        description="Search your Bandcamp library by title or artist",
    )
    p.add_argument("query", nargs="+", help="Search terms")
    p.add_argument(
        "-f", "--format", choices=VALID_FORMATS, metavar="FORMAT",
        help=f"Audio format ({', '.join(VALID_FORMATS)}). Default: flac",
    )
    p.add_argument("-o", "--output", metavar="DIR", help="Output directory")
    p.add_argument("--cookies", metavar="STRING", help="Cookie string from browser dev tools")
    p.add_argument(
        "--cookies-file", dest="cookies_file", metavar="FILE",
        help="Path to a file containing the cookie string",
    )
    p.add_argument(
        "--overwrite", action="store_true",
        help="Re-download items that already exist in the output directory",
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


def apply_template(template: str, artist: str, album: str, year: str | None) -> pathlib.Path:
    filled = template.format(
        artist=safe_name(artist),
        album=safe_name(album),
        year=safe_name(year) if year else "",
    )
    # Strip leading/trailing separators from each component, drop empties.
    # This cleans up dangling " - " left by a missing year.
    parts = []
    for p in pathlib.PurePosixPath(filled).parts:
        cleaned = re.sub(r'^[\s\-_.]+|[\s\-_.]+$', '', p)
        if cleaned:
            parts.append(cleaned)
    return pathlib.Path(*parts) if parts else pathlib.Path(safe_name(f"{artist} - {album}"))


def _auth(cfg: config.Config):
    cookies = resolve_cookies(cfg)
    session = make_session(cookies)
    try:
        fan_id = api.get_fan_id(session)
    except Exception as e:
        sys.exit(f"Authentication failed — your cookies may have expired.\n{e}")
    return session, fan_id


def _do_sync(con, session, fan_id: int, full: bool = False) -> int:
    """Upsert collection items into the DB. Returns count of items written."""
    count = 0
    for item, _ in api.iter_collection(session, fan_id):
        if not full and db.has_item(con, item["sale_item_id"]):
            break
        db.upsert_item(con, item)
        count += 1
    con.commit()
    return count


def _download_one(session, item: dict, redownload_url: str | None, cfg: config.Config, overwrite: bool, con) -> bool:
    """Download a single item. Returns True on success, False on skip or error."""
    artist = item["band_name"]
    album = item["item_title"]
    sid = item["sale_item_id"]
    label = f"{artist} - {album}"

    year = db.get_year(con, sid)
    dest = cfg.output_dir

    if cfg.output_dir_explicit:
        dest.mkdir(parents=True, exist_ok=True)

    existing = dest / apply_template(cfg.path_template, artist, album, year)
    if existing.exists() and not overwrite:
        print(f"  Skipping (already exists): {label}")
        db.mark_downloaded(con, sid)
        return False

    if not redownload_url:
        print(f"  Skipping (no download URL): {label}")
        return False

    fmt = cfg.format
    try:
        downloads, year_from_blob = api.get_download_urls(session, redownload_url)
    except Exception as e:
        print(f"  Failed to get download page for {label}: {e}")
        return False

    # Cache year and recheck path if it changed
    if year_from_blob and year_from_blob != year:
        year = year_from_blob
        db.store_year(con, sid, year)
        existing = dest / apply_template(cfg.path_template, artist, album, year)
        if existing.exists() and not overwrite:
            print(f"  Skipping (already exists): {label}")
            db.mark_downloaded(con, sid)
            return False

    if fmt not in downloads:
        available = ", ".join(downloads.keys())
        print(f"  Skipping (format '{fmt}' not available, got: {available}): {label}")
        return False

    entry = downloads[fmt]

    if existing.exists():
        shutil.rmtree(existing) if existing.is_dir() else existing.unlink()

    name = apply_template(cfg.path_template, artist, album, year)
    try:
        path = download.fetch_and_extract(session, entry["url"], dest, safe_filename(label, fmt), str(name))
        db.mark_downloaded(con, sid)
        print(f"  Saved: {path}")
        return True
    except Exception as e:
        print(f"  Download failed for {label}: {e}")
        return False


def _batch_download(session, fan_id: int, target_ids: set[int], cfg: config.Config, overwrite: bool, con) -> tuple[int, int]:
    """
    One collection pass — download every item whose sale_item_id is in target_ids.
    Returns (succeeded, failed).
    """
    remaining = set(target_ids)
    total = len(remaining)
    done = 0
    failed = 0
    index = 0

    for item, redownload_url in api.iter_collection(session, fan_id):
        sid = item["sale_item_id"]
        if sid not in remaining:
            continue

        remaining.discard(sid)
        index += 1
        title = f"{item['band_name']} - {item['item_title']}"
        print(f"\n[{index}/{total}] {title}")

        if _download_one(session, item, redownload_url, cfg, overwrite, con):
            done += 1
        else:
            failed += 1

        if not remaining:
            break

    return done, failed


HELP = """
campground — download albums from your Bandcamp library

Usage:
  campground <url> [options]
  campground search <query>
  campground download-all [options]
  campground download-new [options]
  campground sync
  campground config

Options (download / download-all / download-new):
  -f, --format FORMAT      Audio format (default: flac)
                           Choices: mp3-v0, mp3-320, flac, aac-hi,
                                    vorbis, alac, wav, aiff-lossless
  -o, --output DIR         Output directory (default: current directory)
  --cookies STRING         Cookie string from browser dev tools
  --cookies-file FILE      Path to a file containing the cookie string
  --overwrite              Re-download items that already exist

Examples:
  campground https://artist.bandcamp.com/album/title
  campground https://artist.bandcamp.com/album/title --format mp3-320
  campground search "sea power"           # shows results, prompts to download
  campground download-all --output ~/Music/Bandcamp
  campground download-new --output ~/Music/Bandcamp
  campground sync

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


CONFIG_TEMPLATE = """\
[bandcamp]
cookies = ""

[download]
format = "flac"
# output_dir = "~/Music/Bandcamp"
# path_template = "{artist}/{year} - {album}"  # default: "{artist} - {album}"
"""


def edit_config():
    path = config.CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(CONFIG_TEMPLATE)
        print(f"Created {path}")

    editor = (
        os.environ.get("EDITOR")
        or os.environ.get("VISUAL")
        or ("open" if platform.system() == "Darwin" else None)
        or ("xdg-open" if platform.system() == "Linux" else None)
        or "notepad"
    )

    subprocess.run([editor, str(path)])


def main():
    if len(sys.argv) == 1:
        print(HELP.strip())
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "config":
        edit_config()
        sys.exit(0)

    try:
        if cmd == "sync":
            _run_sync()
        elif cmd == "search":
            _run_search()
        elif cmd == "download-all":
            _run_bulk(new_only=False)
        elif cmd == "download-new":
            _run_bulk(new_only=True)
        else:
            _run()
    except KeyboardInterrupt:
        print("\nCancelled.")
        os._exit(130)


def _run_sync():
    args = build_sync_parser().parse_args(sys.argv[2:])
    cfg = config.merge(config.load(), args)

    print("Authenticating...")
    session, fan_id = _auth(cfg)

    con = db.open_db()
    print("Syncing full library...")
    count = _do_sync(con, session, fan_id, full=True)
    print(f"Done. {count} items synced.")


def _run_search():
    args = build_search_parser().parse_args(sys.argv[2:])
    cfg = config.merge(config.load(), args)
    query = " ".join(args.query)

    print("Authenticating...")
    session, fan_id = _auth(cfg)

    con = db.open_db()

    print("Checking for new purchases...")
    count = _do_sync(con, session, fan_id, full=False)
    if count:
        print(f"{count} new item{'s' if count != 1 else ''} added.")

    results = db.search_items(con, query)

    if not results:
        print(f"No results for '{query}'.")
        return

    print(f"\n{len(results)} result{'s' if len(results) != 1 else ''} for '{query}':\n")
    for i, row in enumerate(results, 1):
        status = "" if row["download_available"] else " [not downloadable]"
        print(f"  {i}. {row['artist']} — {row['title']}{status}")
        print(f"     {row['item_url']}")

    try:
        answer = input("\nDownload which? (number or comma-separated, Enter to skip): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not answer:
        return

    selected = []
    for part in answer.split(","):
        part = part.strip()
        if not part.isdigit() or not (1 <= int(part) <= len(results)):
            print(f"Invalid selection: '{part}'")
            return
        selected.append(results[int(part) - 1])

    done = 0
    failed = 0
    for i, r in enumerate(selected, 1):
        label = f"{r['artist']} — {r['title']}"
        prefix = f"\n[{i}/{len(selected)}] " if len(selected) > 1 else "\n"
        if not r["download_available"]:
            print(f"{prefix}Skipping (not downloadable): {label}")
            failed += 1
            continue
        print(f"{prefix}{label}")
        print("  Fetching download link...")
        item, redownload_url = api.find_item_by_id(session, fan_id, r["sale_item_id"])
        if not item:
            print("  Could not locate in collection — try 'campground sync'")
            failed += 1
            continue
        if _download_one(session, item, redownload_url, cfg, args.overwrite, con):
            done += 1
        else:
            failed += 1

    if len(selected) > 1:
        print(f"\nDone. {done} downloaded, {failed} failed or skipped.")


def _run_bulk(new_only: bool):
    label = "download-new" if new_only else "download-all"
    args = _bulk_parser(
        f"campground {label}",
        "Download new purchases since last download" if new_only else "Download your entire Bandcamp library",
    ).parse_args(sys.argv[2:])
    cfg = config.merge(config.load(), args)

    print("Authenticating...")
    session, fan_id = _auth(cfg)

    con = db.open_db()

    print("Checking for new purchases...")
    synced = _do_sync(con, session, fan_id, full=False)
    if synced:
        print(f"{synced} new item{'s' if synced != 1 else ''} added to library.")

    target_ids = db.get_new_item_ids(con) if new_only else db.get_all_downloadable_ids(con)

    if not target_ids:
        print("Nothing to download.")
        return

    noun = "new purchase" if new_only else "item"
    print(f"Downloading {len(target_ids)} {noun}{'s' if len(target_ids) != 1 else ''}...")

    done, failed = _batch_download(session, fan_id, target_ids, cfg, args.overwrite, con)

    print(f"\nDone. {done} downloaded, {failed} failed or skipped.")


def _run():
    args = build_download_parser().parse_args()
    cfg = config.merge(config.load(), args)

    print("Authenticating...")
    session, fan_id = _auth(cfg)

    con = db.open_db()

    print("Checking for new purchases...")
    count = _do_sync(con, session, fan_id, full=False)
    if count:
        print(f"{count} new item{'s' if count != 1 else ''} added.")

    target_url = api.normalise_url(args.url)
    row = db.lookup_by_url(con, target_url)

    if not row:
        sys.exit(f"Not found in your collection: {args.url}")

    if not row["download_available"]:
        sys.exit("This item is not available to download (may be a pre-order or stream-only).")

    print(f"Found: {row['artist']} — {row['title']}")
    print("Fetching download link...")

    item, redownload_url = api.find_item_by_id(session, fan_id, row["sale_item_id"])

    if not item:
        sys.exit("Could not locate item in collection — try running 'campground sync'.")

    if not redownload_url:
        sys.exit("This item has no download URL.")

    fmt = cfg.format
    print(f"Fetching {fmt} download link...")
    try:
        downloads, year = api.get_download_urls(session, redownload_url)
    except Exception as e:
        sys.exit(f"Could not fetch download page: {e}")

    if year:
        db.store_year(con, row["sale_item_id"], year)

    if fmt not in downloads:
        available = ", ".join(downloads.keys())
        sys.exit(f"Format '{fmt}' not available. Available formats: {available}")

    entry = downloads[fmt]
    print(f"  Size: {entry.get('size_mb', 'unknown')}")

    artist, album = row["artist"], row["title"]
    title = f"{artist} - {album}"
    name = apply_template(cfg.path_template, artist, album, year)
    dest = cfg.output_dir

    if cfg.output_dir_explicit:
        dest.mkdir(parents=True, exist_ok=True)

    existing = dest / name
    if existing.exists():
        if not args.overwrite:
            print(f"Already exists, skipping: {existing}")
            print("Use --overwrite to replace it.")
            sys.exit(0)
        shutil.rmtree(existing) if existing.is_dir() else existing.unlink()

    print(f"Downloading {entry.get('size_mb', '')} to {dest}...")

    try:
        path = download.fetch_and_extract(session, entry["url"], dest, safe_filename(title, fmt), str(name))
        db.mark_downloaded(con, row["sale_item_id"])
    except Exception as e:
        sys.exit(f"Download failed: {e}")

    print(f"Saved: {path}")
