import io
import pandas as pd
from config import PRICE_SHEET, PRICE_KEY_COL, PRICE_USD_COL


def load_prices(file_bytes: bytes) -> tuple[pd.DataFrame, str | None]:
    """Load 'item cost.xlsx'. Zero prices are treated as missing (NaN).

    Returns (df, None) on success, (empty_df, error_str) on failure.
    """
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=PRICE_SHEET)
        df.columns = df.columns.str.strip()

        if PRICE_KEY_COL not in df.columns:
            return pd.DataFrame(), (
                f"Price file: column '{PRICE_KEY_COL}' not found. "
                f"Got: {list(df.columns)}"
            )

        df[PRICE_KEY_COL] = df[PRICE_KEY_COL].astype(str).str.strip()
        df[PRICE_USD_COL] = pd.to_numeric(df.get(PRICE_USD_COL), errors="coerce")

        # Zero price → treat as not priced
        df.loc[df[PRICE_USD_COL] == 0, PRICE_USD_COL] = float("nan")

        return df.reset_index(drop=True), None

    except Exception as exc:
        return pd.DataFrame(), f"Failed to load Prices: {exc}"
