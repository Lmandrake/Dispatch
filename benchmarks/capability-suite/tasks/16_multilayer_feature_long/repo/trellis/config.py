"""Optional per-user settings file.

trellis reads ``~/.trellisrc`` (or the file named by ``TRELLIS_CONFIG``), an
INI file with one ``[trellis]`` section::

    [trellis]
    db = ~/work/tracker.db
    user = ana
    project = WEB
    width = 100

Command-line options win over environment variables, which win over the
file.  Unknown keys are an error so typos do not go unnoticed.  The file is
optional; a missing file means "no settings".
"""

import configparser
import os
from dataclasses import dataclass

from trellis.errors import ValidationError

KNOWN_KEYS = ("db", "user", "project", "width")
DEFAULT_WIDTH = 80


@dataclass(frozen=True)
class Settings:
    db: str = ""
    user: str = ""
    project: str = ""
    width: int = DEFAULT_WIDTH


def config_path(environ=None):
    environ = os.environ if environ is None else environ
    explicit = environ.get("TRELLIS_CONFIG")
    if explicit:
        return explicit
    home = environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".trellisrc")


def load_settings(path=None, environ=None):
    path = path or config_path(environ)
    if not os.path.exists(path):
        return Settings()
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with open(path, encoding="utf-8") as fh:
            parser.read_file(fh)
    except (OSError, configparser.Error) as exc:
        raise ValidationError(f"cannot read settings file {path}: {exc}") from None
    if not parser.has_section("trellis"):
        return Settings()
    section = parser["trellis"]
    unknown = sorted(set(section) - set(KNOWN_KEYS))
    if unknown:
        raise ValidationError(f"{path}: unknown setting(s) {', '.join(unknown)}")
    width = DEFAULT_WIDTH
    if "width" in section:
        try:
            width = int(section["width"])
        except ValueError:
            raise ValidationError(f"{path}: width must be an integer") from None
        if not 40 <= width <= 400:
            raise ValidationError(f"{path}: width must be 40..400")
    db = section.get("db", "")
    return Settings(db=os.path.expanduser(db) if db else "", user=section.get("user", ""),
                    project=section.get("project", "").upper(), width=width)
