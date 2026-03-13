import json
from pathlib import Path

SITE_INV_FILENAME = "site_inventory.json"


def load_site_inventory(data_dir: Path) -> dict:
    """Load site inventory from site_inventory.json. Returns empty dict if not found."""
    path = data_dir / SITE_INV_FILENAME
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_site_inventory(data_dir: Path, site_inv: dict) -> None:
    """Persist site inventory to site_inventory.json."""
    path = data_dir / SITE_INV_FILENAME
    path.write_text(json.dumps(site_inv, ensure_ascii=False, indent=2), encoding="utf-8")
