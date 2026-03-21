"""Shared BOM loader — used by Main Dashboard and BRD Assembly page.

Supports two modes:
  1. Combined BOM file (e.g. All Boms.xlsx) — flat DataFrame with all
     systems concatenated.  Level-1 rows whose VPN starts with SYS-,
     BRD, or BRA are treated as system headers; all other Level-1 rows
     (accessories, labels, packaging) are treated as normal components.
  2. Individual BOM files — each *.xlsx in DATA_DIR is one system.
"""

import io
from pathlib import Path

import pandas as pd

from config import (
    DATA_DIR,
    BOM_SHEET,
    BOM_LEVEL_COL,
    BOM_VPN_COL,
    BOM_QTY_COL,
    BOM_DESC_COL,
    BOM_MFR_COL,
    BOM_MPN_COL,
    SUPPORT_FILES,
)
from utils.bom_parser import load_bom_file
from utils.combined_bom_parser import is_combined_bom_filename


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_level1(val) -> bool:
    try:
        return int(float(str(val).strip().lstrip("."))) == 1
    except (ValueError, TypeError):
        return False


def _is_system_vpn(vpn: str) -> bool:
    """Return True only for top-level system VPNs (SYS-*, BRD*, BRA*).

    This filters out accessories / labels / packaging that also sit at
    Level 1 inside individual BOM files, so they don't split the flat
    combined DataFrame at the wrong boundary.
    """
    v = str(vpn).strip().upper()
    return v.startswith(("SYS-", "BRD", "BRA"))


def _read_flat_df(file_bytes: bytes) -> pd.DataFrame | None:
    """Read an Excel file into a flat DataFrame, trying all sheets."""
    try:
        xl = pd.ExcelFile(io.BytesIO(file_bytes))
        sheet_names = xl.sheet_names
    except Exception:
        sheet_names = []

    for sheet in ([BOM_SHEET] + sheet_names + [None]):
        try:
            kw = {"sheet_name": sheet} if sheet is not None else {}
            df = pd.read_excel(io.BytesIO(file_bytes), **kw)
            df.columns = df.columns.str.strip()
            if BOM_LEVEL_COL in df.columns and BOM_VPN_COL in df.columns:
                return df
        except Exception:
            continue
    return None


def _split_by_system_level1(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split a flat BOM DataFrame into per-system DataFrames.

    Only Level-1 rows whose VPN starts with SYS-, BRD, or BRA are used
    as system delimiters.  Other Level-1 rows (accessories, etc.) are
    treated as ordinary component rows.
    """
    df = df.reset_index(drop=True)

    # Ensure required columns exist
    for col in [BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL]:
        if col not in df.columns:
            df[col] = ""
    if BOM_QTY_COL in df.columns:
        df[BOM_QTY_COL] = pd.to_numeric(df[BOM_QTY_COL], errors="coerce").fillna(0)
    else:
        df[BOM_QTY_COL] = 0
    df[BOM_VPN_COL] = df[BOM_VPN_COL].astype(str).str.strip()

    # Find positions of system-header Level-1 rows only
    level1_pos = [
        i for i, v in enumerate(df[BOM_LEVEL_COL])
        if _is_level1(v) and _is_system_vpn(df.at[i, BOM_VPN_COL])
    ]

    result: dict[str, pd.DataFrame] = {}
    for idx, pos in enumerate(level1_pos):
        vpn = df.at[pos, BOM_VPN_COL]
        if not vpn or vpn.lower() == "nan":
            continue
        end = level1_pos[idx + 1] if idx + 1 < len(level1_pos) else len(df)
        chunk = df.iloc[pos + 1: end].copy().reset_index(drop=True)
        if not chunk.empty:
            result[vpn] = chunk

    return result


# ── Public API ────────────────────────────────────────────────────────────────

def parse_combined_bom_bytes(
    name: str, file_bytes: bytes
) -> tuple[dict[str, pd.DataFrame], str | None]:
    """Parse a combined BOM from raw bytes (used by upload-page validation).

    Returns ({system_vpn: df}, None) on success, ({}, error_str) on failure.
    Uses SYS-/BRD-/BRA- Level-1 filter so accessory rows don't break splits.
    """
    df = _read_flat_df(file_bytes)
    if df is None:
        return {}, (
            f"Cannot find 'Level' and 'Vendor Part Number' columns in '{name}'. "
            f"Make sure the file uses the DataSheet sheet with the correct column names."
        )
    result = _split_by_system_level1(df)
    if not result:
        sample = df[BOM_LEVEL_COL].head(10).tolist()
        return {}, (
            f"'{name}': no SYS-/BRD-/BRA- Level-1 rows detected. "
            f"Level column sample: {sample}"
        )
    return result, None


def load_all_boms() -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Load all BOM systems from DATA_DIR.

    Returns (bom_dict, errors) where bom_dict maps system key → DataFrame.

    If a combined BOM file (e.g. All Boms.xlsx) is present it is used and
    individual BOM files are ignored.  Otherwise individual *.xlsx BOM files
    are loaded, each becoming one system keyed by its filename.
    """
    bom_files: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    if not DATA_DIR.exists():
        return bom_files, errors

    all_xlsx = sorted(DATA_DIR.glob("*.xlsx"))

    # Find combined BOM (exclude support files to avoid ALL_BOMS.xlsx clash)
    combined_path: Path | None = next(
        (f for f in all_xlsx
         if f.name not in SUPPORT_FILES and is_combined_bom_filename(f.name)), None
    )

    if combined_path:
        # ── Combined BOM ──────────────────────────────────────────────────────
        try:
            file_bytes = combined_path.read_bytes()
            df = _read_flat_df(file_bytes)
            if df is None:
                errors.append(
                    f"Cannot find Level+VPN columns in '{combined_path.name}'. "
                    f"Make sure the file has 'Level' and 'Vendor Part Number' columns."
                )
            else:
                result = _split_by_system_level1(df)
                if result:
                    bom_files.update(result)
                else:
                    errors.append(
                        f"'{combined_path.name}': no SYS-/BRD-/BRA- Level-1 rows detected. "
                        f"Level column sample: {df[BOM_LEVEL_COL].head(10).tolist()}"
                    )
        except Exception as exc:
            errors.append(f"Error reading '{combined_path.name}': {exc}")
    else:
        # ── Individual BOM files ──────────────────────────────────────────────
        for f in all_xlsx:
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
