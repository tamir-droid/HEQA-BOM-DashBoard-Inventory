import json
from pathlib import Path


def load_hidden(data_dir: Path) -> set:
    """Load the set of hidden VPNs from hidden.json."""
    path = data_dir / "hidden.json"
    if path.exists():
        try:
            return set(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_hidden(data_dir: Path, hidden: set) -> None:
    """Persist the set of hidden VPNs to hidden.json."""
    path = data_dir / "hidden.json"
    path.write_text(json.dumps(sorted(hidden), ensure_ascii=False, indent=2), encoding="utf-8")
