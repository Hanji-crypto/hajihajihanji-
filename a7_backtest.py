import sqlite3
import pandas as pd
import yfinance as yf
from datetime import timedelta
import time
import warnings

# 不要な警告を非表示にする
warnings.filterwarnings("ignore")

DB_PATH = "insider.db"

def price_after(hist, base_date, days):
    target = pd.Timestamp(base_date, tz=hist.index.tz) + timedelta(days=days)
    future = hist[hist.index >= target]
    if len(future) > 0:
        return float(future["Close"].iloc[0])
    return None

conn = sqlite3.connect(DB_PATH)
# 🔗 SQLクエリに filing_url を追加しました
trades = pd.read_sql("""
    SELECT ticker, insider, position, buy_date, avg_price, total_shares, total_value, filing_url 
    FROM insider_trades 
    ORDER BY total_value DESC
""", conn)
conn.close()

print("=" * 90)
print(f"インサイダー買い バックテスト ({len(trades)}件)")
print("=" * 90)
header = "銘柄".ljust(6) + "投資額".ljust(12) + "単価".ljust(9) + "1週".ljust(9) + "1月".ljust(9) + "3月".ljust(9) + "現在".ljust(9) + "インサイダー"
print(header)
print("-" * 90)

results = []
for _, t in trades.iterrows():
    ticker = t["ticker"]
    try:
        # シングルスレッドで安全にダウンロード
        hist = yf.download(
            ticker, 
            period="1y", 
            progress=False, 
            threads=False, 
            ignore_tz=False
        )

        if hist is None or hist.empty or len(hist) == 0:
            continue

        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)

        avg = t["avg_price"]
        row = {
            "ticker": ticker, 
            "value": t["total_value"], 
            "insider": t["insider"],
            "position": t["position"],
            "buy_date": t["buy_date"],
            "avg_price": avg,
            "filing_url": t["filing_url"]  # 🔗 CSVに出力するために追加
        }

        cells = []
        for label, days in [("w1", 7), ("m1", 30), ("m3", 90)]:
            p = price_after(hist, t["buy_date"], days)
            if p:
                ret = (p - avg) / avg * 100
                row[label] = ret
                cells.append(("%+.1f%%" % ret))
            else:
                row[label] = None
                cells.append("未到来")

        latest = float(hist["Close"].iloc[-1])
        now_ret = (latest - avg) / avg * 100
        row["now"] = now_ret

        # 画面出力
        line = ticker.ljust(6)
        line += f"${t['total_value']:9,.0f} "
        line += f"${avg:<7.2f}"
        line += cells[0].ljust(9) + cells[1].ljust(9) + cells[2].ljust(9)
        line += f"{now_ret:+.1f}%   " + str(t["insider"])[:12]
        print(line)

        results.append(row)
        time.sleep(0.3)
    except Exception:
        continue

df = pd.DataFrame(results)

# BI分析用にCSV保存（filing_urlが含まれます）
if len(df) > 0:
    df.to_csv("insider_backtest_results.csv", index=False, encoding="utf-8-sig")
    
    print("=" * 90)
    print("集計サマリ")
    print("-" * 90)
    for label, jp in [("w1", "1週後"), ("m1", "1ヶ月後"), ("m3", "3ヶ月後"), ("now", "現在")]:
        valid = df[label].dropna()
        if len(valid):
            win = int((valid > 0).sum())
            msg = "  " + jp.ljust(8)
            msg += " 平均%+.2f%%" % valid.mean()
            msg += " / 勝率%d/%d(%.0f%%)" % (win, len(valid), win / len(valid) * 100)
            msg += " / 最高%+.1f%% 最低%+.1f%%" % (valid.max(), valid.min())
            print(msg)

    print("-" * 90)
    valid_now = df.dropna(subset=["now"])
    if len(valid_now) and valid_now["value"].sum() > 0:
        w_ret = (valid_now["now"] * valid_now["value"]).sum() / valid_now["value"].sum()
        print("  投資額加重リターン(現在): %+.2f%%" % w_ret)

    print("-" * 90)
    print("投資額別の成績比較")
    for threshold, flabel in [(0, "全銘柄"), (50000, "$50k以上"), (100000, "$100k以上")]:
        subset = df[df["value"] >= threshold].dropna(subset=["now"])
        if len(subset):
            win = int((subset["now"] > 0).sum())
            msg = "  " + flabel.ljust(12)
            msg += " %d件" % len(subset)
            msg += " 平均%+.2f%%" % subset["now"].mean()
            msg += " 勝率%d/%d(%.0f%%)" % (win, len(subset), win / len(subset) * 100)
            print(msg)
    print("=" * 90)
    print("💾 BI分析用データを保存しました: insider_backtest_results.csv")
    print("=" * 90)
