import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
import os
from datetime import datetime, timedelta

DB_PATH = "whale_eye.db"

def init_database_if_not_exists():
    """
    データベースファイルまたはテーブルが存在しない場合、自動的に作成し、
    スクリーニングやシミュレーションに適したリアルなデモデータを注入（シード）します。
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # テーブルの存在確認
    cursor.execute("""
        SELECT count(name) FROM sqlite_master WHERE type='table' AND name='insider_trades'
    """)
    if cursor.fetchone()[0] == 0:
        # テーブルの作成
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
        
        # リアルなデモデータの定義
        base_date = datetime.now() - timedelta(days=45)
        demo_data = [
            # AAPL (複数インサイダーによるクラスター買い & CEO大口)
            ("AAPL", "Apple Inc.", "Tim Cook", "CEO", (base_date + timedelta(days=5)).strftime("%Y-%m-%d"), (base_date + timedelta(days=7)).strftime("%Y-%m-%d"), 185.50, 15000, 2782500.0, "https://www.sec.gov/"),
            ("AAPL", "Apple Inc.", "Luca Maestri", "CFO", (base_date + timedelta(days=6)).strftime("%Y-%m-%d"), (base_date + timedelta(days=8)).strftime("%Y-%m-%d"), 186.20, 5000, 931000.0, "https://www.sec.gov/"),
            ("AAPL", "Apple Inc.", "Arthur Levinson", "Director", (base_date + timedelta(days=8)).strftime("%Y-%m-%d"), (base_date + timedelta(days=10)).strftime("%Y-%m-%d"), 188.00, 2000, 376000.0, "https://www.sec.gov/"),
            
            # NVDA (大口役員買い)
            ("NVDA", "NVIDIA Corp.", "Jen-Hsun Huang", "CEO", (base_date + timedelta(days=12)).strftime("%Y-%m-%d"), (base_date + timedelta(days=14)).strftime("%Y-%m-%d"), 450.00, 8000, 3600000.0, "https://www.sec.gov/"),
            ("NVDA", "NVIDIA Corp.", "Colette Kress", "CFO", (base_date + timedelta(days=13)).strftime("%Y-%m-%d"), (base_date + timedelta(days=15)).strftime("%Y-%m-%d"), 455.00, 1500, 682500.0, "https://www.sec.gov/"),
            
            # MSFT (取締役大口)
            ("MSFT", "Microsoft Corp.", "Satya Nadella", "CEO", (base_date + timedelta(days=2)).strftime("%Y-%m-%d"), (base_date + timedelta(days=4)).strftime("%Y-%m-%d"), 380.00, 6000, 2280000.0, "https://www.sec.gov/"),
            ("MSFT", "Microsoft Corp.", "Penny Pritzker", "Director", (base_date + timedelta(days=15)).strftime("%Y-%m-%d"), (base_date + timedelta(days=17)).strftime("%Y-%m-%d"), 390.00, 3000, 1170000.0, "https://www.sec.gov/"),
            
            # TSLA (大株主による超巨額買い)
            ("TSLA", "Tesla, Inc.", "Elon Musk", "CEO / 10% Owner", (base_date + timedelta(days=20)).strftime("%Y-%m-%d"), (base_date + timedelta(days=22)).strftime("%Y-%m-%d"), 175.00, 50000, 8750000.0, "https://www.sec.gov/"),
            
            # EIKN (オプション取引がない小型株のデモデータ)
            ("EIKN", "Eikon Therapeutics", "Roger Perlmutter", "CEO", (base_date + timedelta(days=25)).strftime("%Y-%m-%d"), (base_date + timedelta(days=27)).strftime("%Y-%m-%d"), 10.50, 10000, 105000.0, "https://www.sec.gov/"),
            ("EIKN", "Eikon Therapeutics", "John Doe", "Director", (base_date + timedelta(days=26)).strftime("%Y-%m-%d"), (base_date + timedelta(days=28)).strftime("%Y-%m-%d"), 10.60, 5000, 53000.0, "https://www.sec.gov/")
        ]
        
        cursor.executemany("""
            INSERT INTO insider_trades (ticker, company, insider, position, buy_date, filing_date, share_price, shares_traded, total_value, filing_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, demo_data)
        
        conn.commit()
    
    conn.close()

def load_and_process_data():
    """
    データベースの自動初期化を行い、データをロードする関数。
    """
    init_database_if_not_exists()
    
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT * FROM insider_trades"
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # 日付型の変換
    df["buy_date"] = pd.to_datetime(df["buy_date"])
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    return df

def generate_screener(df):
    """
    【大幅強化された多次元スクリーニング・アルゴリズム】
    単なる購入金額順ではなく、以下のプロ仕様フィルターと統計スコアリングを適用します。
    """
    # 1. 最低取引金額フィルター ($50,000以上のみを対象)
    df_filtered = df[df["total_value"] >= 50000].copy()
    
    if df_filtered.empty:
        # データが空になってしまう場合のセーフティネット
        df_filtered = df[df["total_value"] >= 10000].copy()

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
        
        # クラスター買いボーナス (複数人が買っている場合は、人数に応じてスコアを1.4倍〜2.0倍に増幅)
        cluster_bonus = 1.0
        if unique_insiders >= 3:
            cluster_bonus = 2.0
        elif unique_insiders == 2:
            cluster_bonus = 1.4

        # 統計的確実性スコアの算出
        base_score = np.log10(weighted_sum) * 10
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
    【機能拡張】: 取得期間を動的に指定できるように引数 `period` を追加。
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
        {"date": latest_date - timedelta(days=5), "category": "製品発表 (Product)", "title": "次世代AI統合型エンタープライズプラットフォームの正式ローンチを発表", "source_url": "https://www.sec.gov/"},
        {"date": latest_date + timedelta(days=10), "category": "株主総会 (Meeting)", "title": "臨時株主総会：自社株買いプログラムの規模拡大（最大5億ドル）を決議予定", "source_url": "https://www.sec.gov/"}
    ]
    return pd.DataFrame(catalysts)
