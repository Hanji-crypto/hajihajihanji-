"""Form 4 提出日を起点とした比較ダッシュボード用の計算ロジック（Streamlit非依存・単体テスト可能）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 8-K の Item コード → 日本語ラベル（速報情報を一目で分類するため）
ITEM_LABELS = {
    "1.01": "重要契約の締結", "1.02": "重要契約の終了", "1.05": "サイバーインシデント",
    "2.01": "買収・処分の完了", "2.02": "決算発表", "2.03": "債務の発生",
    "2.05": "リストラ費用", "2.06": "減損", "3.01": "上場廃止・基準未達通知",
    "3.02": "未登録株の発行", "4.02": "過去決算の訂正", "5.01": "支配権の変更",
    "5.02": "役員の異動", "5.03": "定款変更", "5.07": "株主総会の結果",
    "7.01": "Reg FD開示", "8.01": "その他の重要事項", "9.01": "添付資料",
}
# 重要度が高く、チャート上で強調したい速報
HIGH_IMPACT_ITEMS = {"1.01", "1.05", "2.01", "2.02", "2.06", "3.01", "4.02", "5.01", "5.02"}


def aggregate_filings(df: pd.DataFrame) -> pd.DataFrame:
    """取引明細 → (銘柄, 提出日) 単位の1行に集約する。"""
    d = df.copy()
    d["filing_date"] = pd.to_datetime(d["filing_date"], errors="coerce").dt.normalize()
    d = d.dropna(subset=["filing_date", "ticker"])
    d["total_value"] = pd.to_numeric(d["total_value"], errors="coerce")
    d = d[d["total_value"] > 0]
    agg = (
        d.groupby(["ticker", "filing_date"], as_index=False)
        .agg(
            value=("total_value", "sum"),
            insiders=("insider", "nunique"),
            company=("company", "first"),
            filing_url=("filing_url", "first"),
        )
        .sort_values(["filing_date", "value"], ascending=[False, False])
        .reset_index(drop=True)
    )
    return agg


def returns_since_filing(prices: dict[str, pd.Series], filings: pd.DataFrame, max_days: int = 20) -> pd.DataFrame:
    """提出日（以降の最初の取引日）の終値を0%として、経過取引日ごとの騰落率(%)を返す。

    prices: {ticker: 終値Series(DatetimeIndex)}
    戻り値の列: ticker, filing_date, value, day(0..), date, ret
    """
    rows = []
    for _, f in filings.iterrows():
        s = prices.get(f["ticker"])
        if s is None or s.empty:
            continue
        s = s.dropna().sort_index()
        pos = int(s.index.searchsorted(f["filing_date"]))  # 提出日以降の最初の取引日
        if pos >= len(s):
            continue
        base = float(s.iloc[pos])
        if base <= 0:
            continue
        window = s.iloc[pos : pos + max_days + 1]
        for day, (dt, px) in enumerate(window.items()):
            rows.append((f["ticker"], f["filing_date"], f["value"], day, dt, (float(px) / base - 1.0) * 100.0))
    return pd.DataFrame(rows, columns=["ticker", "filing_date", "value", "day", "date", "ret"])


def label_of(ticker: str, filing_date: pd.Timestamp) -> str:
    return f"{ticker} {pd.Timestamp(filing_date):%m/%d}"


def cohort_mean(rets: pd.DataFrame, weighted: bool = False) -> pd.Series:
    """経過日ごとの平均騰落率（weighted=True なら購入額加重）。"""
    if rets.empty:
        return pd.Series(dtype=float)
    if weighted:
        g = rets.groupby("day").apply(lambda x: np.average(x["ret"], weights=x["value"]), include_groups=False)
    else:
        g = rets.groupby("day")["ret"].mean()
    return g


def latest_return(rets: pd.DataFrame) -> pd.DataFrame:
    """各 (銘柄, 提出日) の最新時点の騰落率と経過日数。"""
    if rets.empty:
        return rets
    idx = rets.groupby(["ticker", "filing_date"])["day"].idxmax()
    return rets.loc[idx].reset_index(drop=True)


def heat_matrix(rets: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    """行=銘柄×提出日 / 列=提出後の経過日 / 値=騰落率(%)。購入額上位 top_n のみ。"""
    if rets.empty:
        return pd.DataFrame()
    top = (
        rets.drop_duplicates(["ticker", "filing_date"])
        .nlargest(top_n, "value")[["ticker", "filing_date"]]
    )
    sub = rets.merge(top, on=["ticker", "filing_date"])
    sub["label"] = [label_of(t, d) for t, d in zip(sub["ticker"], sub["filing_date"])]
    m = sub.pivot_table(index="label", columns="day", values="ret", aggfunc="last")
    order = [label_of(t, d) for t, d in zip(top["ticker"], top["filing_date"])]
    return m.reindex([o for o in order if o in m.index])


def kpis(agg: pd.DataFrame, rets: pd.DataFrame, today: pd.Timestamp | None = None) -> dict:
    """上段KPI。today は最新の提出日（営業日基準で「直近の提出」を見るため）。"""
    if agg.empty:
        return {"latest_date": None, "n_latest": 0, "value_latest": 0.0, "n_total": 0, "avg_ret": None, "win_rate": None}
    latest_date = agg["filing_date"].max() if today is None else today
    latest = agg[agg["filing_date"] == latest_date]
    last = latest_return(rets)
    last = last[last["day"] >= 1]  # 提出当日(0%)は除く
    return {
        "latest_date": latest_date,
        "n_latest": int(len(latest)),
        "value_latest": float(latest["value"].sum()),
        "n_total": int(len(agg)),
        "avg_ret": float(last["ret"].mean()) if len(last) else None,
        "win_rate": float((last["ret"] > 0).mean() * 100) if len(last) else None,
    }


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    out = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    out = out.where(~((loss == 0) & (gain > 0)), 100.0)   # 下落なし → 100
    out = out.where(~((loss == 0) & (gain == 0)), 50.0)   # 変動なし → 50
    return out.where(gain.notna())


def items_to_label(items) -> tuple[str, bool]:
    """8-K の items 文字列（例: '2.02,9.01'）→ (日本語ラベル, 高インパクトか)。"""
    if items is None or (isinstance(items, float) and np.isnan(items)):
        return "8-K", False
    codes = [c.strip() for c in str(items).replace(";", ",").split(",") if c.strip()]
    labels = [ITEM_LABELS.get(c, c) for c in codes if c != "9.01"] or ["8-K"]
    return " / ".join(labels), any(c in HIGH_IMPACT_ITEMS for c in codes)
