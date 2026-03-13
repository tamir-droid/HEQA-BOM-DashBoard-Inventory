import io
import pandas as pd
from config import INV_SHEET, INV_KEY_COL, INV_QTY_COL


def load_inventory(file_bytes: bytes) -> tuple[pd.DataFrame, str | None]:
    """Load Inventory.xlsx.

    The key column header contains a literal newline: 'מק"ט חדש\\nמדבר'.
    We do a fuzzy match as fallback so minor formatting changes don't break loading.

    Returns (df, None) on success, (empty_df, error_str) on failure.
    """
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=INV_SHEET)
        df.columns = df.columns.str.strip()

        key_col = _find_key_col(df.columns.tolist())
        if key_col is None:
            return pd.DataFrame(), (
                f"Inventory: key column not found. "
                f"Expected something containing 'מק\"ט' and 'מדבר'. "
                f"Actual columns: {list(df.columns)}"
            )

        if key_col != INV_KEY_COL:
            df = df.rename(columns={key_col: INV_KEY_COL})

        df[INV_KEY_COL] = df[INV_KEY_COL].astype(str).str.strip()
        df[INV_QTY_COL] = pd.to_numeric(df.get(INV_QTY_COL), errors="coerce").fillna(0)

        return df.reset_index(drop=True), None

    except Exception as exc:
        return pd.DataFrame(), f"Failed to load Inventory: {exc}"


def _find_key_col(columns: list[str]) -> str | None:
    if INV_KEY_COL in columns:
        return INV_KEY_COL
    for col in columns:
        if 'מק"ט' in col and 'מדבר' in col:
            return col
    return None
