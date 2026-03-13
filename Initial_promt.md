# BOM & Inventory Dashboard — Project Specification
**Company:** HEQA  
**Goal:** A shared, always-up-to-date web dashboard that calculates procurement needs based on BOM files and current inventory, enabling the team to determine what components need to be ordered for a given production quantity.

---

## 1. Overview

The system reads multiple BOM (Bill of Materials) Excel files and an Inventory Excel file, allows the user to define how many units of each product to manufacture, and outputs a full procurement list showing what is available in stock and what needs to be ordered — including costs.

---

## 2. Input Files

### 2.1 BOM Files (5 files)
Each file represents one product/system.

**Known filenames:**
- `SYSSP111310D01.xlsx`
- `SYSSP111310L01.xlsx`
- `SYSSP111550D01.xlsx`
- `SYSSP111550L01.xlsx`
- `SYSBR3LINK.xlsx`

**Column structure (identical across all BOM files):**

| Column | Description |
|--------|-------------|
| `Level` | Hierarchy level (1 = top system, 2+ = sub-assemblies and parts) |
| `Vendor` | Vendor code (e.g. HEQA) |
| `Vendor Part Number` | **Primary key** — internal HEQA part number |
| `Vendor Part Revision` | Revision |
| `Description` | Part description |
| `Component Category` | Category |
| `Find Number` | Find number |
| `Quantity` | Quantity per assembly |
| `Unit Of Measure` | e.g. EA |
| `Reference Designator` | Reference |
| `Manufacturer` | Manufacturer name |
| `Manufacturer Part Number` | Manufacturer's part number |
| `BOM Notes` | Notes |
| `Amazon Part Number` | Amazon reference |
| `DashRoll` | Additional field |

**BOM rules:**
- Skip `Level = 1` (top-level system row — not a procurable item)
- Include ALL other levels (2, 3, 4, 5, 6...) including HEQA sub-assemblies
- Aggregate by `Vendor Part Number` across all BOM files
- Multiply `Quantity` by the number of systems to produce

---

### 2.2 Inventory File
**Filename pattern:** contains the word `Inventory` (e.g. `Inventory 20260303.xlsx`)

**Column structure:**

| Column | Description |
|--------|-------------|
| `מק"ט חדש מדבר` | **Primary key** — same as `Vendor Part Number` in BOM |
| `תיאור` | Description |
| `MFR P/N for reference` | Manufacturer part number for reference |
| `MFR` | Manufacturer |
| `מחסן` | Warehouse location |
| `איתור ראשי` | Primary location |
| `כמות` | **Stock quantity** |
| `Notes` | Notes |
| `הערות 2 אם יש` | Additional notes |
| `שם יצרן נוסף` | Additional manufacturer name |
| `In Used 22.1.2026` | In-use flag |

---

### 2.3 Price File
**Filename:** price list export from ERP/accounting system

**Column structure:**

| Column | Description |
|--------|-------------|
| `מק"ט` | **Primary key** — same as `Vendor Part Number` |
| `עלות תקן USD` | Standard cost in USD |
| `תאור` | Description |

**Price rules:**
- Price = `0.0` is treated as **no price** (same as missing)
- Items with no price or price = 0 are flagged as ⚠️ missing price

---

### 2.4 Part Type File (P/R/O)
**Purpose:** Classifies each part as purchasable (R), manufactured in-house (P), or other (O)

**Column structure:**

| Column | Description |
|--------|-------------|
| `מק"ט` | **Primary key** |
| `מק"ט יצרן בש. הנדסי` | Engineer BOM manufacturer P/N |
| `תאור מוצר` | Product description |
| `טיפוס P/R/O` | **Type:** R = Purchase, P = Manufacture, O = Other |

**Filter logic:**
- User selects which types to include via checkboxes: R ✅, P ☐, O ☐
- Default: R only (purchase items)
- If file not uploaded → no filtering applied, all parts shown

---

## 3. Core Calculation Logic

```
For each BOM file:
  required_qty[part] += BOM_quantity[part] × number_of_systems

For each unique part:
  to_order = MAX(0, required_qty[part] - inventory[part])
  unit_price = price_file[part]  (if > 0, else NULL)
  total_cost = unit_price × required_qty
  order_cost = unit_price × to_order
```

**Join key:** `Vendor Part Number` (BOM) = `מק"ט חדש מדבר` (Inventory) = `מק"ט` (Price file) = `מק"ט` (Type file)

---

## 4. Dashboard Features

### 4.1 File Upload / Sync
- Upload 4 file types: BOM files (multi-select), Inventory, Prices, Part Types
- For a shared team app: files should be loaded from a shared folder/storage (not per-user upload)
- Auto-refresh when files change

### 4.2 Production Quantity Input
- One numeric input per BOM file (product)
- Label = filename (product name)
- Default = 0

### 4.3 Type Filter (requires Part Type file)
- Checkboxes: **R — רכש** (default ✅), **P — ייצור** (default ☐), **O — אחר** (default ☐)
- Filters which part types appear in results

### 4.4 KPI Cards

**Inventory & Availability:**
| KPI | Description |
|-----|-------------|
| Total unique parts | Count of unique Vendor Part Numbers |
| ✅ In stock | Parts where to_order = 0 |
| 🔴 Missing | Parts where to_order > 0 |
| Availability % | In stock / total × 100 |
| Unique Mfr Part Numbers | Count of unique Manufacturer Part Numbers |
| Unique Manufacturers | Count of unique Manufacturer names |

**Procurement Costs:**
| KPI | Description |
|-----|-------------|
| Total procurement cost | Sum of (unit_price × required_qty) for all parts |
| Order cost (missing only) | Sum of (unit_price × to_order) for missing parts |
| ⚠️ Parts without price | Count of parts with price = 0 or missing |

### 4.5 Results Table

**Columns:**
| Column | Notes |
|--------|-------|
| Vendor Part Number | Bold |
| Description | |
| Manufacturer | |
| Manufacturer Part Number | LTR direction |
| Type | Badge: R (green) / P (yellow) / O (purple) |
| Required Qty | |
| In Stock | |
| To Order | Bold if > 0 |
| Unit Price $ | ⚠️ highlighted if no price |
| Total Cost $ | |
| Order Cost $ | Bold if missing |
| Status | Badge: ✅ In Stock / 🔴 Missing + ⚠️ No Price |
| Product Breakdown | e.g. `SYSBR3LINK×2 | SYSSP111550D01×1` |

**Row colors:**
- 🔴 Red background → missing from stock
- 🟢 Green background → fully in stock
- 🟡 Yellow background → in stock but no price

**Sorting:** All columns sortable (click header)

**Search:** Free text search across VPN, description, manufacturer

### 4.6 Filters
- All
- Missing only
- In stock only
- ⚠️ No price only

### 4.7 Export
- **Export order list (CSV)** — exports current filtered view
- **Export no-price items (CSV)** — always exports all parts with missing/zero price
- CSV filename: `order_list.csv` / `no_price_items.csv`
- UTF-8 BOM encoding for Hebrew support

---

## 5. Tech Stack Recommendation

Since the goal is a **shared team app** (not a local single-user file):

### Option A — Recommended: Python + Streamlit
```
stack:
  - Python 3.10+
  - Streamlit (UI framework)
  - pandas (data processing)
  - openpyxl (Excel reading)

deployment:
  - Streamlit Cloud (free tier)
  - OR Docker container on internal server
  - OR company intranet (streamlit run)

file storage:
  - Shared folder (network drive / mapped path)
  - OR Google Drive / SharePoint sync folder
  - OR upload via Streamlit file_uploader with session state
```

### Option B — Node.js + React
```
stack:
  - React (frontend)
  - Node.js / Express (backend)
  - xlsx / exceljs (Excel parsing)
  - deployment: Vercel / internal server
```

### Option C — Simple (no backend)
```
stack:
  - Pure HTML + JavaScript
  - SheetJS (xlsx) for Excel parsing
  - No server needed — open index.html in browser
  - limitation: each user uploads files manually
```

---

## 6. File & Folder Structure (Streamlit version)

```
bom-dashboard/
├── app.py                  # Main Streamlit app
├── requirements.txt        # pandas, openpyxl, streamlit
├── config.py               # Column name constants
├── utils/
│   ├── bom_parser.py       # BOM file loading & parsing
│   ├── inventory_parser.py # Inventory file loading
│   ├── price_parser.py     # Price file loading
│   ├── type_parser.py      # P/R/O type file loading
│   └── calculator.py       # Core aggregation & comparison logic
├── data/                   # Shared folder with Excel files
│   ├── SYSSP111310D01.xlsx
│   ├── SYSSP111310L01.xlsx
│   ├── SYSSP111550D01.xlsx
│   ├── SYSSP111550L01.xlsx
│   ├── SYSBR3LINK.xlsx
│   ├── Inventory *.xlsx
│   ├── prices.xlsx
│   └── part_types.xlsx
└── README.md
```

---

## 7. Column Name Constants

```python
# BOM columns
BOM_LEVEL       = "Level"
BOM_VPN         = "Vendor Part Number"
BOM_QTY         = "Quantity"
BOM_DESC        = "Description"
BOM_MFR         = "Manufacturer"
BOM_MFR_PN      = "Manufacturer Part Number"

# Inventory columns
INV_PART        = "מק\"ט חדש\nמדבר"   # exact Excel column name (has newline)
INV_QTY         = "כמות"

# Price columns
PRICE_PART      = "מק\"ט"
PRICE_COST      = "עלות תקן USD"

# Type columns
TYPE_PART       = "מק\"ט"
TYPE_TYPE       = "טיפוס P/R/O"
```

> ⚠️ **Note:** The inventory column `מק"ט חדש מדבר` contains a newline character (`\n`) in the Excel header. Handle with `.strip()` or flexible column matching.

---

## 8. Business Rules Summary

1. Skip BOM Level = 1 (top-level system assembly)
2. Include all other levels (sub-assemblies + leaf parts)
3. Aggregate by `Vendor Part Number` across all BOM files
4. Price = 0.0 → treat as "no price" (flag ⚠️)
5. Default type filter = R only (when type file is loaded)
6. to_order = MAX(0, required − in_stock) — never negative
7. Cost calculations only shown when price file is loaded
8. All join keys are `Vendor Part Number` / `מק"ט`

---

## 9. UI Language
- Interface: **Hebrew (RTL)**
- Column headers in results table: **English** (as they appear in BOM files)
- KPI labels, buttons, filters: **Hebrew**
- CSV export: UTF-8 with BOM (`\uFEFF`) for Hebrew compatibility in Excel

---

## 10. Future Enhancements (nice to have)
- [ ] Lead time column per part
- [ ] Supplier contact info
- [ ] Historical order tracking
- [ ] Email alert when stock drops below threshold
- [ ] Multi-warehouse support
- [ ] Integration with ERP system
