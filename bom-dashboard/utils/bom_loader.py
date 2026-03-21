"""Shared BOM loader — used by Main Dashboard and BRD Assembly page.

Reads the combined BOM file (All Boms.xlsx) as a flat DataFrame,
then splits it into per-system DataFrames keyed by the Level-1 VPN
(e.g. SYS-SP1-1-1310-D-01, SYS-BR3-LINK, BRD100700, …).

Falls back to loading individual SYS-*.xlsx / BRD-*.xlsx files when no
combined BOM file is present.
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


def _is_level1(val) -> bool:
    try:
        return int(float(str(val).strip().lstrip("."))) == 1
    except (ValueError, TypeError):
        return False


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


def _split_by_level1(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split a flat BOM DataFrame into per-system DataFrames.

    Each Level-1 row starts a new system (keyed by its VPN).
    The Level-1 row itself is excluded from the returned DataFrame.
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

    # Find positions of all Level-1 rows
    level1_pos = [i for i, v in enumerate(df[BOM_LEVEL_COL]) if _is_level1(v)]

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


def load_all_boms() -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Load all BOM systems from DATA_DIR.

    Returns (bom_dict, errors) where bom_dict maps system VPN → DataFrame.

    If a combined BOM file (e.g. All Boms.xlsx) is present it is used and
    individual BOM files are ignored.  Otherwise individual *.xlsx BOM files
    are loaded, each becoming one system keyed by its filename.
    """
    bom_files: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    if not DATA_DIR.exists():
        return bom_files, errors

    all_xlsx = sorted(DATA_DIR.glob("*.xlsx"))
    combined_path: Path | None = next(
        (f for f in all_xlsx
         if f.name not in SUPPORT_FILES and is_combined_bom_filename(f.name)), None
    )

    if combined_path:
        # ── Combined BOM: split by Level-1 rows ───────────────────────────────
        try:
            file_bytes = combined_path.read_bytes()
            df = _read_flat_df(file_bytes)
            if df is None:
                errors.append(
                    f"Cannot find Level+VPN columns in '{combined_path.name}'. "
                    f"Make sure the file has a 'Level' and 'Vendor Part Number' column."
                )
            else:
                result = _split_by_level1(df)
                if result:
                    bom_files.update(result)
                else:
                    sample = df[BOM_LEVEL_COL].head(10).tolist()
                    errors.append(
                        f"'{combined_path.name}': no Level-1 rows detected. "
                        f"Level column sample: {sample}"
                    )
        except Exception as exc:
            errors.append(f"Error reading '{combined_path.name}': {exc}")
    else:
        # ── Individual BOM files ───────────────────────────────────────────────
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
