import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
import math
from datetime import datetime, timedelta

def std_normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def load_and_process_data():
    conn = sqlite3.connect("insider.db")
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(insider_trades)")
        columns = [col[1] for col in cursor.fetchall()]
        has_sector = "sector" in columns
    except:
        has_sector = False

    sector_select = "sector" if has_sector else "'Other' as sector"
    query = f"""
        SELECT filing_date, insider, position, ticker, company, avg_price, buy_date,
               total_shares as shares, total_value, filing_url, {sector_select}
        FROM insider_trades WHERE ticker IS NOT NULL AND ticker != '' 
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["buy_date"] = pd.to_datetime(df["buy_date"])
    df["total_value"] = pd.to_numeric(df["total_value"], errors='coerce')
    df["avg_price"] = pd.to_numeric(df["avg_price"], errors='coerce')
    df["shares"] = pd.to_numeric(df["shares"], errors='coerce')
    df["ticker"] = df["ticker"].str.strip().str.upper()
    
    exclude_words = {"NONE", "N/A", "NA", "NULL", "DIRECTOR", "OFFICER", "PRESIDENT", "CEO", "CFO"}
    df = df[~df["ticker"].isin(exclude_words)]
    df = df[df["ticker"].str.match(r'^[A-Z0-9\.\-]{1,5}$', na=False)]
    df = df[df["total_value"] < 500000000]
    return df

def generate_screener(df):
    one_year_ago = datetime.now() - timedelta(days=365)
    df_recent = df[df["buy_date"] >= one_year_ago]
    if df_recent.empty:
        df_recent = df
        
    summary = df_recent.groupby("ticker").agg({
        "total_value": "sum",
        "avg_price": "mean",
        "insider": lambda x: ", ".join(x.unique()[:2]),
        "company": "first",
        "buy_date": "max",
        "ticker": "count",
        "shares": "sum"
    }).rename(columns={"ticker": "trade_count"}).reset_index()
    
    size_score = np.minimum(100.0, 30.0 + (np.log10(summary["total_value"] + 1) * 10.0))
    summary["Certainty (%)"] = np.minimum(98.5, np.maximum(10.0, size_score))
    return summary.sort_values(by="Certainty (%)", ascending=False)

def fetch_market_data(ticker):
    stock = yf.Ticker(ticker)
    hist = stock.history(period="1y")
    if hist.empty:
        return None, 0.0, 0.0, []
    hist.index = hist.index.tz_localize(None)
    current_price = hist["Close"].iloc[-1]
    log_ret = np.log(hist["Close"] / hist["Close"].shift(1))
    hv = log_ret.iloc[-180:].std() * np.sqrt(252)
    return hist, current_price, hv, stock.options

def compute_technical_indicators(hist_data):
    df = hist_data.copy()
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df["STD20"] = df["Close"].rolling(window=20).std()
    df["BB_Upper"] = df["MA20"] + (df["STD20"] * 2)
    df["BB_Lower"] = df["MA20"] - (df["STD20"] * 2)

    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

    high_9 = df["High"].rolling(window=9).max()
    low_9 = df["Low"].rolling(window=9).min()
    df["Tenkan_Sen"] = (high_9 + low_9) / 2
    high_26 = df["High"].rolling(window=26).max()
    low_26 = df["Low"].rolling(window=26).min()
    df["Kijun_Sen"] = (high_26 + low_26) / 2
    df["Senkou_Span_A"] = ((df["Tenkan_Sen"] + df["Kijun_Sen"]) / 2).shift(26)
    high_52 = df["High"].rolling(window=52).max()
    low_52 = df["Low"].rolling(window=52).min()
    df["Senkou_Span_B"] = ((high_52 + low_52) / 2).shift(26)

    delta_close = df["Close"].diff()
    gain = (delta_close.where(delta_close > 0, 0)).rolling(window=14).mean()
    loss = (-delta_close.where(delta_close < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df["RSI_14"] = 100 - (100 / (1 + rs))

    ema_12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema_26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema_12 - ema_26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df["ATR"] = true_range.rolling(14).mean()
    return df

def fetch_option_chain_by_expiry(ticker, expiry_date, current_price):
    stock = yf.Ticker(ticker)
    try:
        opt_chain = stock.option_chain(expiry_date)
        calls = opt_chain.calls.copy()
        puts = opt_chain.puts.copy()
        
        for df in [calls, puts]:
            for col in ["volume", "openInterest", "impliedVolatility", "lastPrice"]:
                if col not in df.columns:
                    df[col] = 0.0 if col in ["impliedVolatility", "lastPrice"] else 0
                    
        total_call_vol = calls["volume"].sum() if "volume" in calls.columns else 1.0
        total_put_vol = puts["volume"].sum() if "volume" in puts.columns else 1.0
        pcr_volume = total_put_vol / (total_call_vol + 1e-9)
        
        calls["strike_diff"] = (calls["strike"] - current_price).abs()
        atm_call = calls.sort_values(by="strike_diff").iloc[0]
        implied_vol = atm_call["impliedVolatility"]
        
        T = 30 / 365.25
        r = 0.04
        
        call_deltas = []
        for _, row in calls.iterrows():
            strike = row["strike"]
            sigma = row["impliedVolatility"] if row["impliedVolatility"] > 0 else 0.3
            d1 = (np.log(current_price / strike) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
            call_deltas.append(std_normal_cdf(d1))
        calls["Delta"] = call_deltas
        
        put_deltas = []
        for _, row in puts.iterrows():
            strike = row["strike"]
            sigma = row["impliedVolatility"] if row["impliedVolatility"] > 0 else 0.3
            d1 = (np.log(current_price / strike) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
            put_deltas.append(std_normal_cdf(d1) - 1.0)
        puts["Delta"] = put_deltas
        
        return calls, puts, implied_vol, pcr_volume
    except:
        empty_calls = pd.DataFrame(columns=["strike", "lastPrice", "volume", "openInterest", "impliedVolatility", "Delta"])
        empty_puts = pd.DataFrame(columns=["strike", "lastPrice", "volume", "openInterest", "impliedVolatility", "Delta"])
        return empty_calls, empty_puts, 0.3, 1.0

def fetch_catalyst_events(ticker, df_raw_trades):
    events = []
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        if news:
            for item in news:
                title = item.get("title", "")
                pub_time = item.get("providerPublishTime", 0)
                link_url = item.get("link", f"https://finance.yahoo.com/quote/{ticker}")
                if pub_time == 0: continue
                event_date = datetime.fromtimestamp(pub_time).strftime('%Y-%m-%d')
                title_lower = title.lower()
                category = None
                if any(x in title_lower for x in ["fda", "approval", "approve", "clearance"]):
                    category = "💊 FDA承認/申請"
                elif any(x in title_lower for x in ["phase", "clinical", "trial", "results", "cohort", "efficacy"]):
                    category = "🔬 治験結果(Phase)"
                elif any(x in title_lower for x in ["earnings", "q1", "q2", "q3", "q4", "revenue", "eps", "financial"]):
                    category = "📊 決算発表"
                elif any(x in title_lower for x in ["merger", "acquisition", "buyout", "takeover", "partnership", "agreement"]):
                    category = "🤝 M&A/提携"
                elif any(x in title_lower for x in ["offering", "dilution", "fundraising", "debt", "shares", "capital"]):
                    category = "💸 資金調達/希薄化"
                    
                if category:
                    events.append({"date": event_date, "title": title, "category": category, "source_url": link_url})
    except:
        pass

    try:
        df_ticker_trades = df_raw_trades[df_raw_trades["ticker"] == ticker]
        for _, trade in df_ticker_trades.iterrows():
            val = trade["total_value"]
            insider_name = trade["insider"]
            pos = trade["position"]
            t_date = trade["buy_date"].strftime('%Y-%m-%d')
            f_url = trade["filing_url"] if pd.notna(trade["filing_url"]) else f"https://www.sec.gov/edgar/browse/?CIK={ticker}"
            
            if val >= 1000000:
                events.append({"date": t_date, "title": f"超大口インサイダー買い: {insider_name} ({pos}) が ${val:,.0f} を市場から購入", "category": "🐋 超大口インサイダー", "source_url": f_url})
            elif any(x in str(pos).lower() for x in ["ceo", "chief executive officer", "cfo", "chief financial officer"]):
                events.append({"date": t_date, "title": f"経営トップ(CEO/CFO)による買い: {insider_name} が ${val:,.0f} を購入", "category": "👑 経営陣インサイダー", "source_url": f_url})
    except:
        pass
    return pd.DataFrame(events).drop_duplicates(subset=["date", "category"]) if events else pd.DataFrame()
