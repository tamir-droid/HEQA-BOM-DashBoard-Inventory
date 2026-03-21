"""Parser for a single combined BOM Excel file with a 'System' column.

Expected format:
  - Sheet: DataSheet  (same as individual BOM files)
  - Columns: System, Level, Vendor Part Number, Quantity, Description,
             Manufacturer, Manufacturer Part Number, Find Number, ...
  - The 'System' column value (e.g. "SYS-BR3-LINK") identifies which BOM
    each row belongs to.  Rows with the same System are treated exactly like
    a stand-alone SYS-*.xlsx BOM file.
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


def load_combined_bom(
    name: str, file_bytes: bytes
) -> tuple[dict[str, pd.DataFrame], str | None]:
    """Load a combined BOM xlsx file with a 'System' column.

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
    if COMBINED_SYSTEM_COL not in df.columns:
        return (
            {},
            f"Combined BOM '{name}': missing '{COMBINED_SYSTEM_COL}' column. "
            f"Found: {list(df.columns)}",
        )

    if BOM_LEVEL_COL not in df.columns:
        return (
            {},
            f"Combined BOM '{name}': missing '{BOM_LEVEL_COL}' column.",
        )

    if BOM_VPN_COL not in df.columns:
        return (
            {},
            f"Combined BOM '{name}': missing '{BOM_VPN_COL}' column.",
        )

    # ── Ensure optional columns exist ─────────────────────────────────────────
    for col in [BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL]:
        if col not in df.columns:
            df[col] = ""

    df[BOM_VPN_COL] = df[BOM_VPN_COL].astype(str).str.strip()
    df[BOM_QTY_COL] = pd.to_numeric(df.get(BOM_QTY_COL), errors="coerce").fillna(0)

    # ── Split by System ───────────────────────────────────────────────────────
    result: dict[str, pd.DataFrame] = {}
    for system_name, group in df.groupby(COMBINED_SYSTEM_COL, sort=False):
        sys_str = str(system_name).strip()
        if not sys_str or sys_str.lower() == "nan":
            continue

        # Strip Level-1 rows (top assembly header rows) per system
        grp = group[
            group[BOM_LEVEL_COL].astype(str).str.strip() != "1"
        ].copy()
        grp = grp.reset_index(drop=True)

        if grp.empty:
            continue

        # Store under the system name (used as the BOM key everywhere)
        result[sys_str] = grp

    if not result:
        return {}, f"Combined BOM '{name}': no valid system groups found."

    return result, None


def detect_combined_bom(file_bytes: bytes) -> bool:
    """Return True if the file looks like a combined BOM (has a 'System' column)."""
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=BOM_SHEET, nrows=0)
        return COMBINED_SYSTEM_COL in [c.strip() for c in df.columns]
    except Exception:
        try:
            df = pd.read_excel(io.BytesIO(file_bytes), nrows=0)
            return COMBINED_SYSTEM_COL in [c.strip() for c in df.columns]
        except Exception:
            return False
