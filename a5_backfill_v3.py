from edgar import set_identity, get_filings
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import time
import sys # 💡 追加：実行時の引数を判定するため

# SECへのアイデンティティ設定
set_identity("OptionScreener eae270@gmail.com")
DB_PATH = "insider.db"

# フィルター基準：1つの開示書面における「最低総投資額」 ($100,000 = 10万ドル)
MIN_FILING_VALUE_LIMIT = 100000.0

# 💡 実行モードの判定 (--daily 引数があるか確認)
is_daily_mode = "--daily" in sys.argv

# データベースの初期化と既存キーのキャッシュ
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# テーブルが存在しない場合の初期化（念のため）
cur.execute("""
    CREATE TABLE IF NOT EXISTS insider_trades (
        filing_date TEXT,
        insider TEXT,
        position TEXT,
        ticker TEXT,
        company TEXT,
        cik TEXT,
        avg_price REAL,
        buy_date TEXT,
        total_shares REAL,
        total_value REAL,
        filing_url TEXT UNIQUE
    )
""")
conn.commit()

print("🗄️ 既存のデータをメモリにキャッシュ中...")
cur.execute("SELECT DISTINCT filing_url FROM insider_trades WHERE filing_url IS NOT NULL")
existing_urls = set(row[0] for row in cur.fetchall())
print(f"   -> 取得済みURL数: {len(existing_urls)} 件")

today = datetime.now()
saved_total = 0

print("=" * 80)
if is_daily_mode:
    print(f"🚀 【デイリー差分モード】直近2日間の新規データをスキャン中... (基準: ${MIN_FILING_VALUE_LIMIT:,.0f} 以上)")
    # デイリーモード時は過去2日間を1つの期間としてスキャン
    scan_periods = [( (today - timedelta(days=2)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d") )]
else:
    print(f"🚀 【大口フィルター版】過去6ヶ月のインサイダーデータをスキャン中... (基準: ${MIN_FILING_VALUE_LIMIT:,.0f} 以上)")
    # 通常時は6ヶ月分を30日刻みでスキャン
    scan_periods = []
    for i in range(6):
        start_dt = (today - timedelta(days=(i + 1) * 30)).strftime("%Y-%m-%d")
        end_dt = (today - timedelta(days=i * 30)).strftime("%Y-%m-%d")
        scan_periods.append((start_dt, end_dt))
print("=" * 80)

for start_dt, end_dt in scan_periods:
    print(f"\n📅 期間スキャン中: {start_dt} 〜 {end_dt} ...")
    
    try:
        filings = get_filings(form="4", filing_date=f"{start_dt}:{end_dt}")
        filing_list = list(filings)
        total_filings = len(filing_list)
        print(f"  -> この期間のForm 4開示件数: {total_filings} 件")
        
        if total_filings == 0:
            continue
            
        bulk_data = []
        saved_segment = 0
        skipped_by_limit = 0  # フィルターでスキップした件数
        
        start_time = time.time()
        
        for idx, f in enumerate(filing_list, 1):
            
            if idx % 100 == 0 or idx == total_filings:
                elapsed = time.time() - start_time
                speed = idx / elapsed if elapsed > 0 else 0
                remaining_items = total_filings - idx
                eta_seconds = remaining_items / speed if speed > 0 else 0
                eta_time = datetime.now() + timedelta(seconds=eta_seconds)
                
                eta_str = f"{int(eta_seconds // 60)}分{int(eta_seconds % 60)}秒" if eta_seconds > 0 else "計算中"
                eta_clock = eta_time.strftime("%H:%M:%S") if eta_seconds > 0 else "計算中"
                progress_pct = (idx / total_filings) * 100
                
                print(
                    f"▓ {progress_pct:5.1f}% | "
                    f"Processed: {idx}/{total_filings} | "
                    f"Speed: {speed:4.1f} d/s | "
                    f"Skipped(Small): {skipped_by_limit} | "
                    f"ETA: {eta_str} ({eta_clock}) | "
                    f"Saved: {saved_total}"
                )

            # --- 高速フィルター1: 既存URLの即時スキップ ---
            filing_url = f.url if hasattr(f, 'url') else None
            if filing_url in existing_urls:
                continue

            # --- 高速フィルター2: XML構造を持たないドキュメントの即時スキップ ---
            if not hasattr(f, 'xml') or f.xml is None:
                continue
            
            try:
                # 1. まずは軽量パース（ヘッダーと大枠のオブジェクト取得）
                obj = f.obj()
                if obj is None or not hasattr(obj, "common_stock_purchases") or obj.common_stock_purchases is None or obj.common_stock_purchases.empty:
                    continue
                
                purchases = obj.common_stock_purchases
                
                # 2. 【最重要】明細をループ処理する前に、この書類の総取引額を高速に計算
                total_filing_value = 0.0
                for _, row_data in purchases.iterrows():
                    shares = float(row_data.get("Shares", 0) or 0)
                    price = float(row_data.get("Price", 0) or 0)
                    total_filing_value += (shares * price)
                
                # 3. 基準額（$100k）未満であれば、明細のDB格納処理を一切行わずに即スキップ
                if total_filing_value < MIN_FILING_VALUE_LIMIT:
                    skipped_by_limit += 1
                    continue
                
                # --- 基準をクリアした大口取引のみ詳細を保存 ---
                ticker = obj.issuer.ticker
                insider = obj.insider_name
                position = obj.position
                company = obj.issuer.name
                cik = obj.issuer.cik
                
                if not filing_url:
                    filing_url = f"https://www.sec.gov/edgar/browse/?CIK={cik}"

                for _, row_data in purchases.iterrows():
                    buy_date = str(row_data.get("Date", ""))[:10]
                    shares = float(row_data.get("Shares", 0) or 0)
                    price = float(row_data.get("Price", 0) or 0)
                    value = shares * price
                    
                    if value < 100:  # 極端なノイズデータ除外
                        continue
                    
                    bulk_data.append((
                        str(f.filing_date), insider, position, ticker, company, cik,
                        price, buy_date, shares, value, filing_url
                    ))
                    saved_segment += 1
                    saved_total += 1
                
                existing_urls.add(filing_url)

                if len(bulk_data) >= 100:
                    cur.executemany("""
                        INSERT OR IGNORE INTO insider_trades (
                            filing_date, insider, position, ticker, company, cik, 
                            avg_price, buy_date, total_shares, total_value, filing_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, bulk_data)
                    conn.commit()
                    bulk_data = []
                
            except Exception:
                continue
        
        if bulk_data:
            cur.executemany("""
                INSERT OR IGNORE INTO insider_trades (
                    filing_date, insider, position, ticker, company, cik, 
                    avg_price, buy_date, total_shares, total_value, filing_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, bulk_data)
            conn.commit()
            
        print(f"  🎉 期間完了: データベースに {saved_segment} 件をコミット！ (小口スキップ: {skipped_by_limit} 件)")
        time.sleep(0.5)
        
    except Exception as e:
        print(f"  ❌ 期間エラー: {e}")
        continue

conn.close()
print("=" * 80)
if is_daily_mode:
    print(f"📊 デイリー更新完了！ 新規の大口取引データを合計 {saved_total} 件追加しました。")
else:
    print(f"📊 バックフィル完了！ 有意な大口取引データを合計 {saved_total} 件格納しました。")
print("=" * 80)
    try:
        filings = get_filings(form="4", filing_date=f"{start_dt}:{end_dt}")
        filing_list = list(filings)
        total_filings = len(filing_list)
        print(f"  -> この期間のForm 4開示件数: {total_filings} 件")
        
        if total_filings == 0:
            continue
            
        bulk_data = []
        saved_segment = 0
        skipped_by_limit = 0  # フィルターでスキップした件数
        
        start_time = time.time()
        
        for idx, f in enumerate(filing_list, 1):
            
            if idx % 100 == 0 or idx == total_filings:
                elapsed = time.time() - start_time
                speed = idx / elapsed if elapsed > 0 else 0
                remaining_items = total_filings - idx
                eta_seconds = remaining_items / speed if speed > 0 else 0
                eta_time = datetime.now() + timedelta(seconds=eta_seconds)
                
                eta_str = f"{int(eta_seconds // 60)}分{int(eta_seconds % 60)}秒" if eta_seconds > 0 else "計算中"
                eta_clock = eta_time.strftime("%H:%M:%S") if eta_seconds > 0 else "計算中"
                progress_pct = (idx / total_filings) * 100
                
                print(
                    f"▓ {progress_pct:5.1f}% | "
                    f"Processed: {idx}/{total_filings} | "
                    f"Speed: {speed:4.1f} d/s | "
                    f"Skipped(Small): {skipped_by_limit} | "
                    f"ETA: {eta_str} ({eta_clock}) | "
                    f"Saved: {saved_total}"
                )

            # --- 高速フィルター1: 既存URLの即時スキップ ---
            filing_url = f.url if hasattr(f, 'url') else None
            if filing_url in existing_urls:
                continue

            # --- 高速フィルター2: XML構造を持たないドキュメントの即時スキップ ---
            if not hasattr(f, 'xml') or f.xml is None:
                continue
            
            try:
                # 1. まずは軽量パース（ヘッダーと大枠のオブジェクト取得）
                obj = f.obj()
                if obj is None or not hasattr(obj, "common_stock_purchases") or obj.common_stock_purchases is None or obj.common_stock_purchases.empty:
                    continue
                
                purchases = obj.common_stock_purchases
                
                # 2. 【最重要】明細をループ処理する前に、この書類の総取引額を高速に計算
                # 各行の (Shares * Price) の合計を算出
                total_filing_value = 0.0
                for _, row_data in purchases.iterrows():
                    shares = float(row_data.get("Shares", 0) or 0)
                    price = float(row_data.get("Price", 0) or 0)
                    total_filing_value += (shares * price)
                
                # 3. 基準額（$100k）未満であれば、明細のDB格納処理を一切行わずに即スキップ
                if total_filing_value < MIN_FILING_VALUE_LIMIT:
                    skipped_by_limit += 1
                    continue
                
                # --- 基準をクリアした大口取引のみ詳細を保存 ---
                ticker = obj.issuer.ticker
                insider = obj.insider_name
                position = obj.position
                company = obj.issuer.name
                cik = obj.issuer.cik
                
                if not filing_url:
                    filing_url = f"https://www.sec.gov/edgar/browse/?CIK={cik}"

                for _, row_data in purchases.iterrows():
                    buy_date = str(row_data.get("Date", ""))[:10]
                    shares = float(row_data.get("Shares", 0) or 0)
                    price = float(row_data.get("Price", 0) or 0)
                    value = shares * price
                    
                    if value < 100:  # 極端なノイズデータ除外
                        continue
                    
                    bulk_data.append((
                        str(f.filing_date), insider, position, ticker, company, cik,
                        price, buy_date, shares, value, filing_url
                    ))
                    saved_segment += 1
                    saved_total += 1
                
                existing_urls.add(filing_url)

                if len(bulk_data) >= 100:
                    cur.executemany("""
                        INSERT INTO insider_trades (
                            filing_date, insider, position, ticker, company, cik, 
                            avg_price, buy_date, total_shares, total_value, filing_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, bulk_data)
                    conn.commit()
                    bulk_data = []
                
            except Exception:
                continue
        
        if bulk_data:
            cur.executemany("""
                INSERT INTO insider_trades (
                    filing_date, insider, position, ticker, company, cik, 
                    avg_price, buy_date, total_shares, total_value, filing_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, bulk_data)
            conn.commit()
            
        print(f"  🎉 期間完了: データベースに {saved_segment} 件をコミット！ (小口スキップ: {skipped_by_limit} 件)")
        time.sleep(0.5)
        
    except Exception as e:
        print(f"  ❌ 期間エラー: {e}")
        continue

conn.close()
print("=" * 80)
print(f"📊 バックフィル完了！ 有意な大口取引データを合計 {saved_total} 件格納しました。")
print("=" * 80)
