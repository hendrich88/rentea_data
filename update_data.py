import json
import os
import pandas as pd
import yfinance as yf


def to_ms(value):
    """Převede datum (číslo v ms nebo řetězec) na milisekundy od epochy (půlnoc UTC)."""
    if isinstance(value, (int, float)) and not pd.isna(value):
        return int(value)
    return int(pd.Timestamp(value).value // 10**6)


# ==========================================
# 1. NAČTENÍ PORTFOLIA A ŠABLONY METADAT
# ==========================================
portfolio_file = "portfolio_final.json"

if os.path.exists(portfolio_file):
    with open(portfolio_file, "r", encoding="utf-8") as f:
        existing_data = json.load(f)
    df_existing = pd.DataFrame(existing_data)

    if "date" in df_existing.columns and not df_existing.empty:
        # Sjednocení formátu data na ms (pro případ smíšených typů)
        df_existing["date"] = df_existing["date"].apply(to_ms)

        latest_date = df_existing["date"].max()

        # Vezmeme kompletní řádky posledního dne jako šablonu (názvy, ID, typy atd.)
        df_latest_template = df_existing[df_existing["date"] == latest_date].copy()
    else:
        raise ValueError("Soubor portfolio_final.json neobsahuje sloupec 'date' nebo je prázdný!")
else:
    raise FileNotFoundError("Soubor portfolio_final.json nebyl nalezen!")

# ==========================================
# 2. ČÁST: Stažení cen z Yahoo Finance
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

data = yf.download(tickers, start=start_date, end=end_date, progress=False)

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
    "GBPCZK=X": "GBP",
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

# Uložení prices_history_final.json (výpočet hodnot pro historii cen)
df_prices_extended = df_prices.copy()
currency_to_column = {"EUR": "EURCZK", "USD": "USDCZK", "GBPp": "GBPp"}
value_columns = []

amounts_dict = dict(zip(df_latest_template["isin"], df_latest_template["amount"]))
currencies_dict = dict(zip(df_latest_template["isin"], df_latest_template["currency"]))

for isin, amount in amounts_dict.items():
    curr = currencies_dict.get(isin)
    fx_col = currency_to_column.get(curr)
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
    df_prices_extended[f"share_{isin}"] = (
        df_prices_extended[col_name] / df_prices_extended["value_fund"]
    ).fillna(0).round(4)

result_df = df_prices_extended.round(2)
if "Date" in result_df.columns:
    result_df["Date"] = result_df["Date"].astype(str)

prices_file = "prices_history_final.json"
with open(prices_file, "w", encoding="utf-8") as f:
    json.dump(
        result_df.where(pd.notnull(result_df), None).to_dict(orient="records"),
        f, ensure_ascii=False, indent=4,
    )

print(f"Ceny uloženy do {prices_file}!")


# ==========================================
# 3. ČÁST: Aktualizace portfolio_final.json
# ==========================================
assets_total = 11704226000
df_prices_filled = df_prices.ffill()
last_row = df_prices_filled.iloc[-1]
last_date_str = last_row["Date"]
last_date_ms = to_ms(last_date_str)  # stejný formát jako v portfolio_final.json

# Vezmeme šablonu a aktualizujeme u ní ceny, kurzy a hodnoty pro aktuální den
df_today = df_latest_template.copy()
df_today["date"] = last_date_ms

prices_map = last_row.to_dict()

for idx, row in df_today.iterrows():
    isin = row["isin"]
    curr = row["currency"]
    fx_col = currency_to_column.get(curr)

    price = prices_map.get(isin, row.get("price"))
    fx_rate = prices_map.get(fx_col, row.get("fx_rate"))
    amount = row["amount"]

    df_today.loc[idx, "price"] = price
    df_today.loc[idx, "fx_rate"] = fx_rate
    val = amount * price * fx_rate
    df_today.loc[idx, "value"] = val
    df_today.loc[idx, "share"] = val / assets_total

df_today = df_today.round(4)

# Odstranění duplicitního záznamu pro stejné datum
df_existing = df_existing[df_existing["date"] != last_date_ms]

df_combined = pd.concat([df_existing, df_today], ignore_index=True)

with open(portfolio_file, "w", encoding="utf-8") as f:
    json.dump(
        df_combined.where(pd.notnull(df_combined), None).to_dict(orient="records"),
        f, ensure_ascii=False, indent=4,
    )

print(f"Portfolio úspěšně aktualizováno – přidán den {last_date_str}!")
