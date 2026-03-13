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


def load_bom_file(name: str, file_bytes: bytes) -> tuple[pd.DataFrame, str | None]:
    """Load a single BOM xlsx file. Strips level-1 rows (top assembly).

    Returns (df, None) on success, (empty_df, error_str) on failure.
    """
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=BOM_SHEET)
        df.columns = df.columns.str.strip()

        if BOM_LEVEL_COL not in df.columns:
            return pd.DataFrame(), f"BOM '{name}': column '{BOM_LEVEL_COL}' not found. Got: {list(df.columns)}"

        # Level column is mixed type: ints 1-7 plus strings like '.....8'
        # Cast everything to str and strip before comparison
        df = df[df[BOM_LEVEL_COL].astype(str).str.strip() != "1"].copy()

        if BOM_VPN_COL not in df.columns:
            return pd.DataFrame(), f"BOM '{name}': column '{BOM_VPN_COL}' not found."

        df[BOM_VPN_COL] = df[BOM_VPN_COL].astype(str).str.strip()
        df[BOM_QTY_COL] = pd.to_numeric(df.get(BOM_QTY_COL), errors="coerce").fillna(0)

        # Ensure optional columns exist
        for col in [BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL]:
            if col not in df.columns:
                df[col] = ""

        return df.reset_index(drop=True), None

    except Exception as exc:
        return pd.DataFrame(), f"Failed to load BOM '{name}': {exc}"


def load_all_bom_files(data_dir) -> tuple[dict, list[str]]:
    """Scan data_dir for BOM xlsx files (not in SUPPORT_FILES) and load them all."""
    from config import SUPPORT_FILES

    bom_dfs: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    for path in sorted(data_dir.glob("*.xlsx")):
        if path.name in SUPPORT_FILES:
            continue
        try:
            file_bytes = path.read_bytes()
        except Exception as exc:
            errors.append(f"Cannot read '{path.name}': {exc}")
            continue

        df, err = load_bom_file(path.name, file_bytes)
        if err:
            errors.append(err)
        else:
            bom_dfs[path.name] = df

    return bom_dfs, errors
