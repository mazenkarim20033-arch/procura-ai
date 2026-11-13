"""Versioned prompt registry. Prompt files are named `<name>@v<N>.md`, are never edited in place (add a
new version instead), and their SHA-256 is recorded with every call so a result can be traced to the
exact text that produced it."""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_DIR = Path(__file__).parent
_PATTERN = re.compile(r"^(?P<name>[a-z_]+)@v(?P<version>\d+)\.md$")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str
    sha256: str

    @property
    def label(self) -> str:
        return f"{self.name}@v{self.version}"


def load_prompt(name: str, version: int | None = None) -> Prompt:
    versions = {}
    for f in _DIR.glob("*.md"):
        m = _PATTERN.match(f.name)
        if m and m["name"] == name:
            versions[int(m["version"])] = f
    if not versions:
        raise KeyError(f"unknown prompt '{name}'")
    chosen = version if version is not None else max(versions)
    if chosen not in versions:
        raise KeyError(f"prompt '{name}' has no version {chosen}")
    text = versions[chosen].read_text(encoding="utf-8")
    return Prompt(name, chosen, text, hashlib.sha256(text.encode("utf-8")).hexdigest())
