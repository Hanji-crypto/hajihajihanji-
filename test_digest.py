"""digest.py（毎朝のメール「インサイダー大口買い Top5」）のテスト。実行: pytest test_digest.py"""
import json
from datetime import date, datetime

import pandas as pd
import pytest

import digest as dg
from data_status import US_EASTERN

D = date(2026, 11, 20)
CFG = dg.DigestConfig(sender_name="送信者テスト", sender_contact="contact-test",
                      dashboard_url="https://dash.example/whale-eye?ticker={ticker}")


def _row(i, ticker, value, *, filed="2026-11-20", insider="Jane Doe", position="Director",
         price=10.0, url=None, code=None, company=None, cik="0000320193"):
    r = {
        "id": i, "filing_date": filed, "insider": insider, "position": position, "ticker": ticker,
        "company": company or f"{ticker} Inc.", "cik": cik, "avg_price": price, "buy_date": filed,
        "total_shares": value / price if price else 100, "total_value": value,
        "filing_url": url or f"https://www.sec.gov/Archives/edgar/data/1/0000000001-26-{i:06d}-index.html",
    }
    if code is not None:
        r["transaction_code"] = code
    return r


def _top(rows, target=D):
    return dg.select_top(pd.DataFrame(rows), target)


# ---------------------------------------------------------------- 選び方
def test_ranks_by_company_total_and_limits_to_five():
    rows = [_row(i, tk, v) for i, (tk, v) in enumerate(
        [("AAA", 100_000), ("BBB", 900_000), ("CCC", 300_000), ("DDD", 500_000),
         ("EEE", 700_000), ("FFF", 200_000), ("AAA", 950_000)], 1)]
    picks = _top(rows)
    assert [p.ticker for p in picks] == ["AAA", "BBB", "EEE", "DDD", "CCC"]  # AAA は 2 行の合計 $1.05M
    assert picks[0].total_value == 1_050_000
    assert [p.rank for p in picks] == [1, 2, 3, 4, 5]


def test_quality_excluded_rows_are_not_selected():
    rows = [
        _row(1, "NONE", 50_000_000),                                     # 無効ティッカー
        _row(2, "BIG", 2_000_000_000),                                   # 1行 $10億超
        _row(3, "PRC", 5_000_000, price=50_000.0),                       # 1株 $10,000 超
        _row(4, "DUP", 1_000_000, url="https://www.sec.gov/Archives/edgar/data/1/0000000009-26-000001-index.html"),
        _row(5, "DUP", 1_000_000, url="https://www.sec.gov/Archives/edgar/data/2/0000000009-26-000001-index.html"),
        _row(6, "MIS", 0),                                               # 金額 0
        _row(7, "OK", 10_000),
    ]
    picks = _top(rows)
    assert [p.ticker for p in picks] == ["DUP", "OK"]
    assert picks[0].total_value == 1_000_000  # 同じ書類の重複は1回だけ数える
    assert picks[0].filing_urls == [BROWSE_320193]        # 未解決は発行体の Form 4 一覧
    assert picks[0].accessions == ["0000000009-26-000001"]
    assert picks[0].owner_ciks == [1]


BROWSE_320193 = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=320193"
                 "&type=4&dateb=&owner=include&count=40")
OWNER = "https://www.sec.gov/Archives/edgar/data/1579179/000119312526473131/0001193125-26-473131-index.html"
XSL = "https://www.sec.gov/Archives/edgar/data/1341235/000119312526473131/xslF345X05/ownership.xml"
TXT = (b"<SEC-DOCUMENT>\n<DOCUMENT>\n<TYPE>4\n<SEQUENCE>1\n<FILENAME>ownership.xml\n<TEXT>\n<XML>...</XML>\n"
       b"</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>\n")


def test_resolved_links_come_from_filing_links_json(tmp_path, monkeypatch):
    path = tmp_path / "filing_links.json"
    path.write_text(json.dumps({"links": {"0001193125-26-473131": XSL}, "unresolved": {}}), encoding="utf-8")
    monkeypatch.setattr(dg.filing_links, "LINKS_PATH", str(path))
    picks = _top([_row(1, "ALDX", 243_060, url=OWNER, cik="0001341235")])
    assert picks[0].filing_urls == [XSL]
    assert picks[0].owner_ciks == [1579179]


def test_resolve_links_on_the_spot_and_fallback():
    picks = _top([_row(1, "ALDX", 243_060, url=OWNER, cik="0001341235"),
                  _row(2, "AAA", 100_000, cik="0000320193")])
    calls = []

    def fake_get(url):
        calls.append(url)
        if url.endswith("0001193125-26-473131.txt") and "/1341235/" in url:
            return 200, TXT
        return (200, b"<html>") if url == XSL else (404, b"")

    failed = dg.resolve_links(picks, get=fake_get)
    aldx = next(p for p in picks if p.ticker == "ALDX")
    aaa = next(p for p in picks if p.ticker == "AAA")
    assert aldx.filing_urls == [XSL]                              # 発行体の .txt → XML 名 → 表示用 HTML
    assert aaa.filing_urls == [BROWSE_320193]                     # 開かなければ Form 4 一覧のまま
    assert failed == [aaa.accessions[0]]
    assert calls[0].endswith("/1341235/000119312526473131/0001193125-26-473131.txt")  # 発行体のフォルダから
    # 解決済みは問い合わせない
    calls.clear()
    assert dg.resolve_links([aldx], get=fake_get) == [] and calls == []


def test_mail_labels_links():
    picks = _top([_row(1, "AAA", 100_000, cik="0000320193")])
    d = dg.build_digest(picks, D, None, CFG, "https://u.example/unsub")
    assert "Form 4（受付番号 0000000001-26-000001）・発行体の Form 4 一覧" in d.text
    picks[0].filing_urls = [XSL]
    d = dg.build_digest(picks, D, None, CFG, "https://u.example/unsub")
    assert f"Form 4（受付番号 0000000001-26-000001） {XSL}" in d.text


def test_non_purchase_codes_are_not_selected():
    rows = [_row(1, "SEL", 9_000_000, code="S"), _row(2, "AWD", 8_000_000, code="A"),
            _row(3, "BUY", 100_000, code="P"), _row(4, "LOW", 50_000, code=" p ")]
    assert [p.ticker for p in _top(rows)] == ["BUY", "LOW"]


def test_rows_without_code_column_are_purchases():
    # 今の DB には取引コードの列が無い（取り込み側が P だけを保存する）
    assert [p.ticker for p in _top([_row(1, "AAA", 100_000)])] == ["AAA"]


def test_ties_are_broken_by_ticker_alphabetically():
    rows = [_row(1, "ZZZ", 500_000), _row(2, "MMM", 500_000), _row(3, "AAA", 500_000),
            _row(4, "QQQ", 500_000), _row(5, "BBB", 500_000), _row(6, "CCC", 500_000)]
    assert [p.ticker for p in _top(rows)] == ["AAA", "BBB", "CCC", "MMM", "QQQ"]
    assert [p.ticker for p in _top(list(reversed(rows)))] == ["AAA", "BBB", "CCC", "MMM", "QQQ"]


def test_only_target_filing_date_and_empty_day():
    rows = [_row(1, "OLD", 9_000_000, filed="2026-11-19"), _row(2, "NEW", 100_000)]
    assert [p.ticker for p in _top(rows)] == ["NEW"]
    assert _top(rows, date(2026, 11, 21)) == []  # 休場日（提出なし）は空
    assert dg.select_top(pd.DataFrame(), D) == []


def test_company_details_and_30_day_cluster():
    rows = [
        _row(1, "ABC", 300_000, insider="Alice", position="CEO", price=20.0),
        _row(2, "ABC", 100_000, insider="Bob", position="CFO", price=10.0),
        _row(3, "ABC", 50_000, insider="Carol", filed="2026-11-01"),
        _row(4, "ABC", 50_000, insider="Dan", filed="2026-10-01"),  # 30日より前
    ]
    p = _top(rows)[0]
    assert [(i.name, i.position) for i in p.insiders] == [("Alice", "CEO"), ("Bob", "CFO")]
    assert p.shares == 25_000 and p.total_value == 400_000
    assert p.avg_price == pytest.approx(16.0)  # 金額 / 株数
    assert p.recent_filings_30d == 3 and p.recent_insiders_30d == 3 and p.is_cluster


def test_previous_business_day_skips_weekend_and_holiday():
    assert dg.previous_business_day(datetime(2026, 11, 23, 17, tzinfo=US_EASTERN)) == date(2026, 11, 20)  # 月→金
    assert dg.previous_business_day(datetime(2026, 11, 27, 17, tzinfo=US_EASTERN)) == date(2026, 11, 25)  # 感謝祭の翌日
    assert dg.previous_business_day(datetime(2026, 11, 18, 17, tzinfo=US_EASTERN)) == date(2026, 11, 17)


def test_eight_k_on_target_date():
    sub = {"filings": {"recent": {
        "form": ["4", "8-K", "8-K", "10-Q"],
        "filingDate": ["2026-11-20", "2026-11-20", "2026-11-19", "2026-11-20"],
        "accessionNumber": ["a", "0000320193-26-000111", "0000320193-26-000100", "b"],
        "primaryDocument": ["x.xml", "ev.htm", "old.htm", "q.htm"],
        "items": ["", "2.02,9.01", "8.01", ""],
    }}}
    ks = dg.eight_k_on(sub, "0000320193", D)
    assert ks == [{"form": "8-K", "items": ["2.02", "9.01"],
                   "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000111/ev.htm"}]
    assert dg._eight_k_line(ks[0]) == "8-K: Item 2.02 業績・財務状況（決算）、Item 9.01 財務諸表・添付資料"


def test_attach_8k_survives_network_errors(monkeypatch):
    monkeypatch.setattr(dg.time, "sleep", lambda s: None)
    picks = _top([_row(1, "AAA", 100_000), _row(2, "BBB", 50_000, cik=None)])

    def boom(cik):
        raise dg.urllib.error.URLError("down")

    assert dg.attach_8k(picks, D, fetch=boom) == ["AAA", "BBB"]
    assert all(p.eight_k == [] for p in picks)


# ---------------------------------------------------------------- 文面
def _digest(unsubscribe="https://unsub.example/x", picks=None):
    picks = picks or _top([
        _row(1, "ABC", 1_234_567, insider="Alice <b>", position="CEO & Director", company="ABC & Co <Corp>"),
        _row(2, "XYZ", 500_000, insider="Bob", position="10% Owner"),
    ])
    picks[0].eight_k = [{"form": "8-K", "items": ["2.02"], "url": "https://www.sec.gov/Archives/edgar/data/1/2/ev.htm"}]
    return dg.build_digest(picks, D, datetime(2026, 11, 21, 13, 5, tzinfo=dg.JST), CFG, unsubscribe)


def test_subject_and_summary():
    d = _digest()
    assert d.subject == "昨夜のインサイダー大口買い Top5（11/20 提出分）"
    assert d.text.splitlines()[2].startswith("2026-11-20（米国東部）に SEC EDGAR へ提出された")


@pytest.mark.parametrize("unsubscribe", ["https://unsub.example/x", "{{ unsubscribe_url }}", ""])
def test_required_notices_are_always_present(unsubscribe):
    d = _digest(unsubscribe)
    for body in (d.text, d.html):
        assert "投資助言ではなく" in body and "一般的な情報提供" in body
        assert "出典: U.S. SEC EDGAR" in body and "取得時点: 2026-11-21 13:05 JST" in body
        assert "配信停止" in body
        assert "SEC による承認・提携もありません" in body
        assert "送信者テスト" in body and "contact-test" in body
    if unsubscribe:
        assert unsubscribe in d.text and unsubscribe in d.html


def test_no_banned_terms_in_output():
    d = _digest()
    assert dg.banned_terms_in(d.subject, d.text, d.html) == []
    assert dg.banned_terms_in("今が買い時です") == ["買い時", "今が買"]


def test_facts_and_links_in_output():
    d = _digest()
    for body in (d.text, d.html):
        assert "ABC" in body and "$1,234,567" in body and "123,457 株" in body and "$10.00" in body
        assert "0000000001-26-000001" in body  # 原典の受付番号
        assert "https://dash.example/whale-eye?ticker=ABC" in body
        assert "Item 2.02 業績・財務状況（決算）" in body
    assert "Alice <b>（CEO & Director）" in d.text


def test_html_escapes_values():
    h = _digest().html
    assert "<b>" not in h and "Alice &lt;b&gt;" in h and "ABC &amp; Co &lt;Corp&gt;" in h
    assert "<script" not in h.lower()


def test_sender_placeholders_when_not_configured():
    picks = _top([_row(1, "ABC", 100_000)])
    d = dg.build_digest(picks, D, None, dg.DigestConfig(), "")
    assert "送信者: （未設定）" in d.text and "取得時点: 不明" in d.text
    assert "ダッシュボード" not in d.text
    assert "このメールに「配信停止」と返信" in d.text


def test_config_from_env_and_plain_dashboard_url():
    c = dg.DigestConfig.from_env({"DIGEST_SENDER_NAME": " n ", "DIGEST_DASHBOARD_URL": "https://d.example/"})
    assert c.sender_name == "n" and c.dashboard_link("ABC") == "https://d.example/"


# ---------------------------------------------------------------- 配信
def test_send_is_dry_run_without_key(tmp_path):
    d = _digest()
    calls = []
    r = dg.send_digest(d, str(tmp_path), env={}, post=lambda *a: calls.append(a))
    assert r.mode == "dry-run" and calls == []
    assert (tmp_path / "digest.html").read_text(encoding="utf-8") == d.html
    assert (tmp_path / "digest.txt").read_text(encoding="utf-8") == d.text


def test_send_dry_run_flag_wins_over_key(tmp_path):
    calls = []
    r = dg.send_digest(_digest(), str(tmp_path), env={"BUTTONDOWN_API_KEY": "k"}, dry_run=True,
                       post=lambda *a: calls.append(a))
    assert r.mode == "dry-run" and calls == []


def test_send_via_buttondown_with_key(tmp_path):
    d = _digest()
    calls = []

    def post(url, payload, headers):
        calls.append((url, payload, headers))
        return {"id": "em_1"}

    r = dg.send_digest(d, str(tmp_path), env={"BUTTONDOWN_API_KEY": "secret-key"}, post=post)
    assert r.mode == "buttondown" and "em_1" in r.detail and "secret-key" not in r.detail
    url, payload, headers = calls[0]
    assert url == "https://api.buttondown.com/v1/emails"
    assert headers["Authorization"] == "Token secret-key"
    assert payload["subject"] == d.subject and d.html in payload["body"]


def test_main_skips_empty_day(tmp_path, monkeypatch):
    import sqlite3

    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE insider_trades (id INTEGER, filing_date TEXT, insider TEXT, position TEXT, ticker TEXT,"
                 " company TEXT, cik TEXT, avg_price REAL, buy_date TEXT, total_shares REAL, total_value REAL, filing_url TEXT)")
    conn.commit()
    conn.close()
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert dg.main(["--db", str(db), "--date", "2026-11-21", "--out", str(tmp_path / "o"), "--no-8k", "--no-resolve-links"]) == 0
    assert "status=skipped" in out.read_text()
    assert not (tmp_path / "o").exists()


# ---------------------------------------------------------------- 鮮度（送る直前の取り込み）
def _status(fetched="2026-11-23T21:32:00Z", **kw):
    return {"mode": "current", "feed_fetched_at": fetched, "stopped_by_budget": False, "error": None, **kw}


def test_fresh_ingest_targets_today_with_cutoff():
    f = dg.resolve_freshness(_status(), True, "unused.db", None)
    assert f.kind == "fresh" and f.target == date(2026, 11, 23)  # 米国東部 11/23（月）16:32
    note = f.note()
    assert "米国東部 11/23 16:32 までの提出分" in note and "日本時間 06:32" in note
    assert "それより後の提出は含みません" in note


def test_partial_ingest_says_some_may_be_missing():
    f = dg.resolve_freshness(_status(stopped_by_budget=True), True, "unused.db", None)
    assert f.kind == "partial" and f.target == date(2026, 11, 23)
    assert "一部が含まれていない可能性" in f.note()


def test_fresh_ingest_on_us_holiday_is_skipped():
    f = dg.resolve_freshness(_status("2026-11-26T21:30:00Z"), True, "unused.db", None)  # 感謝祭
    assert f.target is None


def _db(path, dates):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE insider_trades (id INTEGER, filing_date TEXT, insider TEXT, position TEXT, ticker TEXT,"
                 " company TEXT, cik TEXT, avg_price REAL, buy_date TEXT, total_shares REAL, total_value REAL, filing_url TEXT)")
    for i, (d, tk, v) in enumerate(dates, 1):
        conn.execute("INSERT INTO insider_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (i, d, "Jane Doe", "Director", tk, f"{tk} Inc.", "0000320193", 10.0, d, v / 10.0, v,
                      f"https://www.sec.gov/Archives/edgar/data/1/0000000001-26-{i:06d}-index.html"))
    conn.commit()
    conn.close()
    return str(path)


def test_failed_ingest_falls_back_to_latest_committed_day(tmp_path):
    db = _db(tmp_path / "c.db", [("2026-11-19", "OLD", 100_000), ("2026-11-20", "NEW", 200_000)])
    committed = datetime(2026, 11, 22, 13, 20, tzinfo=dg.JST)
    f = dg.resolve_freshness(None, True, db, committed, now=datetime(2026, 11, 23, 16, 30, tzinfo=US_EASTERN))
    assert f.kind == "fallback" and f.target == date(2026, 11, 20)
    assert f.note().startswith("【遅れ】") and "日本時間 11/22 13:20" in f.note()
    assert "最新の提出分は含まれていません" in f.note()


def test_without_ingest_uses_previous_business_day():
    f = dg.resolve_freshness(None, False, "unused.db", None, now=datetime(2026, 11, 23, 16, 30, tzinfo=US_EASTERN))
    assert f.kind == "manual" and f.target == date(2026, 11, 20) and f.note() == ""


def test_read_ingest_status(tmp_path):
    import json

    assert dg.read_ingest_status(str(tmp_path / "missing.json")) is None  # 取り込みが強制終了した
    assert dg.read_ingest_status(None) is None
    p = tmp_path / "s.json"
    p.write_text("{broken", encoding="utf-8")
    assert dg.read_ingest_status(str(p)) is None
    p.write_text(json.dumps(_status(error="HTTPError: 503")), encoding="utf-8")
    assert dg.read_ingest_status(str(p)) is None
    p.write_text(json.dumps(_status(feed_fetched_at=None)), encoding="utf-8")
    assert dg.read_ingest_status(str(p)) is None
    p.write_text(json.dumps(_status()), encoding="utf-8")
    assert dg.read_ingest_status(str(p))["feed_fetched_at"] == "2026-11-23T21:32:00Z"


def test_freshness_note_is_in_text_and_html():
    picks = _top([_row(1, "ABC", 100_000)])
    note = dg.resolve_freshness(_status(), True, "unused.db", None).note()
    d = dg.build_digest(picks, D, None, CFG, "", note)
    assert d.text.splitlines()[3] == note  # 冒頭の要約のすぐ下
    assert "米国東部 11/23 16:32 までの提出分" in d.html
    assert dg.banned_terms_in(d.text, d.html) == []
    late = dg.build_digest(picks, D, None, CFG, "", "【遅れ】テスト")
    assert "#FEF3C7" in late.html and "【遅れ】テスト" in late.text


def _run_main(tmp_path, monkeypatch, status, rows_fresh, rows_committed):
    import json

    fresh_db = _db(tmp_path / "insider.db", rows_fresh)
    committed_db = _db(tmp_path / "committed.db", rows_committed)
    st_path = tmp_path / "status.json"
    if status is not None:
        st_path.write_text(json.dumps(status), encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_out"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("BUTTONDOWN_API_KEY", raising=False)
    out = tmp_path / "o"
    rc = dg.main(["--db", fresh_db, "--fallback-db", committed_db, "--ingest-status", str(st_path),
                  "--out", str(out), "--no-8k", "--no-resolve-links"])
    return rc, (tmp_path / "gh_out").read_text(), out


def test_main_fresh_uses_ingested_today(tmp_path, monkeypatch):
    rows = [("2026-11-20", "OLD", 900_000), ("2026-11-23", "TOD", 100_000)]
    rc, gh, out = _run_main(tmp_path, monkeypatch, _status(), rows, rows[:1])
    assert rc == 0 and "freshness=fresh" in gh and "target_date=2026-11-23" in gh
    text = (out / "digest.txt").read_text(encoding="utf-8")
    assert "TOD" in text and "OLD" not in text and "米国東部 11/23 16:32 までの提出分" in text
    assert (out / "subject.txt").read_text(encoding="utf-8").strip() == "昨夜のインサイダー大口買い Top5（11/23 提出分）"


def test_main_failed_ingest_uses_committed_db_and_says_late(tmp_path, monkeypatch):
    monkeypatch.setattr(dg, "datetime", type("FakeDT", (datetime,), {
        "now": classmethod(lambda cls, tz=None: datetime(2026, 11, 23, 16, 45, tzinfo=tz))}))
    # 取り込みが途中で落ちて作業コピーに当日分が半端に入っていても、取り込み前の写しで作る
    rc, gh, out = _run_main(tmp_path, monkeypatch, None,
                            [("2026-11-20", "OLD", 900_000), ("2026-11-23", "HALF", 50_000)],
                            [("2026-11-20", "OLD", 900_000)])
    assert rc == 0 and "freshness=fallback" in gh and "target_date=2026-11-20" in gh
    text = (out / "digest.txt").read_text(encoding="utf-8")
    assert "【遅れ】" in text and "OLD" in text and "HALF" not in text
