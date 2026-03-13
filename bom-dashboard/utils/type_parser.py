import io
import pandas as pd
from config import TYPE_SHEET, TYPE_KEY_COL, TYPE_COL


def load_types(file_bytes: bytes) -> tuple[pd.DataFrame, str | None]:
    """Load 'Buy & Make.xlsx'. Provides P/R/O classification per part.

    Returns (df, None) on success, (empty_df, error_str) on failure.
    """
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=TYPE_SHEET)
        df.columns = df.columns.str.strip()

        if TYPE_KEY_COL not in df.columns:
            return pd.DataFrame(), (
                f"Type file: column '{TYPE_KEY_COL}' not found. "
                f"Got: {list(df.columns)}"
            )

        df[TYPE_KEY_COL] = df[TYPE_KEY_COL].astype(str).str.strip()

        if TYPE_COL in df.columns:
            df[TYPE_COL] = df[TYPE_COL].astype(str).str.strip()
        else:
            df[TYPE_COL] = "—"

        return df.reset_index(drop=True), None

    except Exception as exc:
        return pd.DataFrame(), f"Failed to load Types: {exc}"
