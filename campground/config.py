import tomllib
import pathlib
from dataclasses import dataclass, field

CONFIG_PATH = pathlib.Path.home() / ".config" / "campground" / "config.toml"
DEFAULT_FORMAT = "flac"


@dataclass
class Config:
    username: str = ""
    cookies: str = ""
    cookies_file: str = ""
    format: str = DEFAULT_FORMAT
    output_dir: pathlib.Path | None = None  # None resolves to cwd at runtime
    output_dir_explicit: bool = False       # True when set by config or CLI flag

    def __post_init__(self):
        if self.output_dir is None:
            self.output_dir = pathlib.Path.cwd()
        elif isinstance(self.output_dir, str):
            self.output_dir = pathlib.Path(self.output_dir).expanduser()


def load(path: pathlib.Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    bc = data.get("bandcamp", {})
    dl = data.get("download", {})
    raw_output = dl.get("output_dir")
    return Config(
        username=bc.get("username", ""),
        cookies=bc.get("cookies", ""),
        cookies_file=bc.get("cookies_file", ""),
        format=dl.get("format", DEFAULT_FORMAT),
        output_dir=raw_output,
        output_dir_explicit=raw_output is not None,
    )


def merge(base: Config, args) -> Config:
    cli_output = getattr(args, "output", None)
    return Config(
        username=getattr(args, "username", None) or base.username,
        cookies=getattr(args, "cookies", None) or base.cookies,
        cookies_file=getattr(args, "cookies_file", None) or base.cookies_file,
        format=getattr(args, "format", None) or base.format,
        output_dir=cli_output or str(base.output_dir),
        output_dir_explicit=bool(cli_output) or base.output_dir_explicit,
    )
