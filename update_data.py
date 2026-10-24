import json
import os
import pandas as pd
import yfinance as yf

# ==========================================
# 1. NAČTENÍ KOMPLETNÍHO PORTFOLIA ZE SOUBORU
# ==========================================
portfolio_file = "portfolio_final.json"

if os.path.exists(portfolio_file):
    with open(portfolio_file, "r", encoding="utf-8") as f:
        existing_data = json.load(f)
    df_existing = pd.DataFrame(existing_data)
    
    if "date" in df_existing.columns and not df_existing.empty:
        # Převedeme sloupec date na řetězce, abychom bezpečně našli nejnovější datum (string porovnání YYYY-MM-DD)
        df_existing["date_str"] = df_existing["date"].astype(str)
        latest_date_str = df_existing["date_str"].max()
        
        # Vezmeme KOMPLETNÍ řádky nejnovějšího dne včetně všech metadat (ticker, ticker_name, counterparty atd.)
        df_portfolio = df_existing[df_existing["date_str"] == latest_date_str].copy()
        
        # Odstraníme dočasný pomocný sloupec
        df_existing = df_existing.drop(columns=["date_str"])
        if "date_str" in df_portfolio.columns:
            df_portfolio = df_portfolio.drop(columns=["date_str"])
    else:
        raise ValueError("Soubor portfolio_final.json neobsahuje sloupec 'date' nebo je prázdný!")
else:
    raise FileNotFoundError("Soubor portfolio_final.json nebyl nalezen!")

# ==========================================
# 2. ČÁST: Stažení cen a výpočet prices_history_final.json
# ==========================================

ticker_to_isin = {
    "P500.DE": "IE00B3YCGJ38",
    "XRS2.DE": "IE00BJZ2DD79",
    "WELE.DE": "IE000LAP5Z18",
    "EWSP.AS": "IE000MLMNYS0",
    "EIMI.L": "IE00BKM4GZ66",
    "WSML.L": "IE00BF4RFH31",
    "IUES.L": "IE00B42NKQ00",
    "MSFT": "US5949181045",
    "EWG.L": "GB00BLGXWY71",
}

tickers = list(ticker_to_isin.keys()) + [
    "EURCZK=X",
    "USDCZK=X",
    "GBPCZK=X",
]

start_date = "2021-10-23"
end_date = pd.Timestamp.today().strftime("%Y-%m-%d")

print(f"Stahuji data od {start_date} do {end_date}...")

data = yf.download(
    tickers, start=start_date, end=end_date, progress=False
)

if isinstance(data.columns, pd.MultiIndex):
    closes = data["Close"]
else:
    closes = data

closes = closes.reset_index()

if "Date" in closes.columns:
    closes["Date"] = pd.to_datetime(closes["Date"]).dt.strftime("%Y-%m-%d")

rename_dict = {
    "EURCZK=X": "EURCZK",
    "USDCZK=X": "USDCZK",
    "GBPCZK=X": "GBP"
}
closes = closes.rename(columns=rename_dict)

if "GBP" in closes.columns:
    closes["GBPp"] = closes["GBP"] / 100.0

closes = closes.rename(columns=ticker_to_isin)

currency_cols = ["EURCZK", "USDCZK", "GBP", "GBPp"]
other_cols = [col for col in closes.columns if col not in currency_cols]
closes = closes[other_cols + currency_cols]

closes.columns.name = None
df_prices = closes.copy()

# --- Rozšíření o value_{isin}, value_fund a share_{isin} ---
df_prices_extended = df_prices.copy()

currency_to_column = {
    "EUR": "EURCZK",
    "USD": "USDCZK",
    "GBPp": "GBPp"
}

value_columns = []

for index, row in df_portfolio.iterrows():
    isin = row["isin"]
    amount = row["amount"]
    currency = row["currency"]
    
    fx_col = currency_to_column.get(currency)
    
    if isin in df_prices_extended.columns and fx_col in df_prices_extended.columns:
        col_name = f"value_{isin}"
        df_prices_extended[col_name] = (
            df_prices_extended[isin] * amount * df_prices_extended[fx_col]
        ).fillna(0).round(0).astype(int)
        value_columns.append(col_name)

remain_assets = 5766672150

df_prices_extended["value_fund"] = (
    df_prices_extended[value_columns].fillna(0).sum(axis=1) + remain_assets
).round(0).astype(int)

for col_name in value_columns:
    isin = col_name.replace("value_", "")
    share_col_name = f"share_{isin}"
    df_prices_extended[share_col_name] = (
        df_prices_extended[col_name] / df_prices_extended["value_fund"]
    ).fillna(0).round(4)

result_df = df_prices_extended.round(2)

if "Date" in result_df.columns:
    result_df["Date"] = result_df["Date"].astype(str)

# Uložení prices_history_final.json
result_df_json = result_df.where(pd.notnull(result_df), None)
prices_file = "prices_history_final.json"
data_dict = result_df_json.to_dict(orient="records")
with open(prices_file, "w", encoding="utf-8") as f:
    json.dump(data_dict, f, ensure_ascii=False, indent=4)

print(f"Ceny úspěšně uloženy do {prices_file}!")


# ==========================================
# 3. ČÁST: Kumulativní aktualizace portfolio_final.json
# ==========================================

assets_total = 11704226000
df_prices_filled = df_prices.ffill()
last_row = df_prices_filled.iloc[-1]
last_date = last_row["Date"]

# Použijeme kopii celého df_portfolio, takže si zachováme veškerá metadata (ticker_name, ticker_id atd.)
df_today = df_portfolio.copy()
df_today["date"] = last_date
df_today["price"] = df_today["isin"].map(last_row)
df_today["fx_rate"] = df_today["currency"].map(currency_to_column).map(last_row)
df_today["value"] = df_today["amount"] * df_today["price"] * df_today["fx_rate"]
df_today["share"] = df_today["value"] / assets_total

df_today = df_today.round(4)

# Odstranění případného duplicitního záznamu pro tento den v historii
if "date" in df_existing.columns:
    df_existing["date_str"] = df_existing["date"].astype(str)
    df_existing = df_existing[df_existing["date_str"] != last_date]
    df_existing = df_existing.drop(columns=["date_str"])

df_combined = pd.concat([df_existing, df_today], ignore_index=True)
df_combined_json = df_combined.where(pd.notnull(df_combined), None)

with open(portfolio_file, "w", encoding="utf-8") as f:
    json.dump(df_combined_json.to_dict(orient="records"), f, ensure_ascii=False, indent=4)

print(f"Portfolio úspěšně aktualizováno – přidán den {last_date} do {portfolio_file}!")
