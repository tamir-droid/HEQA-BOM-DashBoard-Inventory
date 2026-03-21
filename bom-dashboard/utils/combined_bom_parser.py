"""Parser for a single combined BOM Excel file.

Supports two formats:
  1. With 'System' column — each row's System value identifies its BOM group.
  2. Without 'System' column (flat concatenation) — Level-1 rows act as system
     headers; the VPN of each Level-1 row becomes the system key, and all
     subsequent Level 2+ rows (until the next Level-1) belong to that system.

Sheet name: DataSheet (same as individual BOM files).
"""

import io

import pandas as pd

from config import (
    BOM_SHEET,
    BOM_LEVEL_COL,
    BOM_VPN_COL,
    BOM_QTY_COL,
    BOM_DESC_COL,
    BOM_MFR_COL,
    BOM_MPN_COL,
)

COMBINED_SYSTEM_COL = "System"


def _is_level1(val) -> bool:
    """Return True if the BOM level value represents Level 1."""
    try:
        return int(float(str(val).strip().lstrip("."))) == 1
    except (ValueError, TypeError):
        return False


def _split_by_level1(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Auto-detect systems from Level-1 rows in a flat concatenated BOM.

    Each Level-1 row starts a new system group keyed by its VPN.
    All Level 2+ rows below it (until the next Level-1) belong to that system.
    Level-1 rows themselves are excluded from the returned DataFrames.
    """
    result: dict[str, pd.DataFrame] = {}
    current_key: str | None = None
    current_rows: list[int] = []

    for idx, row in df.iterrows():
        level_val = row[BOM_LEVEL_COL]
        if _is_level1(level_val):
            # Save previous group
            if current_key and current_rows:
                result[current_key] = df.loc[current_rows].reset_index(drop=True)
            # Start new group
            vpn = str(row[BOM_VPN_COL]).strip()
            current_key = vpn if vpn and vpn.lower() != "nan" else None
            current_rows = []
        else:
            if current_key is not None:
                current_rows.append(idx)

    # Save last group
    if current_key and current_rows:
        result[current_key] = df.loc[current_rows].reset_index(drop=True)

    return result


def load_combined_bom(
    name: str, file_bytes: bytes
) -> tuple[dict[str, pd.DataFrame], str | None]:
    """Load a combined BOM xlsx file.

    Supports both 'System' column format and flat Level-1-delimited format.

    Returns
    -------
    ({system_name: df}, None)   on success
    ({}, error_string)          on failure
    """
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=BOM_SHEET)
    except Exception as exc:
        # Try without specifying a sheet name (use first sheet)
        try:
            df = pd.read_excel(io.BytesIO(file_bytes))
        except Exception:
            return {}, f"Failed to open combined BOM '{name}': {exc}"

    df.columns = df.columns.str.strip()

    # ── Validate required columns ──────────────────────────────────────────────
    if BOM_LEVEL_COL not in df.columns:
        return {}, f"Combined BOM '{name}': missing '{BOM_LEVEL_COL}' column."

    if BOM_VPN_COL not in df.columns:
        return {}, f"Combined BOM '{name}': missing '{BOM_VPN_COL}' column."

    # ── Ensure optional columns exist ─────────────────────────────────────────
    for col in [BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL]:
        if col not in df.columns:
            df[col] = ""

    df[BOM_VPN_COL] = df[BOM_VPN_COL].astype(str).str.strip()
    df[BOM_QTY_COL] = pd.to_numeric(df.get(BOM_QTY_COL), errors="coerce").fillna(0)

    # ── Choose split strategy ─────────────────────────────────────────────────
    if COMBINED_SYSTEM_COL in df.columns:
        # Format 1: explicit System column
        result: dict[str, pd.DataFrame] = {}
        for system_name, group in df.groupby(COMBINED_SYSTEM_COL, sort=False):
            sys_str = str(system_name).strip()
            if not sys_str or sys_str.lower() == "nan":
                continue
            # Strip Level-1 rows per system
            grp = group[
                ~group[BOM_LEVEL_COL].apply(_is_level1)
            ].copy().reset_index(drop=True)
            if grp.empty:
                continue
            result[sys_str] = grp
    else:
        # Format 2: flat concatenation — split by Level-1 rows
        result = _split_by_level1(df)

    if not result:
        return {}, f"Combined BOM '{name}': no valid system groups found."

    return result, None


def is_combined_bom_filename(name: str) -> bool:
    """Return True if the filename indicates a combined (multi-system) BOM file.

    Matches common naming conventions regardless of case or separator style:
      All Boms.xlsx, ALL_BOMS.xlsx, allboms.xlsx, Combined BOM.xlsx, etc.
    """
    from pathlib import Path as _Path
    stem = _Path(name).stem.lower().replace("_", " ").replace("-", " ")
    _KNOWN = {
        "all boms", "allboms", "all bom", "allbom",
        "combined boms", "combined bom", "combinedboms", "combinedbom",
    }
    return stem in _KNOWN


def detect_combined_bom(file_bytes: bytes) -> bool:
    """Return True if the file looks like a combined BOM by content.

    Prefer is_combined_bom_filename() for fast filename-based detection.
    This function is a content-based fallback.
    """
    for sheet in (BOM_SHEET, None):
        try:
            kw = {"sheet_name": sheet} if sheet else {}
            df = pd.read_excel(io.BytesIO(file_bytes), **kw)
            df.columns = df.columns.str.strip()
            if BOM_LEVEL_COL not in df.columns or BOM_VPN_COL not in df.columns:
                continue
            if COMBINED_SYSTEM_COL in df.columns:
                return True
            level1_vpns = (
                df[df[BOM_LEVEL_COL].apply(_is_level1)][BOM_VPN_COL]
                .astype(str).str.strip()
            )
            distinct = level1_vpns[level1_vpns.str.lower() != "nan"].nunique()
            return distinct > 1
        except Exception:
            continue
    return False
