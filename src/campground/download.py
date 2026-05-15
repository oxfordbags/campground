import pathlib
import re
import shutil
import tempfile
import zipfile

from curl_cffi import requests

from .session import HEADERS


def fetch_and_extract(
    session: requests.Session,
    url: str,
    dest_dir: pathlib.Path,
    fallback_name: str,
    subdir_name: str,
) -> pathlib.Path:
    """Download to a temp directory, extract if zip, move result to dest_dir."""
    with tempfile.TemporaryDirectory(prefix="campground_") as tmp:
        tmp_path = pathlib.Path(tmp)
        zip_path = _fetch(session, url, tmp_path, fallback_name)

        if zip_path.suffix == ".zip":
            print("Extracting...")
            extracted = _unzip(zip_path, tmp_path, subdir_name)
            final = dest_dir / extracted.name
            shutil.move(str(extracted), final)
        else:
            final = dest_dir / zip_path.name
            shutil.move(str(zip_path), final)

    return final


def _fetch(session: requests.Session, url: str, dest_dir: pathlib.Path, fallback_name: str) -> pathlib.Path:
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


def _unzip(zip_path: pathlib.Path, dest_dir: pathlib.Path, subdir_name: str) -> pathlib.Path:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        top_level = {n.split("/")[0] for n in names}

        if len(top_level) == 1 and not any(n == top_level.copy().pop() for n in names):
            # All entries share a single root folder — extract directly so that
            # folder becomes the subdir, avoiding double-nesting.
            extract_to = dest_dir
            result_dir = dest_dir / top_level.pop()
        else:
            # Files at root — create a named subdir.
            extract_to = dest_dir / subdir_name
            extract_to.mkdir(parents=True, exist_ok=True)
            result_dir = extract_to

        zf.extractall(extract_to)

    zip_path.unlink()
    return result_dir


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
