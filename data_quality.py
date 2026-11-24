"""インサイダー取引データの品質チェック（表示側・取り込み側で共通の基準）。

insider.db には、Form 4 の取り込み時に入った誤データが残っている。
DB は書き換えず、読み込むたびにここで除外・補正してから画面に出す。
取り込み側（a5_backfill_v3.py）も同じ関数で判定し、今後の行に誤りを入れない。

■ 除外・補正の基準（行単位。上から順に判定）
1. invalid_ticker   : ティッカーが無い/プレースホルダ（NONE, N/A など）/米国株の形でない。
                      非上場ファンド（BDC・インターバルファンド）の Form 4 が "NONE" "N/A" で入る。
                      "NASDAQ:SVC" → "SVC"、"HEI, HEI.A" → "HEI"、小文字 → 大文字 などは正規化して残す。
2. duplicate_filing : 同じ書類（受付番号が同じ）が、提出者ごとの別URLで重複して入った行。
                      EDGAR は共同提出の書類を提出者 CIK ごとに一覧へ載せるため、URL で重複判定すると
                      2〜7 回入る。書類ごとに最初に入った URL の行だけ残す。
3. missing_value    : 価格・株数・金額のどれかが欠けている/0以下。
4. （補正）ads_ratio : ADS 価格に普通株の株数が掛けられている既知銘柄（ADS_RATIOS）。株数を ADS 数に直す。
                      取り込み側を直す前に入った行だけが対象。
5. price_too_high   : 1株 $10,000 超（BRK.A などの高額株を除く）。総額を価格欄に入れた誤記。
6. value_too_large  : 1行の金額が $10億 超。単位・株数の誤り（インサイダーの市場買いとして非現実的）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --- 基準値（変える時はテストも合わせて直す） ---
PLACEHOLDER_TICKERS = {"", "NONE", "N/A", "NA", "NULL", "NAN", "UNKNOWN", "-", "--", "TBD"}
TICKER_PATTERN = re.compile(r"^[A-Z]{1,5}([.\-][A-Z]{1,3})?$")
MAX_SHARE_PRICE = 10_000.0
HIGH_PRICE_ALLOWLIST = {"BRK.A", "BRK-A", "BRKA"}
MAX_ROW_VALUE = 1_000_000_000.0

# ADS 価格 × 普通株数 で入っている銘柄: {ティッカー: (取引日の下限, 提出日の上限, 1 ADS あたりの普通株数)}
# SVRE: 書類の脚注 F1「Each ADS represents 43,200 ordinary shares ... effective February 25, 2026」。
# 提出日の上限 = 取り込み側を直した日。それより後の行は取り込み時に ADS 数で入るので補正しない。
INGEST_FIX_DATE = "2026-11-23"
ADS_RATIOS: dict[str, tuple[str, str, int]] = {
    "SVRE": ("2026-02-25", INGEST_FIX_DATE, 43_200),
}

REASON_LABELS = {
    "invalid_ticker": "ティッカー無効（NONE・N/A など）",
    "duplicate_filing": "同じ書類の重複",
    "missing_value": "価格・株数・金額の欠損",
    "price_too_high": f"1株 ${MAX_SHARE_PRICE:,.0f} 超（価格欄の誤記）",
    "value_too_large": f"1行 ${MAX_ROW_VALUE / 1e9:,.0f}B 超（単位の誤り）",
    "ads_ratio": "ADS 比率で株数を補正",
}

_ACCESSION_DASHED = re.compile(r"(\d{10}-\d{2}-\d{6})")
_ACCESSION_PLAIN = re.compile(r"/(\d{18})(?:/|$)")


def normalize_ticker(raw) -> str | None:
    """ティッカーを正規化する。無効なら None。"""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    t = str(raw).strip().upper()
    if t in PLACEHOLDER_TICKERS or t.strip("[]()") in PLACEHOLDER_TICKERS:
        return None
    if ":" in t:  # "NASDAQ:SVC" → "SVC"
        t = t.split(":")[-1]
    t = re.split(r"[,;]", t)[0].strip()  # "HEI, HEI.A" → "HEI"
    t = t.replace(" ", "")  # "N O G" → "NOG"
    if t in PLACEHOLDER_TICKERS or not TICKER_PATTERN.match(t):
        return None
    return t


def accession_from_url(url) -> str | None:
    """書類 URL から受付番号（0001234567-26-000123）を取り出す。"""
    if not isinstance(url, str):
        return None
    m = _ACCESSION_DASHED.search(url)
    if m:
        return m.group(1)
    m = _ACCESSION_PLAIN.search(url)
    if m:
        d = m.group(1)
        return f"{d[:10]}-{d[10:12]}-{d[12:]}"
    return None


def row_problem(ticker, price, shares, value) -> str | None:
    """1行の取引が基準を満たさない理由（満たせば None）。取り込み側でも使う。"""
    if ticker is None:
        return "invalid_ticker"
    vals = [price, shares, value]
    if any(v is None or pd.isna(v) or v <= 0 for v in vals):
        return "missing_value"
    if price > MAX_SHARE_PRICE and ticker not in HIGH_PRICE_ALLOWLIST:
        return "price_too_high"
    if value > MAX_ROW_VALUE:
        return "value_too_large"
    return None


@dataclass
class QualityReport:
    total_rows: int = 0
    kept_rows: int = 0
    excluded: dict = field(default_factory=dict)  # 理由 → 行数
    corrected: dict = field(default_factory=dict)  # 理由 → 行数

    @property
    def excluded_rows(self) -> int:
        return sum(self.excluded.values())

    def summary_lines(self) -> list[str]:
        lines = [f"{REASON_LABELS.get(k, k)}: {v:,} 行を除外" for k, v in self.excluded.items() if v]
        lines += [f"{REASON_LABELS.get(k, k)}: {v:,} 行" for k, v in self.corrected.items() if v]
        return lines


def clean_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, QualityReport]:
    """insider_trades の生データ（DB の列名のまま）を基準で除外・補正する。

    必要な列: ticker, avg_price, total_shares, total_value。filing_url, id, buy_date, filing_date があれば重複判定・補正に使う。
    """
    report = QualityReport(total_rows=len(df))
    if df.empty:
        return df.copy(), report
    out = df.copy()

    # 1. ティッカー
    out["ticker"] = out["ticker"].map(normalize_ticker)
    bad = out["ticker"].isna()
    report.excluded["invalid_ticker"] = int(bad.sum())
    out = out[~bad]

    # 2. 同じ書類の重複（受付番号ごとに最初に入ったURLの行だけ残す）
    if "filing_url" in out.columns:
        acc = out["filing_url"].map(accession_from_url).fillna(out["filing_url"].astype(str))
        order = out["id"] if "id" in out.columns else pd.Series(np.arange(len(out)), index=out.index)
        first_url = (
            pd.DataFrame({"acc": acc, "url": out["filing_url"], "order": order})
            .sort_values("order")
            .groupby("acc")["url"]
            .first()
        )
        dup = out["filing_url"].values != acc.map(first_url).values
        report.excluded["duplicate_filing"] = int(dup.sum())
        out = out[~dup]

    for col in ("avg_price", "total_shares", "total_value"):
        out[col] = pd.to_numeric(out[col], errors="coerce")

    # 3. 欠損
    miss = (
        out[["avg_price", "total_shares", "total_value"]].isna().any(axis=1)
        | (out[["avg_price", "total_shares", "total_value"]] <= 0).any(axis=1)
    )
    report.excluded["missing_value"] = int(miss.sum())
    out = out[~miss].copy()

    # 4. ADS 比率の補正（取り込み側を直す前に入った行だけ。株数が比率以上なら普通株数とみなして ADS 数に直す）
    fixed = 0
    if "buy_date" in out.columns and "filing_date" in out.columns:
        trade_d = pd.to_datetime(out["buy_date"], errors="coerce")
        filed_d = pd.to_datetime(out["filing_date"], errors="coerce")
        for tk, (since, until, ratio) in ADS_RATIOS.items():
            m = (
                (out["ticker"] == tk)
                & (trade_d >= pd.Timestamp(since))
                & (filed_d <= pd.Timestamp(until))
                & (out["total_shares"] >= ratio)
            )
            if m.any():
                out.loc[m, "total_shares"] = (out.loc[m, "total_shares"] / ratio).round()
                out.loc[m, "total_value"] = out.loc[m, "total_shares"] * out.loc[m, "avg_price"]
                fixed += int(m.sum())
    report.corrected["ads_ratio"] = fixed

    # 5〜6. 価格・金額の上限
    price_bad = (out["avg_price"] > MAX_SHARE_PRICE) & ~out["ticker"].isin(HIGH_PRICE_ALLOWLIST)
    report.excluded["price_too_high"] = int(price_bad.sum())
    out = out[~price_bad]
    value_bad = out["total_value"] > MAX_ROW_VALUE
    report.excluded["value_too_large"] = int(value_bad.sum())
    out = out[~value_bad]

    # 7. 原典リンクを発行会社の CIK のフォルダに組み直す（DB は書き換えず、表示用の値だけ直す）
    out = with_issuer_filing_urls(out)

    report.kept_rows = len(out)
    return out, report


def issuer_filing_url(url, cik):
    """内部者など別の CIK のフォルダを指す書類の URL を、発行会社の CIK のフォルダの索引ページに組み直す。

    insider.db の filing_url は、取り込み時の書類の提出者（内部者本人など）の CIK のフォルダを指すことが多く、
    EDGAR では 404 になる書類がある（例: ALDX 0001193125-26-473131 の 1579179 側）。
    - 既に発行会社のフォルダを指していれば、そのまま返す（書き方を変えると開けなくなる書類がある）。
    - 組み直す時の索引ページは「-index.htm」（EDGAR の標準。実測で .html より開ける割合が高い）。
    - CIK か受付番号が読めない時は元の値のまま。
    """
    acc = accession_from_url(url)
    try:
        cik_num = int(str(cik).strip())
    except (TypeError, ValueError):
        return url
    if not acc or cik_num <= 0:
        return url
    m = _ARCHIVE_CIK.search(url)
    if m and int(m.group(1)) == cik_num:
        return url
    return f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc.replace('-', '')}/{acc}-index.htm"


_ARCHIVE_CIK = re.compile(r"/Archives/edgar/data/(\d+)/")


def with_issuer_filing_urls(df: pd.DataFrame) -> pd.DataFrame:
    """filing_url と cik（発行会社）の列があれば、filing_url を発行会社のフォルダの URL に置き換えた写しを返す。"""
    if df.empty or not {"filing_url", "cik"} <= set(df.columns):
        return df
    out = df.copy()
    out["filing_url"] = [issuer_filing_url(u, c) for u, c in zip(out["filing_url"], out["cik"])]
    return out


# ---------------------------------------------------------------- 取り込み側（a5_backfill_v3.py）用
_ADS_RATIO_PATTERN = re.compile(
    r"(?:each|one|1)\s+(?:ADS|American\s+Depositary\s+Shares?)\s*(?:\(\s*\"?ADS\"?\s*\))?\s+represents\s+([\d,]+)\s+ordinary\s+shares",
    re.IGNORECASE,
)
MIN_ROW_VALUE = 100.0  # 端数のノイズ行は入れない


def ads_ratio_from_footnotes(text: str | None) -> int | None:
    """脚注に「Each ADS represents N ordinary shares」とあれば N を返す。"""
    if not text:
        return None
    m = _ADS_RATIO_PATTERN.search(text)
    if not m:
        return None
    n = int(m.group(1).replace(",", ""))
    return n if n > 1 else None


def purchase_rows(purchases: pd.DataFrame, ticker_raw, footnotes_text: str | None = None) -> tuple[list[dict], dict]:
    """Form 4 の市場買い明細（edgartools の common_stock_purchases）を保存用の行にする。

    - ティッカーを正規化し、無効なら1行も返さない。
    - 価格が ADS 単位で株数が普通株単位の書類（脚注で判定）は、株数を ADS 数に直す。
    - row_problem() の基準に当たる行と、金額 $100 未満の行は除く。
    戻り値: (行のリスト[{buy_date, shares, price, value}], 除いた理由 → 行数)
    """
    skipped: dict[str, int] = {}
    ticker = normalize_ticker(ticker_raw)
    if ticker is None:
        skipped["invalid_ticker"] = len(purchases)
        return [], skipped
    ratio = ads_ratio_from_footnotes(footnotes_text)
    rows = []
    for _, r in purchases.iterrows():
        shares = float(r.get("Shares", 0) or 0)
        price = float(r.get("Price", 0) or 0)
        security = str(r.get("Security", "") or "")
        if ratio and "ordinary" in security.lower() and shares >= ratio:
            shares = round(shares / ratio)
        value = shares * price
        problem = row_problem(ticker, price, shares, value)
        if problem is None and value < MIN_ROW_VALUE:
            problem = "too_small"
        if problem:
            skipped[problem] = skipped.get(problem, 0) + 1
            continue
        rows.append({"buy_date": str(r.get("Date", ""))[:10], "shares": shares, "price": price, "value": value})
    return rows, skipped


def load_trades(db_path: str, columns: str = "*") -> tuple[pd.DataFrame, QualityReport]:
    """insider_trades を読み込み、品質基準で除外・補正して返す（全ページ共通の入口）。"""
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(f"SELECT {columns} FROM insider_trades", conn)
    finally:
        conn.close()
    return clean_trades(df)
