import tomllib
import pathlib
from dataclasses import dataclass, field

CONFIG_PATH = pathlib.Path.home() / ".config" / "campground" / "config.toml"
DEFAULT_FORMAT = "flac"
DEFAULT_OUTPUT = pathlib.Path.home() / "Music" / "Bandcamp"


@dataclass
class Config:
    username: str = ""
    cookies: str = ""
    cookies_file: str = ""
    format: str = DEFAULT_FORMAT
    output_dir: pathlib.Path = field(default_factory=lambda: DEFAULT_OUTPUT)

    def __post_init__(self):
        if isinstance(self.output_dir, str):
            self.output_dir = pathlib.Path(self.output_dir).expanduser()


def load(path: pathlib.Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    bc = data.get("bandcamp", {})
    dl = data.get("download", {})
    return Config(
        username=bc.get("username", ""),
        cookies=bc.get("cookies", ""),
        cookies_file=bc.get("cookies_file", ""),
        format=dl.get("format", DEFAULT_FORMAT),
        output_dir=dl.get("output_dir", str(DEFAULT_OUTPUT)),
    )


def merge(base: Config, args) -> Config:
    return Config(
        username=getattr(args, "username", None) or base.username,
        cookies=getattr(args, "cookies", None) or base.cookies,
        cookies_file=getattr(args, "cookies_file", None) or base.cookies_file,
        format=getattr(args, "format", None) or base.format,
        output_dir=getattr(args, "output", None) or str(base.output_dir),
    )
