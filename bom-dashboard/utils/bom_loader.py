"""Shared BOM loader — used by Main Dashboard and BRD Assembly page.

Reads individual BOM xlsx files from DATA_DIR.
Each file (e.g. SYS-SP1-1-1310-D-01.xlsx) becomes one system keyed by
its filename.  Support files (Inventory, prices, etc.) are skipped.
"""

import pandas as pd

from config import (
    DATA_DIR,
    SUPPORT_FILES,
)
from utils.bom_parser import load_bom_file


def load_all_boms() -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Load all BOM systems from DATA_DIR.

    Returns (bom_dict, errors) where bom_dict maps filename → DataFrame.
    Each individual *.xlsx file (excluding support files) is one system.
    """
    bom_files: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    if not DATA_DIR.exists():
        return bom_files, errors

    for f in sorted(DATA_DIR.glob("*.xlsx")):
        if f.name in SUPPORT_FILES:
            continue
        try:
            file_bytes = f.read_bytes()
            df, err = load_bom_file(f.name, file_bytes)
            if err:
                errors.append(err)
            elif df is not None and not df.empty:
                bom_files[f.name] = df
        except Exception as exc:
            errors.append(f"Cannot read '{f.name}': {exc}")

    return bom_files, errors
