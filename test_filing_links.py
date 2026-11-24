"""filing_links（Form 4 の原典リンクを一度だけ解決して保存）のテスト。実行: pytest test_filing_links.py

SEC には問い合わせない（取得は偽物に差し替える）。
"""
import json
import sqlite3
import time

import pytest

import filing_links as fl

ACC = "0001193125-26-473131"
ISSUER, OWNER = 1341235, 1579179
XSL = f"https://www.sec.gov/Archives/edgar/data/{ISSUER}/000119312526473131/xslF345X05/ownership.xml"


def _txt(*docs):
    body = "".join(f"<DOCUMENT>\n<TYPE>{t}\n<SEQUENCE>1\n<FILENAME>{n}\n<TEXT>\n...\n</TEXT>\n</DOCUMENT>\n" for t, n in docs)
    return f"<SEC-DOCUMENT>\n{body}</SEC-DOCUMENT>\n".encode()


class FakeSec:
    """URL → (状態, 本文)。呼ばれた URL を覚える。"""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return self.pages.get(url, (404, b""))


# ---------------------------------------------------------------- URL・XML 名
def test_urls():
    assert fl.browse_url("0001341235") == ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1341235"
                                           "&type=4&dateb=&owner=include&count=40")
    assert fl.browse_url(None) is None and fl.browse_url("x") is None and fl.browse_url(0) is None
    assert fl.txt_url("0001341235", ACC) == f"https://www.sec.gov/Archives/edgar/data/{ISSUER}/000119312526473131/{ACC}.txt"
    assert fl.xsl_url(ISSUER, ACC, "ownership.xml") == XSL
    assert fl.folder_cik(f"https://www.sec.gov/Archives/edgar/data/{OWNER}/{ACC}-index.html") == OWNER
    assert fl.folder_cik(None) is None


def test_link_for():
    links = {ACC: XSL}
    assert fl.link_for(ACC, ISSUER, links) == XSL
    assert fl.link_for("0000000000-26-000001", ISSUER, links) == fl.browse_url(ISSUER)   # 未解決は Form 4 一覧
    assert fl.link_for(None, None, links, fallback="orig") == "orig"                    # CIK も無ければ元のまま
    assert fl.is_resolved_link(XSL) and not fl.is_resolved_link(fl.browse_url(ISSUER))


def test_xml_name_from_txt():
    assert fl.xml_name_from_txt(_txt(("4", "wk-form4_1.xml")).decode()) == "wk-form4_1.xml"
    # Form 4 本体の XML を選ぶ（添付の XML・画像より）
    assert fl.xml_name_from_txt(_txt(("EX-99", "exhibit.xml"), ("4/A", "form4a.xml")).decode()) == "form4a.xml"
    assert fl.xml_name_from_txt(_txt(("EX-99", "only.xml")).decode()) == "only.xml"
    assert fl.xml_name_from_txt(_txt(("4", "doc.htm")).decode()) is None
    assert fl.xml_name_from_txt("") is None


# ---------------------------------------------------------------- 解決
def test_resolve_from_issuer_folder_with_two_requests():
    sec = FakeSec({fl.txt_url(ISSUER, ACC): (200, _txt(("4", "ownership.xml"))), XSL: (200, b"<html>")})
    assert fl.resolve(ACC, ISSUER, OWNER, get=sec) == XSL
    assert len(sec.calls) == 2   # .txt と表示用 HTML の確認だけ


def test_resolve_falls_back_to_owner_folder_and_older_xsl():
    owner_xsl = fl.xsl_url(OWNER, ACC, "f.xml", "xslF345X03")
    sec = FakeSec({fl.txt_url(OWNER, ACC): (200, _txt(("4", "f.xml"))), owner_xsl: (200, b"<html>")})
    assert fl.resolve(ACC, ISSUER, OWNER, get=sec) == owner_xsl
    assert sec.calls[0] == fl.txt_url(ISSUER, ACC)   # 発行体を先に試す


def test_resolve_returns_none_when_nothing_opens():
    assert fl.resolve(ACC, ISSUER, OWNER, get=FakeSec({})) is None
    sec = FakeSec({fl.txt_url(ISSUER, ACC): (200, _txt(("4", "ownership.xml")))})  # 表示用 HTML が開かない
    assert fl.resolve(ACC, ISSUER, None, get=sec) is None


def test_sec_getter_keeps_under_10_per_second_and_sends_user_agent(monkeypatch):
    seen = []

    class Resp:
        status = 200

        def read(self):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen.append((time.monotonic(), req.get_header("User-agent")))
        return Resp()

    monkeypatch.setattr(fl.urllib.request, "urlopen", fake_urlopen)
    get = fl.SecGetter(user_agent="Test Agent test@example.com")
    for _ in range(11):
        assert get("https://www.sec.gov/x") == (200, b"ok")
    assert seen[-1][0] - seen[0][0] >= 1.0          # 11件に1秒以上 = 毎秒10件未満
    assert {ua for _, ua in seen} == {"Test Agent test@example.com"}


# ---------------------------------------------------------------- 保存・まとめて解決（再開）
def _db(tmp_path, rows):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE insider_trades (id INTEGER, filing_date TEXT, cik TEXT, filing_url TEXT)")
    conn.executemany("INSERT INTO insider_trades VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return str(db)


def _acc(i):
    return f"0000000001-26-{i:06d}"


def _rows(n):
    # 新しい提出日ほど番号が大きい。内部者のフォルダの URL（DB の形）
    return [(i, f"2026-11-{i:02d}", "0000320193", f"https://www.sec.gov/Archives/edgar/data/9{i}/{_acc(i)}-index.html")
            for i in range(1, n + 1)]


def _resolver_sec(ok=lambda i: True):
    pages = {}
    for i in range(1, 30):
        pages[fl.txt_url(320193, _acc(i))] = (200, _txt(("4", "f.xml")))
        if ok(i):
            pages[fl.xsl_url(320193, _acc(i), "f.xml")] = (200, b"<html>")
    return FakeSec(pages)


def test_store_roundtrip_and_broken_file(tmp_path):
    path = tmp_path / "l.json"
    assert fl.load_store(str(path)) == {"links": {}, "unresolved": {}}
    fl.save_store({"links": {ACC: XSL}, "unresolved": {"x": 1}}, str(path))
    assert fl.load_store(str(path)) == {"links": {ACC: XSL}, "unresolved": {"x": 1}}
    assert fl.load_links(str(path)) == {ACC: XSL}
    path.write_text("{broken", encoding="utf-8")
    assert fl.load_store(str(path)) == {"links": {}, "unresolved": {}}


def test_resolve_pending_newest_first_and_resumes(tmp_path):
    db, path = _db(tmp_path, _rows(5)), str(tmp_path / "l.json")
    sec = _resolver_sec()
    r = fl.resolve_pending(db, path, get=sec, limit=2, log=lambda *_: None)
    assert r["resolved"] == 2
    assert set(fl.load_store(path)["links"]) == {_acc(5), _acc(4)}   # 新しい提出日から
    sec.calls.clear()
    r = fl.resolve_pending(db, path, get=sec, log=lambda *_: None)   # 続きから（解決済みは問い合わせない）
    assert r["pending"] == 3 and r["resolved"] == 3
    assert not any(_acc(5) in c or _acc(4) in c for c in sec.calls)
    assert fl.load_store(path)["links"][_acc(1)] == fl.xsl_url(320193, _acc(1), "f.xml")


def test_resolve_pending_stops_at_deadline_and_keeps_progress(tmp_path):
    db, path = _db(tmp_path, _rows(5)), str(tmp_path / "l.json")
    sec = _resolver_sec()
    calls = {"n": 0}
    real = sec.__call__

    def slow(url):
        calls["n"] += 1
        return real(url)

    deadline = time.time() + 3600
    r = fl.resolve_pending(db, path, get=slow, deadline=time.time() - 1, log=lambda *_: None)
    assert r["stopped_by_budget"] and r["resolved"] == 0 and calls["n"] == 0
    r = fl.resolve_pending(db, path, get=slow, deadline=deadline, limit=1, log=lambda *_: None)
    assert r["resolved"] == 1 and r["remaining"] == 0
    assert len(fl.load_store(path)["links"]) == 1


def test_unresolved_is_counted_and_given_up_after_max_attempts(tmp_path):
    db, path = _db(tmp_path, _rows(2)), str(tmp_path / "l.json")
    sec = _resolver_sec(ok=lambda i: i != 1)
    for _ in range(fl.MAX_ATTEMPTS):
        fl.resolve_pending(db, path, get=sec, log=lambda *_: None)
    store = fl.load_store(path)
    assert store["unresolved"] == {_acc(1): fl.MAX_ATTEMPTS} and _acc(2) in store["links"]
    sec.calls.clear()
    r = fl.resolve_pending(db, path, get=sec, log=lambda *_: None)
    assert r["pending"] == 0 and sec.calls == []   # もう試さない（表示は Form 4 一覧）


def test_db_is_read_only(tmp_path):
    db = _db(tmp_path, _rows(1))
    before = open(db, "rb").read()
    fl.resolve_pending(db, str(tmp_path / "l.json"), get=_resolver_sec(), log=lambda *_: None)
    assert open(db, "rb").read() == before


def test_main_writes_summary(tmp_path, monkeypatch):
    db, path = _db(tmp_path, _rows(1)), str(tmp_path / "l.json")
    monkeypatch.setattr(fl, "SecGetter", lambda *a, **k: _resolver_sec())
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert fl.main(["--db", db, "--out", path, "--max-minutes", "5"]) == 0
    assert "今回の解決: **1** 件" in summary.read_text(encoding="utf-8")
    assert json.loads(open(path, encoding="utf-8").read())["links"]


def test_repo_links_file_is_valid():
    # auto_update.yml が git add するため、リポジトリに必ず置いておく
    store = json.load(open(fl.LINKS_PATH, encoding="utf-8"))
    assert set(store) == {"links", "unresolved"}
    assert all(fl.is_resolved_link(u) for u in store["links"].values())
