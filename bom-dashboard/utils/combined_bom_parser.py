"""Parser for a single combined BOM Excel file.

The file contains multiple systems concatenated together.
Level-1 rows act as system headers — the VPN of each Level-1 row
becomes the system key (e.g. SYS-SP1-1-1310-D-01).
All rows below a Level-1 row (until the next Level-1) belong to that system.
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
        s = str(val).strip().lstrip(".")
        return int(float(s)) == 1
    except (ValueError, TypeError):
        return False


def is_combined_bom_filename(name: str) -> bool:
    """Return True if the filename indicates a combined (multi-system) BOM file."""
    from pathlib import Path as _Path
    stem = _Path(name).stem.lower().replace("_", " ").replace("-", " ")
    _KNOWN = {
        "all boms", "allboms", "all bom", "allbom",
        "combined boms", "combined bom", "combinedboms", "combinedbom",
    }
    return stem in _KNOWN


def _read_excel_any_sheet(file_bytes: bytes) -> tuple[pd.DataFrame | None, str | None]:
    """Try to read an Excel file, first with DataSheet, then any sheet that has
    the required BOM columns (Level + Vendor Part Number)."""

    sheets_to_try: list = [BOM_SHEET, None]  # None = first sheet

    # Also discover all actual sheet names
    try:
        xl = pd.ExcelFile(io.BytesIO(file_bytes))
        for sh in xl.sheet_names:
            if sh not in sheets_to_try:
                sheets_to_try.append(sh)
    except Exception:
        pass

    last_err = ""
    for sheet in sheets_to_try:
        try:
            kw = {"sheet_name": sheet} if sheet is not None else {}
            df = pd.read_excel(io.BytesIO(file_bytes), **kw)
            df.columns = df.columns.str.strip()
            if BOM_LEVEL_COL in df.columns and BOM_VPN_COL in df.columns:
                return df, None
            last_err = f"Sheet '{sheet}' columns: {list(df.columns)}"
        except Exception as exc:
            last_err = str(exc)
            continue

    return None, f"Could not find a sheet with '{BOM_LEVEL_COL}' and '{BOM_VPN_COL}' columns. Last error: {last_err}"


def load_combined_bom(
    name: str, file_bytes: bytes
) -> tuple[dict[str, pd.DataFrame], str | None]:
    """Load a combined BOM xlsx file. Splits by Level-1 rows.

    Returns
    -------
    ({system_name: df}, None)   on success
    ({}, error_string)          on failure
    """
    df, err = _read_excel_any_sheet(file_bytes)
    if df is None:
        return {}, f"Cannot read '{name}': {err}"

    # Ensure optional columns exist
    for col in [BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL]:
        if col not in df.columns:
            df[col] = ""

    df[BOM_VPN_COL] = df[BOM_VPN_COL].astype(str).str.strip()
    if BOM_QTY_COL in df.columns:
        df[BOM_QTY_COL] = pd.to_numeric(df[BOM_QTY_COL], errors="coerce").fillna(0)
    else:
        df[BOM_QTY_COL] = 0

    # ── If explicit System column exists, use it ───────────────────────────────
    if COMBINED_SYSTEM_COL in df.columns:
        result: dict[str, pd.DataFrame] = {}
        for sys_name, group in df.groupby(COMBINED_SYSTEM_COL, sort=False):
            s = str(sys_name).strip()
            if not s or s.lower() == "nan":
                continue
            grp = group[~group[BOM_LEVEL_COL].apply(_is_level1)].copy().reset_index(drop=True)
            if not grp.empty:
                result[s] = grp
        if result:
            return result, None

    # ── Split by Level-1 rows ─────────────────────────────────────────────────
    # Reset index so positions are 0..n-1
    df = df.reset_index(drop=True)

    # Find positions of all Level-1 rows
    level1_positions = [i for i, v in enumerate(df[BOM_LEVEL_COL]) if _is_level1(v)]

    if not level1_positions:
        sample = df[BOM_LEVEL_COL].head(10).tolist()
        return {}, (
            f"'{name}': no Level-1 rows detected. "
            f"Level column sample: {sample}. "
            f"Columns found: {list(df.columns)}"
        )

    result = {}
    for i, pos in enumerate(level1_positions):
        vpn = str(df.at[pos, BOM_VPN_COL]).strip()
        if not vpn or vpn.lower() == "nan":
            continue
        # Rows belonging to this system: from pos+1 to next Level-1 row (exclusive)
        end = level1_positions[i + 1] if i + 1 < len(level1_positions) else len(df)
        system_df = df.iloc[pos + 1 : end].copy().reset_index(drop=True)
        if not system_df.empty:
            result[vpn] = system_df

    if not result:
        return {}, (
            f"'{name}': Level-1 rows found at positions {level1_positions} "
            f"but no component rows below them."
        )

    return result, None


def detect_combined_bom(file_bytes: bytes) -> bool:
    """Return True if the file looks like a combined BOM (content-based check)."""
    df, _ = _read_excel_any_sheet(file_bytes)
    if df is None:
        return False
    if COMBINED_SYSTEM_COL in df.columns:
        return True
    level1_vpns = df[df[BOM_LEVEL_COL].apply(_is_level1)][BOM_VPN_COL].astype(str).str.strip()
    return level1_vpns[level1_vpns.str.lower() != "nan"].nunique() > 1
