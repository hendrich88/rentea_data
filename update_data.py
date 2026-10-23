import json
import os
import pandas as pd
import yfinance as yf

# ==========================================
# 1. ČÁST: Stažení cen a aktualizace prices_history.json
# ==========================================

# Slovník pro mapování tickerů na ISINy
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
result_df = closes.round(2)

df_prices = result_df.copy()

# Uložení prices_history.json (historie cen)
result_df_json = result_df.where(pd.notnull(result_df), None)
prices_file = "prices_history.json"
data_dict = result_df_json.to_dict(orient="records")
with open(prices_file, "w", encoding="utf-8") as f:
    json.dump(data_dict, f, ensure_ascii=False, indent=4)

print(f"Ceny úspěšně uloženy do {prices_file}!")


# ==========================================
# 2. ČÁST: Kumulativní aktualizace portfolio_final.json
# ==========================================

# Celková hodnota aktiv pro výpočet podílu
assets_total = 11704226000

# 1. Doplnění chybějících hodnot (NaN) z předchozích dní
df_prices_filled = df_prices.ffill()

# 2. Získání posledního řádku (dnešní/nejnovější data)
last_row = df_prices_filled.iloc[-1]
last_date = last_row["Date"]

# 3. Načtení struktury portfolia ze stávajícího portfolio_final.json
portfolio_file = "portfolio_final.json"

if os.path.exists(portfolio_file):
    with open(portfolio_file, "r", encoding="utf-8") as f:
        existing_data = json.load(f)
    df_existing = pd.DataFrame(existing_data)
    
    # Najdeme nejnovější datum, které už v portfoliu je, abychom z něj vzali aktuální množství (amount) a měny (currency)
    if "date" in df_existing.columns and not df_existing.empty:
        latest_existing_date = df_existing["date"].max()
        df_portfolio = df_existing[df_existing["date"] == latest_existing_date][["isin", "amount", "currency"]].copy()
    else:
        raise ValueError("Soubor portfolio_final.json neobsahuje sloupec 'date' nebo je prázdný!")
else:
    raise FileNotFoundError("Soubor portfolio_final.json nebyl nalezen! Musí existovat, aby skript věděl, jaká aktiva v portfoliu má.")

# 4. Příprava dat pro dnešní den
df_today = df_portfolio.copy()
df_today["date"] = last_date
df_today["price"] = df_today["isin"].map(last_row)

currency_to_column = {
    "EUR": "EURCZK",
    "USD": "USDCZK",
    "GBPp": "GBPp"
}

df_today["fx_rate"] = df_today["currency"].map(currency_to_column).map(last_row)
df_today["value"] = df_today["amount"] * df_today["price"] * df_today["fx_rate"]
df_today["share"] = df_today["value"] / assets_total

df_today = df_today.round(4)

# 5. Spojení se stávající historií portfolia (vyčištění duplicit pro dnešek, pokud by se skript pustil víckrát)
if "date" in df_existing.columns:
    df_existing = df_existing[df_existing["date"] != last_date]

df_combined = pd.concat([df_existing, df_today], ignore_index=True)

# Ošetření NaN na null pro JSON
df_combined_json = df_combined.where(pd.notnull(df_combined), None)

# Uložení kompletní historie zpět do portfolio_final.json
portfolio_dict = df_combined_json.to_dict(orient="records")
with open(portfolio_file, "w", encoding="utf-8") as f:
    json.dump(portfolio_dict, f, ensure_ascii=False, indent=4)

print(f"Portfolio úspěšně aktualizováno – přidán den {last_date} do {portfolio_file}!")
