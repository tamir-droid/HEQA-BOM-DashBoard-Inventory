import json
from pathlib import Path


def load_followup(data_dir: Path) -> dict:
    """Load followup tracking from followup.json. Returns empty dict if not found."""
    path = data_dir / "followup.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_followup(data_dir: Path, followup: dict) -> None:
    """Persist followup tracking to followup.json."""
    path = data_dir / "followup.json"
    path.write_text(json.dumps(followup, ensure_ascii=False, indent=2), encoding="utf-8")
