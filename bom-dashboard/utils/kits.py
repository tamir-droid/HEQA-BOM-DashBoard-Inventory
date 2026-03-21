"""Production kit presets — save/load named sets of BOM quantities."""
from __future__ import annotations
import json
from pathlib import Path


KITS_FILE = "kits.json"


def load_kits(data_dir: Path) -> dict:
    """Load kits from kits.json. Returns empty dict if not found."""
    path = data_dir / KITS_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_kits(data_dir: Path, kits: dict) -> None:
    """Persist kits to kits.json."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / KITS_FILE
    path.write_text(json.dumps(kits, ensure_ascii=False, indent=2), encoding="utf-8")
