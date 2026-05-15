# campground

A lightweight command-line tool for downloading albums from your Bandcamp library.

## Requirements

- Python 3.11+
- A Bandcamp account with purchased items

## Installation

```sh
pip install git+https://github.com/yourusername/campground.git
```

## Setup

Campground authenticates using your browser session cookies. You only need to do this once (or when your session expires).

1. Log in to [bandcamp.com](https://bandcamp.com) in your browser
2. Open Dev Tools (`Cmd+Option+I` on Mac, `F12` on Windows)
3. Go to the **Network** tab and refresh the page
4. Click any `bandcamp.com` request and find the **Cookie:** request header
5. Copy the full value

Then add it to `~/.config/campground/config.toml`:

```toml
[bandcamp]
cookies = "your_cookie_string_here"

[download]
format = "flac"           # optional, default: flac
output_dir = "~/Music"    # optional, default: current directory
```

Or pass cookies directly on the command line:

```sh
campground <url> --cookies "your_cookie_string_here"
```

## Usage

```sh
campground <bandcamp-album-url> [options]
```

**Examples:**

```sh
# Download an album in the default format (flac)
campground https://artist.bandcamp.com/album/album-title

# Choose a format
campground https://artist.bandcamp.com/album/album-title --format mp3-320

# Download to a specific directory
campground https://artist.bandcamp.com/album/album-title --output ~/Music/Bandcamp

# Re-download and replace an existing copy
campground https://artist.bandcamp.com/album/album-title --overwrite
```

## Options

| Flag | Description |
|---|---|
| `-f`, `--format` | Audio format (see below). Default: `flac` |
| `-o`, `--output` | Output directory. Default: current directory |
| `--cookies` | Cookie string from browser dev tools |
| `--cookies-file` | Path to a file containing the cookie string |
| `--overwrite` | Replace an existing download in the output directory |

**Supported formats:** `mp3-v0`, `mp3-320`, `flac`, `aac-hi`, `vorbis`, `alac`, `wav`, `aiff-lossless`

## How it works

Campground uses your session cookies to access the Bandcamp collection API, locates the requested album, fetches a signed download link for your chosen format, and streams the file to a temporary directory before extracting and moving it to the output directory. If anything goes wrong the temporary files are cleaned up automatically.
