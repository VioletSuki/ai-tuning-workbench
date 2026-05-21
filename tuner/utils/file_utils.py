import json
import shutil
from pathlib import Path


def ensure_dir(path: str | Path) -> Path:
    """Create directory (including parents) if it does not exist. Returns the Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(path: str | Path, data: dict) -> None:
    """Write a dict as pretty-printed JSON to the given path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def append_jsonl(path: str | Path, data: dict) -> None:
    """Append a single JSON line to a JSONL file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")


def copy_file_if_exists(src: str | Path, dst: str | Path) -> bool:
    """Copy src to dst if src exists. Returns True if copied, False otherwise."""
    src_p = Path(src)
    if not src_p.is_file():
        return False
    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_p, dst_p)
    return True
