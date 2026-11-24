"""data_quality（表示側・取り込み側の品質基準）のテスト。実行: pytest"""
import os
import sqlite3

import pandas as pd
import pytest

import data_quality as dq

DB = os.path.join(os.path.dirname(__file__), "insider.db")

U1 = "https://www.sec.gov/Archives/edgar/data/1894693/0001731122-26-000579-index.html"
U2 = "https://www.sec.gov/Archives/edgar/data/2038439/0001731122-26-000579-index.html"  # 同じ書類の別提出者URL


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("AAPL", "AAPL"), (" aapl ", "AAPL"), ("BRK.A", "BRK.A"), ("CFTR-PRA", "CFTR-PRA"),
        ("NASDAQ:SVC", "SVC"), ("HEI, HEI.A", "HEI"), ("N O G", "NOG"),
        ("NONE", None), ("none", None), ("N/A", None), ("[NONE]", None), ("N.A.", None),
        ("", None), (None, None), (float("nan"), None), ("AB-Lend", None), ("CSAN3", None), ("TOOLONGX", None),
    ],
)
def test_normalize_ticker(raw, expected):
    assert dq.normalize_ticker(raw) == expected


def test_accession_from_url():
    assert dq.accession_from_url(U1) == "0001731122-26-000579"
    assert dq.accession_from_url(
        "https://www.sec.gov/Archives/edgar/data/1620463/000212618626000002/0002126186-26-000002-index.html"
    ) == "0002126186-26-000002"
    assert dq.accession_from_url("https://www.sec.gov/Archives/edgar/data/1/000212618626000002/") == "0002126186-26-000002"
    assert dq.accession_from_url(None) is None


def _row(i, ticker, price, shares, url, value=None, buy="2026-05-01", filed="2026-05-03"):
    return {
        "id": i, "ticker": ticker, "avg_price": price, "total_shares": shares,
        "total_value": price * shares if value is None and price and shares else value,
        "filing_url": url, "buy_date": buy, "filing_date": filed, "insider": "x", "company": "c",
    }


def _df(rows):
    return pd.DataFrame(rows)


def test_clean_trades_each_rule():
    rows = [
        _row(1, "AAPL", 200.0, 1000, "https://x/0000000001-26-000001-index.html"),            # 残る
        _row(2, "NONE", 10.0, 50_000, "https://x/0000000001-26-000002-index.html"),           # 無効ティッカー
        _row(3, "N/A", 10.0, 50_000, "https://x/0000000001-26-000003-index.html"),            # 無効ティッカー
        _row(4, "MSFT", 400.0, 500, "https://a/1/0000000001-26-000004-index.html"),            # 残る
        _row(5, "MSFT", 400.0, 500, "https://a/2/0000000001-26-000004-index.html"),            # 同じ書類の重複
        _row(6, "SBLK", 227_538.0, 11_500, "https://x/0000000001-26-000006-index.html"),       # 価格欄に総額
        _row(7, "LONA", 3149.47, 3_149_470, "https://x/0000000001-26-000007-index.html"),      # $9.9B
        _row(8, "TXTM", None, 1000, "https://x/0000000001-26-000008-index.html", value=None),  # 欠損
        _row(9, "BRK.A", 700_000.0, 2, "https://x/0000000001-26-000009-index.html"),           # 高額株は残す
        _row(10, "SVRE", 3.45, 2_501_582_400, U1, buy="2026-04-09", filed="2026-04-15"),       # ADS 補正
        _row(11, "SVRE", 3.45, 2_501_582_400, U2, buy="2026-04-09", filed="2026-04-15"),       # その重複
    ]
    out, rep = dq.clean_trades(_df(rows))
    assert sorted(out["id"]) == [1, 4, 9, 10]
    assert rep.excluded == {
        "invalid_ticker": 2, "duplicate_filing": 2, "missing_value": 1, "price_too_high": 1, "value_too_large": 1,
    }
    assert rep.corrected == {"ads_ratio": 1}
    assert rep.total_rows == 11 and rep.kept_rows == 4 and rep.excluded_rows == 7
    svre = out[out["id"] == 10].iloc[0]
    assert svre["total_shares"] == 57_907  # 2,501,582,400 / 43,200（脚注の ADS 数）
    assert svre["total_value"] == pytest.approx(57_907 * 3.45)


def test_ads_correction_skips_rows_ingested_after_fix():
    # 取り込み側を直した後の行は ADS 数で入っているので補正しない
    rows = [_row(1, "SVRE", 4.0, 57_907, "https://x/0000000001-26-000010-index.html", filed="2026-12-01")]
    out, rep = dq.clean_trades(_df(rows))
    assert out.iloc[0]["total_shares"] == 57_907 and rep.corrected["ads_ratio"] == 0


def test_clean_trades_keeps_identical_lines_within_one_filing():
    # 同じ書類（同じURL）の中の同額の明細は重複ではない
    url = "https://x/0000000001-26-000011-index.html"
    out, rep = dq.clean_trades(_df([_row(1, "AAPL", 10.0, 100, url), _row(2, "AAPL", 10.0, 100, url)]))
    assert len(out) == 2 and rep.excluded["duplicate_filing"] == 0


def test_clean_trades_empty():
    out, rep = dq.clean_trades(pd.DataFrame(columns=["ticker", "avg_price", "total_shares", "total_value"]))
    assert out.empty and rep.total_rows == 0


# ---------------------------------------------------------------- 取り込み側
SVRE_FOOTNOTE = (
    'The price reported is the price per American Depositary Share ("ADS") acquired in an open-market transaction '
    "on The Nasdaq Stock Market LLC. Each ADS represents 43,200 ordinary shares of the Issuer pursuant to the ADS "
    "ratio effective February 25, 2026."
)


def test_ads_ratio_from_footnotes():
    assert dq.ads_ratio_from_footnotes(SVRE_FOOTNOTE) == 43_200
    assert dq.ads_ratio_from_footnotes("Each American Depositary Share represents 10 ordinary shares.") == 10
    assert dq.ads_ratio_from_footnotes("The shares are held by a trust.") is None
    assert dq.ads_ratio_from_footnotes(None) is None


def _purchases(rows):
    return pd.DataFrame(rows, columns=["Security", "Date", "Shares", "Price"])


def test_purchase_rows_ads_and_limits():
    p = _purchases([
        ("Ordinary Shares", "2026-04-09", 2_501_582_400, 3.45),
        ("Ordinary Shares", "2026-04-02", 288_014_400, 2.93),
    ])
    rows, skipped = dq.purchase_rows(p, "SVRE", SVRE_FOOTNOTE)
    assert [r["shares"] for r in rows] == [57_907, 6_667]
    assert rows[0]["value"] == pytest.approx(199_779.15)
    assert skipped == {}

    rows, skipped = dq.purchase_rows(_purchases([("Common", "2026-03-31", 11_500, 227_538)]), "SBLK")
    assert rows == [] and skipped == {"price_too_high": 1}

    rows, skipped = dq.purchase_rows(_purchases([("Common", "2026-10-26", 3_149_470, 3149.47)]), "LONA")
    assert rows == [] and skipped == {"value_too_large": 1}

    rows, skipped = dq.purchase_rows(_purchases([("Common", "2026-10-26", 1000, 10.0)]), "NONE")
    assert rows == [] and skipped == {"invalid_ticker": 1}

    rows, skipped = dq.purchase_rows(_purchases([("Common", "2026-10-26", 1, 5.0)]), "AAPL")
    assert rows == [] and skipped == {"too_small": 1}

    rows, _ = dq.purchase_rows(_purchases([("Common", "2026-10-26", 1000, 150.0)]), "aapl")
    assert rows == [{"buy_date": "2026-10-26", "shares": 1000.0, "price": 150.0, "value": 150_000.0}]


# ---------------------------------------------------------------- 実データでの回帰（insider.db の既知の誤データ）
@pytest.mark.skipif(not os.path.exists(DB), reason="insider.db が無い")
def test_real_db_screener_has_no_known_errors():
    from data_loader import generate_screener, load_and_process_data

    scr = generate_screener(load_and_process_data())
    assert not scr["ticker"].isin(["NONE", "N/A", "NA", "UNKNOWN", "N"]).any()
    svre = scr.loc[scr["ticker"] == "SVRE", "net_flow"]
    assert svre.empty or svre.iloc[0] < 5_000_000  # 生データでは +$53.9B
    assert scr["net_flow"].max() < 5_000_000_000

    raw = pd.read_sql_query("SELECT * FROM insider_trades", sqlite3.connect(DB))
    out, rep = dq.clean_trades(raw)
    assert out.groupby("filing_url").ngroups == out["filing_url"].map(dq.accession_from_url).nunique()
    assert rep.kept_rows + rep.excluded_rows == rep.total_rows


# ---------------------------------------------------------------- 原典リンク（発行会社の CIK のフォルダ）
OWNER = "https://www.sec.gov/Archives/edgar/data/1579179/000119312526473131/0001193125-26-473131-index.html"
ISSUER = "https://www.sec.gov/Archives/edgar/data/1341235/000119312526473131/0001193125-26-473131-index.htm"


def test_issuer_filing_url():
    assert dq.issuer_filing_url(OWNER, "0001341235") == ISSUER
    assert dq.issuer_filing_url(ISSUER, 1341235) == ISSUER                  # 既に正しければ同じ
    assert dq.issuer_filing_url(U1, "0000320193") == (                      # 受付番号のフォルダが無い形も直す
        "https://www.sec.gov/Archives/edgar/data/320193/000173112226000579/0001731122-26-000579-index.htm")
    same = "https://www.sec.gov/Archives/edgar/data/1287032/000129435726000018/0001294357-26-000018-index.html"
    assert dq.issuer_filing_url(same, "0001287032") == same                  # 発行会社のフォルダなら書き方も変えない
    assert dq.issuer_filing_url(U1, "1894693") == U1
    assert dq.issuer_filing_url(OWNER, None) == OWNER                       # CIK が無ければそのまま
    assert dq.issuer_filing_url(OWNER, "abc") == OWNER
    assert dq.issuer_filing_url("https://www.sec.gov/", "1") == "https://www.sec.gov/"  # 受付番号が無ければそのまま


def test_clean_trades_rewrites_links_to_issuer_folder_without_touching_input():
    raw = pd.DataFrame([{"id": 1, "ticker": "ALDX", "cik": "0001341235", "avg_price": 0.81,
                         "total_shares": 300_000, "total_value": 243_060.0, "filing_url": OWNER}])
    out, _ = dq.clean_trades(raw)
    assert out["filing_url"].tolist() == [ISSUER]
    assert raw["filing_url"].tolist() == [OWNER]                             # 元の表（DB の値）は変えない
    no_cik, _ = dq.clean_trades(raw.drop(columns="cik"))                     # cik 列が無ければ直さない
    assert no_cik["filing_url"].tolist() == [OWNER]


def test_load_trades_returns_issuer_links_and_db_is_unchanged(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE insider_trades (id INTEGER, filing_date TEXT, ticker TEXT, cik TEXT, avg_price REAL,"
                 " total_shares REAL, total_value REAL, filing_url TEXT)")
    conn.execute("INSERT INTO insider_trades VALUES (1, '2026-11-24', 'ALDX', '0001341235', 0.81, 300000, 243060, ?)",
                 (OWNER,))
    conn.commit()
    conn.close()
    df, _ = dq.load_trades(str(db))
    assert df["filing_url"].tolist() == [ISSUER]
    (stored,) = sqlite3.connect(db).execute("SELECT filing_url FROM insider_trades").fetchone()
    assert stored == OWNER
