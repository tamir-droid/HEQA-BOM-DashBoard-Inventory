import pandas as pd
from config import (
    BOM_VPN_COL,
    BOM_QTY_COL,
    BOM_DESC_COL,
    BOM_MFR_COL,
    BOM_MPN_COL,
    INV_KEY_COL,
    INV_QTY_COL,
    PRICE_KEY_COL,
    PRICE_USD_COL,
    TYPE_KEY_COL,
    TYPE_COL,
)

# Output column names (stable across merges)
COL_REQUIRED = "Required Qty"
COL_IN_STOCK = "In Stock"
COL_TO_ORDER = "To Order"
COL_UNIT_PRICE = "Unit Price $"
COL_TOTAL_COST = "Total Cost $"
COL_ORDER_COST = "Order Cost $"
COL_STATUS = "Status"
COL_BREAKDOWN = "Product Breakdown"


def aggregate_bom(bom_dfs: dict[str, pd.DataFrame], qty_map: dict[str, int]) -> pd.DataFrame:
    """Sum required quantities across all BOMs weighted by production qty.

    For each BOM file with qty > 0:  part_required += bom_qty * production_qty

    If the same VPN appears twice in a BOM file, the second row is treated as
    an alternative manufacturer (MFR Name 2 / MPN 2).

    Returns a DataFrame with one row per unique Vendor Part Number.
    """
    parts = []
    second_mfr_parts = []

    for bom_name, df in bom_dfs.items():
        prod_qty = int(qty_map.get(bom_name, 0))
        if prod_qty <= 0:
            continue

        available_extra = [c for c in [BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL] if c in df.columns]
        keep_cols = [BOM_VPN_COL, BOM_QTY_COL] + available_extra
        temp = df[keep_cols].copy()

        # Drop rows with empty VPN
        temp = temp[
            temp[BOM_VPN_COL].notna()
            & (temp[BOM_VPN_COL] != "")
            & (temp[BOM_VPN_COL].str.lower() != "nan")
        ].reset_index(drop=True)

        # Extract second-occurrence rows as alternative manufacturer data
        if BOM_MFR_COL in temp.columns and BOM_MPN_COL in temp.columns:
            temp["_rank"] = temp.groupby(BOM_VPN_COL).cumcount()
            second = temp[temp["_rank"] == 1][[BOM_VPN_COL, BOM_MFR_COL, BOM_MPN_COL]].copy()
            if not second.empty:
                second_mfr_parts.append(second)
            temp = temp[temp["_rank"] == 0].drop(columns=["_rank"])

        temp[COL_REQUIRED] = temp[BOM_QTY_COL] * prod_qty
        label = bom_name.replace(".xlsx", "")
        temp[COL_BREAKDOWN] = f"{label}×{prod_qty}"
        parts.append(temp)

    if not parts:
        return pd.DataFrame(columns=[BOM_VPN_COL, BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL,
                                      COL_REQUIRED, COL_BREAKDOWN])

    combined = pd.concat(parts, ignore_index=True)

    agg_dict: dict = {
        COL_REQUIRED: "sum",
        COL_BREAKDOWN: lambda x: " | ".join(x.unique()),
    }
    for col in [BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL]:
        if col in combined.columns:
            agg_dict[col] = "first"

    grouped = combined.groupby(BOM_VPN_COL, sort=False).agg(agg_dict).reset_index()

    # Ensure all description/mfr/mpn columns exist
    for col in [BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL]:
        if col not in grouped.columns:
            grouped[col] = ""

    # Merge alternative manufacturer data (second BOM row per VPN)
    if second_mfr_parts:
        second_mfr_df = (
            pd.concat(second_mfr_parts, ignore_index=True)
            .rename(columns={BOM_MFR_COL: "MFR Name 2", BOM_MPN_COL: "MPN 2"})
            .drop_duplicates(subset=BOM_VPN_COL)
        )
        grouped = grouped.merge(second_mfr_df, on=BOM_VPN_COL, how="left")

    return grouped


def calculate_results(
    required_df: pd.DataFrame,
    inventory_df: pd.DataFrame,
    price_df: pd.DataFrame,
    type_df: pd.DataFrame,
) -> pd.DataFrame:
    """Merge all data sources and compute procurement columns."""
    if required_df.empty:
        return pd.DataFrame()

    df = required_df.copy()
    df[COL_REQUIRED] = pd.to_numeric(df[COL_REQUIRED], errors="coerce").fillna(0)

    # ── Inventory ──────────────────────────────────────────────────────────────
    if not inventory_df.empty and INV_KEY_COL in inventory_df.columns:
        inv = (
            inventory_df[[INV_KEY_COL, INV_QTY_COL]]
            .rename(columns={INV_KEY_COL: BOM_VPN_COL, INV_QTY_COL: COL_IN_STOCK})
            .drop_duplicates(subset=BOM_VPN_COL)
        )
        df = df.merge(inv, on=BOM_VPN_COL, how="left")
    else:
        df[COL_IN_STOCK] = 0.0

    df[COL_IN_STOCK] = pd.to_numeric(df[COL_IN_STOCK], errors="coerce").fillna(0)

    # ── Prices ─────────────────────────────────────────────────────────────────
    if not price_df.empty and PRICE_KEY_COL in price_df.columns:
        prices = (
            price_df[[PRICE_KEY_COL, PRICE_USD_COL]]
            .rename(columns={PRICE_KEY_COL: BOM_VPN_COL, PRICE_USD_COL: COL_UNIT_PRICE})
            .drop_duplicates(subset=BOM_VPN_COL)
        )
        df = df.merge(prices, on=BOM_VPN_COL, how="left")
    else:
        df[COL_UNIT_PRICE] = float("nan")

    # ── Types ──────────────────────────────────────────────────────────────────
    if not type_df.empty and TYPE_KEY_COL in type_df.columns:
        types = (
            type_df[[TYPE_KEY_COL, TYPE_COL]]
            .rename(columns={TYPE_KEY_COL: BOM_VPN_COL, TYPE_COL: "Type"})
            .drop_duplicates(subset=BOM_VPN_COL)
        )
        df = df.merge(types, on=BOM_VPN_COL, how="left")
    else:
        df["Type"] = "—"

    df["Type"] = df["Type"].fillna("—")

    # ── Calculations ───────────────────────────────────────────────────────────
    df[COL_TO_ORDER] = (df[COL_REQUIRED] - df[COL_IN_STOCK]).clip(lower=0)

    has_price = df[COL_UNIT_PRICE].notna() & (df[COL_UNIT_PRICE] > 0)
    df[COL_TOTAL_COST] = float("nan")
    df[COL_ORDER_COST] = float("nan")
    df.loc[has_price, COL_TOTAL_COST] = (
        df.loc[has_price, COL_UNIT_PRICE] * df.loc[has_price, COL_REQUIRED]
    )
    df.loc[has_price, COL_ORDER_COST] = (
        df.loc[has_price, COL_UNIT_PRICE] * df.loc[has_price, COL_TO_ORDER]
    )

    # ── Status ─────────────────────────────────────────────────────────────────
    def _status(row: pd.Series) -> str:
        missing = row[COL_TO_ORDER] > 0
        no_price = pd.isna(row[COL_UNIT_PRICE]) or row[COL_UNIT_PRICE] <= 0
        if missing and no_price:
            return "🔴 Missing ⚠️ No Price"
        elif missing:
            return "🔴 Missing"
        elif no_price:
            return "⚠️ No Price"
        else:
            return "✅ In Stock"

    df[COL_STATUS] = df.apply(_status, axis=1)

    # ── Column order ───────────────────────────────────────────────────────────
    ordered_cols = [
        BOM_VPN_COL,
        BOM_DESC_COL,
        BOM_MFR_COL,
        BOM_MPN_COL,
        "MFR Name 2",
        "MPN 2",
        "Type",
        COL_REQUIRED,
        COL_IN_STOCK,
        COL_TO_ORDER,
        COL_UNIT_PRICE,
        COL_TOTAL_COST,
        COL_ORDER_COST,
        COL_STATUS,
        COL_BREAKDOWN,
    ]
    existing = [c for c in ordered_cols if c in df.columns]
    return df[existing].reset_index(drop=True)


def get_kpis(results_df: pd.DataFrame) -> dict:
    """Derive summary KPIs from the results DataFrame."""
    if results_df.empty:
        return {
            "total_parts": 0,
            "in_stock_count": 0,
            "missing_count": 0,
            "availability_pct": 0.0,
            "no_price_count": 0,
            "total_procurement_cost": 0.0,
            "order_cost": 0.0,
        }

    total = len(results_df)
    missing = int((results_df[COL_TO_ORDER] > 0).sum())
    in_stock = total - missing

    has_price = results_df[COL_UNIT_PRICE].notna() & (results_df[COL_UNIT_PRICE] > 0)
    no_price = int((~has_price).sum())

    total_cost = float(results_df.loc[has_price, COL_TOTAL_COST].sum())
    order_cost = float(results_df.loc[has_price, COL_ORDER_COST].sum())

    return {
        "total_parts": total,
        "in_stock_count": in_stock,
        "missing_count": missing,
        "availability_pct": round(in_stock / total * 100, 1) if total > 0 else 0.0,
        "no_price_count": no_price,
        "total_procurement_cost": total_cost,
        "order_cost": order_cost,
    }
