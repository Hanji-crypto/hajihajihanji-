from edgar import set_identity, get_filings
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import time
import argparse
import os

from data_quality import accession_from_url, normalize_ticker, purchase_rows

# --daily: 日次更新用（直近数日のみ）/ 引数なし: 従来どおり過去6ヶ月をバックフィル
parser = argparse.ArgumentParser()
parser.add_argument("--daily", action="store_true", help="直近 --lookback-days 日分だけ取得する日次モード")
parser.add_argument("--lookback-days", type=int, default=5, help="--daily 時にさかのぼる日数（週末・祝日・取り込み遅延の余裕込み）")
parser.add_argument("--max-minutes", type=float, default=0,
                    help="この時間(分)を超えたら安全に打ち切って保存する(0=無制限)。再実行すれば取得済みURLをスキップして続きから再開")
args = parser.parse_args()
RUN_STARTED = time.time()
DEADLINE = RUN_STARTED + args.max_minutes * 60 if args.max_minutes > 0 else None
stopped_by_budget = False
window_stats = []  # 実行サマリ用: [(start, end, 開示件数, 保存件数, 小口スキップ, 状態)]

# SECへのアイデンティティ設定
set_identity("OptionScreener eae270@gmail.com")
DB_PATH = "insider.db"

# フィルター基準：1つの開示書面における「最低総投資額」 ($100,000 = 10万ドル)
# 💡 この値を変更することで、収集するデータの粒度と処理速度をコントロールできます。
MIN_FILING_VALUE_LIMIT = 100000.0

# データベースの初期化と既存キーのキャッシュ
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("🗄️ 既存のデータをメモリにキャッシュ中...")
cur.execute("SELECT DISTINCT filing_url FROM insider_trades WHERE filing_url IS NOT NULL")
existing_urls = set(row[0] for row in cur.fetchall())
# 共同提出の書類は EDGAR で提出者 CIK ごとに別URLで一覧に載るため、URLではなく受付番号で重複を判定する
existing_accessions = {a for a in map(accession_from_url, existing_urls) if a}
# 重複防止＆高速化用のインデックス（既存データは変更しない）
cur.execute("CREATE INDEX IF NOT EXISTS idx_insider_trades_filing_url ON insider_trades(filing_url)")
conn.commit()
print(f"   -> 取得済みURL数: {len(existing_urls)} 件 / 書類数(受付番号): {len(existing_accessions)} 件")

today = datetime.now()
saved_total = 0

# スキャン対象の期間リスト [(start, end), ...] を作る
if args.daily:
    windows = [(
        (today - timedelta(days=args.lookback_days)).strftime("%Y-%m-%d"),
        today.strftime("%Y-%m-%d"),
    )]
    mode_label = f"日次モード(直近{args.lookback_days}日)"
else:
    windows = [(
        (today - timedelta(days=(i + 1) * 30)).strftime("%Y-%m-%d"),
        (today - timedelta(days=i * 30)).strftime("%Y-%m-%d"),
    ) for i in range(6)]
    mode_label = "過去6ヶ月"

print("=" * 80)
print(f"🚀 【大口フィルター版】{mode_label}のインサイダーデータをスキャン中... (基準: ${MIN_FILING_VALUE_LIMIT:,.0f} 以上)")
print("=" * 80)

for start_dt, end_dt in windows:
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

            # 時間予算を超えたら、ここまでの結果を保存して正常終了する（ジョブ全体のタイムアウトで全消失するのを防ぐ）
            if DEADLINE and time.time() > DEADLINE:
                stopped_by_budget = True
                print(f"  ⏱️ 時間予算({args.max_minutes:.0f}分)に到達。ここまでを保存して終了します ({idx}/{total_filings})")
                break
            
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
            accession = getattr(f, "accession_no", None) or accession_from_url(filing_url)
            if accession and accession in existing_accessions:
                continue  # 同じ書類を別の提出者URLで取得済み

            # --- 高速フィルター2: XML構造を持たないドキュメントの即時スキップ ---
            if not hasattr(f, 'xml') or f.xml is None:
                continue
            
            try:
                # 1. まずは軽量パース（ヘッダーと大枠のオブジェクト取得）
                obj = f.obj()
                if obj is None or not hasattr(obj, "common_stock_purchases") or obj.common_stock_purchases is None or obj.common_stock_purchases.empty:
                    continue
                
                purchases = obj.common_stock_purchases

                # 2. 明細を検証・補正してから、この書類の総取引額を計算する
                #    （ティッカー無効・ADS単位のずれ・価格欄の誤記・非現実的な金額は data_quality の基準で除く）
                footnotes = getattr(obj, "footnotes", None)
                footnotes_text = footnotes.text if footnotes is not None and hasattr(footnotes, "text") else None
                rows, skipped = purchase_rows(purchases, obj.issuer.ticker, footnotes_text)
                for reason, n in skipped.items():
                    if reason != "too_small":
                        print(f"  ⚠️ 品質基準で除外({reason}): {obj.issuer.ticker} {n} 行 filing={filing_url}")
                total_filing_value = sum(r["value"] for r in rows)

                # 3. 基準額（$100k）未満であれば、明細のDB格納処理を一切行わずに即スキップ
                if total_filing_value < MIN_FILING_VALUE_LIMIT:
                    skipped_by_limit += 1
                    continue

                # --- 基準をクリアした大口取引のみ詳細を保存 ---
                ticker = normalize_ticker(obj.issuer.ticker)
                insider = obj.insider_name
                position = obj.position
                company = obj.issuer.name
                cik = obj.issuer.cik

                if not filing_url:
                    filing_url = f"https://www.sec.gov/edgar/browse/?CIK={cik}"

                for r in rows:
                    bulk_data.append((
                        str(f.filing_date), insider, position, ticker, company, cik,
                        r["price"], r["buy_date"], r["shares"], r["value"], filing_url
                    ))
                    saved_segment += 1
                    saved_total += 1

                existing_urls.add(filing_url)
                if accession:
                    existing_accessions.add(accession)

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
        window_stats.append((start_dt, end_dt, total_filings, saved_segment, skipped_by_limit,
                             "時間切れで途中終了" if stopped_by_budget else "完了"))
        if stopped_by_budget:
            break
        time.sleep(0.5)
        
    except Exception as e:
        print(f"  ❌ 期間エラー: {e}")
        continue

# --- 実行サマリ(GitHub Actions の Run ページに表示) ---
elapsed_min = (time.time() - RUN_STARTED) / 60
latest = cur.execute("SELECT MAX(filing_date), COUNT(*) FROM insider_trades").fetchone()
summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
if summary_path:
    lines = [f"## インサイダーデータ更新 ({mode_label})", "",
             f"- 所要時間: {elapsed_min:.1f} 分" + (f" / 予算 {args.max_minutes:.0f} 分" if DEADLINE else ""),
             f"- 今回の新規保存: **{saved_total:,}** 件",
             f"- DB最新の提出日: **{latest[0]}** / 総行数: {latest[1]:,}",
             "- 状態: " + ("⚠️ 時間予算で途中終了（再実行で続きから再開）" if stopped_by_budget else "✅ 完了"), "",
             "| 期間 | 開示件数 | 保存 | 小口スキップ | 状態 |", "|---|--:|--:|--:|---|"]
    for a, b, n, sv, sk, st in window_stats:
        lines.append(f"| {a} 〜 {b} | {n:,} | {sv:,} | {sk:,} | {st} |")
    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

conn.close()
print("=" * 80)
print(f"📊 バックフィル完了！ 有意な大口取引データを合計 {saved_total} 件格納しました。")
print("=" * 80)
