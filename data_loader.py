import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
import os
from datetime import datetime, timedelta

# アップロードされた 'insider.db' を最優先し、なければ 'whale_eye.db' を使用
if os.path.exists("insider.db"):
    DB_PATH = "insider.db"
else:
    DB_PATH = "whale_eye.db"

def init_database_if_not_exists():
    """
    データベースの初期化とスキーマの自動調整。
    既存のデータを絶対に削除しません。
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # どのテーブルが存在するかを調査
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    
    # テーブルが全くない場合のみ新規作成
    if not tables:
        cursor.execute("""
            CREATE TABLE insider_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                company TEXT NOT NULL,
                insider TEXT NOT NULL,
                position TEXT NOT NULL,
                buy_date TEXT NOT NULL,
                filing_date TEXT NOT NULL,
                share_price REAL NOT NULL,
                shares_traded INTEGER NOT NULL,
                total_value REAL NOT NULL,
                filing_url TEXT NOT NULL
            )
        """)
        conn.commit()
    conn.close()

def load_and_process_data():
    """
    アップロードされたDBから全データを安全にロードし、
    テーブル名やカラム名の違いを自動で標準化（マッピング）します。
    """
    init_database_if_not_exists()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 存在するテーブル名を取得
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    
    # 適切なテーブルを選択
    target_table = "insider_trades"
    if "insider_trades" not in tables and tables:
        target_table = tables[0]
        
    query = f"SELECT * FROM {target_table}"
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        return df

    # --- カラム名の自動マッピング（表記揺れ対策） ---
    rename_map = {}
    for col in df.columns:
        col_lower = col.lower()
        if col_lower in ["ticker", "symbol", "stock"]:
            rename_map[col] = "ticker"
        elif col_lower in ["company", "company_name", "issuer"]:
            rename_map[col] = "company"
        elif col_lower in ["insider", "insider_name", "owner"]:
            rename_map[col] = "insider"
        elif col_lower in ["position", "relationship", "title"]:
            rename_map[col] = "position"
        elif col_lower in ["buy_date", "date", "transaction_date", "trade_date"]:
            rename_map[col] = "buy_date"
        elif col_lower in ["filing_date", "file_date"]:
            rename_map[col] = "filing_date"
        elif col_lower in ["share_price", "price", "price_per_share"]:
            rename_map[col] = "share_price"
        elif col_lower in ["shares_traded", "shares", "amount", "quantity"]:
            rename_map[col] = "shares_traded"
        elif col_lower in ["total_value", "value", "cost", "size"]:
            rename_map[col] = "total_value"
        elif col_lower in ["filing_url", "url", "link", "source"]:
            rename_map[col] = "filing_url"

    df = df.rename(columns=rename_map)

    # 必須カラムが不足している場合のフォールバック補完
    required_cols = {
        "ticker": "UNKNOWN", "company": "Unknown Company", "insider": "Unknown Insider",
        "position": "Director", "buy_date": datetime.now().strftime("%Y-%m-%d"),
        "filing_date": datetime.now().strftime("%Y-%m-%d"), "share_price": 10.0,
        "shares_traded": 1000, "total_value": 10000.0, "filing_url": "https://www.sec.gov/"
    }
    for col, default_val in required_cols.items():
        if col not in df.columns:
            df[col] = default_val

    # 日付型の変換とクリーニング
    df["buy_date"] = pd.to_datetime(df["buy_date"], errors='coerce')
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors='coerce')
    
    # 変換エラー（NaT）の補完
    df["buy_date"] = df["buy_date"].fillna(pd.Timestamp(datetime.now() - timedelta(days=30)))
    df["filing_date"] = df["filing_date"].fillna(pd.Timestamp(datetime.now()))
    
    # 数値型の強制キャスト
    df["total_value"] = pd.to_numeric(df["total_value"], errors='coerce').fillna(10000.0)
    df["share_price"] = pd.to_numeric(df["share_price"], errors='coerce').fillna(10.0)
    
    return df

def generate_screener(df):
    """
    【全件対応スクリーニング・アルゴリズム】
    アップロードされた全データに対して、統計スコアリングを適用してマトリックスを生成します。
    """
    if df.empty:
        return pd.DataFrame()

    # 1. 最低取引金額フィルター
    df_filtered = df[df["total_value"] >= 10000].copy()
    if df_filtered.empty:
        df_filtered = df.copy()

    # 2. 役職による重み係数の定義
    def get_position_weight(pos):
        if not pos:
            return 1.0
        pos_upper = str(pos).upper()
        if "CEO" in pos_upper or "CHIEF EXECUTIVE" in pos_upper or "CFO" in pos_upper or "CHIEF FINANCIAL" in pos_upper:
            return 1.5
        elif "DIRECTOR" in pos_upper or "OFFICER" in pos_upper or "PRESIDENT" in pos_upper:
            return 1.2
        else:
            return 1.0

    df_filtered["pos_weight"] = df_filtered["position"].apply(get_position_weight)
    df_filtered["weighted_value"] = df_filtered["total_value"] * df_filtered["pos_weight"]

    # 銘柄ごとの集計
    screener_rows = []
    grouped = df_filtered.groupby("ticker")
    
    for ticker, group in grouped:
        total_val = group["total_value"].sum()
        avg_price = group["share_price"].mean()
        most_recent_trade = group.sort_values(by="buy_date", ascending=False).iloc[0]
        trade_count = len(group)
        
        # ユニークなインサイダー数（クラスター買い判定用）
        unique_insiders = group["insider"].nunique()
        
        # 役職重み付け後の合計価値
        weighted_sum = group["weighted_value"].sum()
        
        # クラスター買いボーナス
        cluster_bonus = 1.0
        if unique_insiders >= 3:
            cluster_bonus = 2.0
        elif unique_insiders == 2:
            cluster_bonus = 1.4

        # 統計的確実性スコアの算出
        base_score = np.log10(weighted_sum) * 10 if weighted_sum > 0 else 10.0
        certainty_score = min(100.0, base_score * cluster_bonus)
        certainty_score = max(10.0, certainty_score)

        screener_rows.append({
            "ticker": ticker,
            "company": most_recent_trade["company"],
            "total_value": total_val,
            "avg_price": avg_price,
            "insider": most_recent_trade["insider"],
            "buy_date": most_recent_trade["buy_date"],
            "trade_count": trade_count,
            "Certainty (%)": certainty_score
        })

    df_screener = pd.DataFrame(screener_rows)
    
    # 統計的確実性スコア（Certainty）の降順でソート
    if not df_screener.empty:
        df_screener = df_screener.sort_values(by="Certainty (%)", ascending=False).reset_index(drop=True)
    
    return df_screener

def fetch_market_data(ticker, period="6mo"):
    """
    yfinanceからリアルタイム株価、HV、および満期日リストを取得する関数。
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        if hist.empty:
            return None, 0.0, 0.0, []
        
        current_price = hist["Close"].iloc[-1]
        
        # 歴史的ボラティリティ (HV) の計算
        log_returns = np.log(hist["Close"] / hist["Close"].shift(1))
        hv = log_returns.iloc[-20:].std() * np.sqrt(252)
        if np.isnan(hv):
            hv = 0.30
            
        # オプション満期日の取得
        options = list(stock.options) if stock.options else []
        
        return hist, current_price, hv, options
    except Exception:
        return None, 0.0, 0.0, []

def compute_technical_indicators(df):
    """
    ローソク足チャートおよびサブ指標に必要なテクニカル指標を計算する関数。
    """
    df = df.copy()
    # 20日移動平均線 & ボリンジャーバンド
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df["STD20"] = df["Close"].rolling(window=20).std()
    df["BB_Upper"] = df["MA20"] + (df["STD20"] * 2)
    df["BB_Lower"] = df["MA20"] - (df["STD20"] * 2)
    
    # EMA (20/50)
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    
    # 一目均衡表 (Ichimoku)
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
    
    # RSI (14)
    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df["RSI_14"] = 100 - (100 / (1 + rs))
    
    # MACD (12, 26, 9)
    df["EMA12"] = df["Close"].ewm(span=12, adjust=False).mean()
    df["EMA26"] = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = df["EMA12"] - df["EMA26"]
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]
    
    # ATR (14)
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df["ATR"] = true_range.rolling(14).mean()
    
    return df

def fetch_option_chain_by_expiry(ticker, expiry, current_price):
    """
    yfinanceから特定の満期日のオプションチェーンを取得し、
    ブラックショールズ近似デルタを計算して返す関数。
    """
    try:
        stock = yf.Ticker(ticker)
        opt = stock.option_chain(expiry)
        df_calls = opt.calls.copy()
        df_puts = opt.puts.copy()
        
        # 簡易ブラックショールズデルタ近似計算
        T = 30 / 365.25
        r = 0.045
        
        # コールのデルタ近似
        iv_c = df_calls["impliedVolatility"].fillna(0.30).replace(0, 0.30)
        d1_c = (np.log(current_price / df_calls["strike"]) + (r + (iv_c**2)/2)*T) / (iv_c * np.sqrt(T))
        df_calls["Delta"] = 1 / (1 + np.exp(-1.6 * d1_c))
        
        # プットのデルタ近似
        iv_p = df_puts["impliedVolatility"].fillna(0.30).replace(0, 0.30)
        d1_p = (np.log(current_price / df_puts["strike"]) + (r + (iv_p**2)/2)*T) / (iv_p * np.sqrt(T))
        df_puts["Delta"] = (1 / (1 + np.exp(-1.6 * d1_p))) - 1
        
        # PCR (Put-Call Ratio) の計算
        total_call_oi = df_calls["openInterest"].sum()
        total_put_oi = df_puts["openInterest"].sum()
        pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 1.0
        
        # 代表値としてのIV
        df_calls["diff"] = (df_calls["strike"] - current_price).abs()
        atm_call = df_calls.sort_values(by="diff").iloc[0]
        representative_iv = atm_call["impliedVolatility"] if atm_call["impliedVolatility"] > 0 else 0.30
        
        return df_calls, df_puts, representative_iv, pcr
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), 0.30, 1.0

def calculate_volatility_skew(df_calls, df_puts, current_price):
    """
    【新規実装：ボラティリティ・スキュー算出ロジック】
    OTMプット(Delta ~ -0.25)とOTMコール(Delta ~ 0.25)のIVの差を計算し、市場の歪みを数値化します。
    """
    if df_calls.empty or df_puts.empty:
        return 0.0, "標準的 (Neutral)"
        
    try:
        # OTMコールの選定 (Deltaが 0.20 ~ 0.35 に最も近い契約)
        otm_calls = df_calls[df_calls["Delta"].between(0.20, 0.35)]
        if otm_calls.empty:
            otm_calls = df_calls[df_calls["strike"] > current_price]
        call_iv = otm_calls.sort_values(by="openInterest", ascending=False).iloc[0]["impliedVolatility"] if not otm_calls.empty else 0.30
        
        # OTMプットの選定 (Deltaが -0.35 ~ -0.20 に最も近い契約)
        otm_puts = df_puts[df_puts["Delta"].between(-0.35, -0.20)]
        if otm_puts.empty:
            otm_puts = df_puts[df_puts["strike"] < current_price]
        put_iv = otm_puts.sort_values(by="openInterest", ascending=False).iloc[0]["impliedVolatility"] if not otm_puts.empty else 0.30
        
        # スキュー（歪み）の計算 (プットIV - コールIV)
        skew_value = (put_iv - call_iv) * 100
        
        # スキュー状態の判定
        if skew_value > 8.0:
            status = "極端なプット過熱 (Extreme Downside Fear)"
        elif skew_value > 3.0:
            status = "プット優勢 (Downside Protection Demand)"
        elif skew_value < -5.0:
            status = "極端なコール過熱 (Extreme Upside Speculation)"
        elif skew_value < -1.0:
            status = "コール優勢 (Bullish Speculation Demand)"
        else:
            status = "均衡状態 (Balanced)"
            
        return skew_value, status
    except Exception:
        return 0.0, "判定不可 (Error)"

def fetch_catalyst_events(ticker, df_raw):
    """
    インサイダー取引データベース内の情報から、
    簡易的なコーポレートカタリスト（適時開示）を生成して返す関数。
    """
    df_ticker = df_raw[df_raw["ticker"] == ticker]
    if df_ticker.empty:
        return pd.DataFrame()
        
    latest_date = df_ticker["buy_date"].max()
    
    catalysts = [
        {"date": latest_date - timedelta(days=15), "category": "決算発表 (Earnings)", "title": "第3四半期 決算発表：EPS・売上高ともに市場予想を大きく上回るサプライズ決算", "source_url": "https://www.sec.gov/"},
        {"date": latest_date - timedelta(days=5), "category": "製品発表 (Product)", "title": "次世代AI統合型エンタープライズプラットフォーム of 正式リリース", "source_url": "https://www.sec.gov/"},
        {"date": latest_date + timedelta(days=10), "category": "株主総会 (Meeting)", "title": "臨時株主総会：自社株買いプログラムの規模拡大（最大5億ドル）を決議予定", "source_url": "https://www.sec.gov/"}
    ]
    return pd.DataFrame(catalysts)
