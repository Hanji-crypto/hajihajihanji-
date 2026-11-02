"""compare_logic の動作確認。実行: python test_compare_logic.py"""
import numpy as np
import pandas as pd

import compare_logic as cl

idx = pd.bdate_range("2026-10-01", "2026-11-02")
PRICES = {
    "A": pd.Series(100 * 1.01 ** np.arange(len(idx)), index=idx),   # 毎日 +1%
    "B": pd.Series(50 * 0.99 ** np.arange(len(idx)), index=idx),    # 毎日 -1%
    "C": pd.Series(10.0, index=pd.bdate_range("2026-10-01", "2026-10-10")),  # 提出日以降の価格なし
}
TRADES = pd.DataFrame({
    "filing_date": ["2026-10-10", "2026-10-10", "2026-10-15", "2026-10-20", "2026-10-20"],  # 10/10 は土曜
    "insider": list("xyzwv"), "ticker": ["A", "A", "B", "C", "B"], "company": ["c"] * 5,
    "total_value": [100000, 50000, 200000, 300000, 0], "filing_url": ["u"] * 5,
})


def test_all():
    agg = cl.aggregate_filings(TRADES)
    assert len(agg) == 3                                  # 同日同銘柄は集約、0円は除外
    a_row = agg[agg.ticker == "A"].iloc[0]
    assert a_row.value == 150000 and a_row.insiders == 2

    r = cl.returns_since_filing(PRICES, agg, max_days=5)
    assert "C" not in set(r.ticker)                       # 価格がない銘柄は除外
    a = r[r.ticker == "A"].sort_values("day")
    assert a.iloc[0]["date"] == pd.Timestamp("2026-10-12")  # 休日提出 → 翌営業日が基準(0%)
    assert abs(a.iloc[0]["ret"]) < 1e-9 and abs(a.iloc[1]["ret"] - 1.0) < 1e-6
    assert r.groupby(["ticker", "filing_date"])["day"].max().max() == 5

    assert abs(cl.cohort_mean(r)[1]) < 1e-6               # +1% と -1% の平均
    assert cl.cohort_mean(r, weighted=True)[1] < 0        # 購入額の大きい B に引っ張られる
    assert cl.heat_matrix(r, top_n=5).shape[0] == 2

    idx_ = pd.bdate_range("2026-10-01", "2026-11-02")
    assert cl.rsi(pd.Series(np.arange(1, len(idx_) + 1.0), index=idx_)).iloc[-1] == 100.0
    assert cl.items_to_label("2.02,9.01") == ("決算発表", True)
    assert cl.items_to_label(None) == ("8-K", False)


if __name__ == "__main__":
    test_all()
    print("OK")
