# Whale-Eye：米国株インサイダー分析ダッシュボード

米国株の**インサイダー（会社役員・大株主）による株式売買**と、株価・テクニカル指標・オプション市場の動きを1つの画面で追うための Streamlit アプリです。
「大口（クジラ）が何を買っているか」を毎日確かめ、銘柄ごとに深掘りできます。

> **招待制ベータは SEC EDGAR のみです。** ベータでは SEC EDGAR の公式開示（Form 4・8-K・企業の SIC 業種）だけを使い、Yahoo Finance（yfinance）の株価・オプション・企業属性は表示しません（下の「データモード」）。株価・オプションの画面は、ローカル開発（`full` モード）でだけ動きます。

## 見られる画面

アプリは3ページ構成で、画面上部のナビゲーションで切り替えます（画面が狭い時は左上の `»` から開くメニューに入ります）。

| ページ | 見られること |
|---|---|
| 🐋 **Whale-Eye：オプション＆インサイダー**（最初に開く画面） | 全銘柄スクリーナー（インサイダーのネット買い越し額など）、選んだ銘柄の株価・テクニカル分析チャート、オプションチェーン、ボラティリティ・スキュー、相場診断ガイド、推奨オプション戦略と損益図 |
| 📈 **Insider Trading Workstation Pro** | セクター別スライサー、絞り込みと連動する銘柄マトリックス（購入額・取引件数・EDGARへのリンク）、銘柄ごとの株価分析 |
| 📊 **Daily Compare（Form4×騰落率×8-K）** | Form 4 の提出日を 0% とした提出後の騰落率の推移、日次ヒートマップ、銘柄詳細（株価・RSI・出来高に速報 8-K を重ねて表示） |

上の表は `full` モードの画面です。招待制ベータ（`edgar_only` モード）では、各ページから株価に依存する部品を外します。

| ページ（edgar_only での名前） | 残るもの | 外すもの |
|---|---|---|
| 🐋 **Whale-Eye：インサイダー** | 全銘柄スクリーナー（ネット買い越し額・平均取得単価など）、選んだ銘柄の Form 4 取引一覧（提出日・取引日・内部者・役職・株数・取得単価・金額・書類リンク） | 株価・テクニカル分析チャート、オプションチェーン、IV/HV・ボラティリティ・スキュー、相場診断ガイド、推奨オプション戦略と損益図 |
| 📈 **Insider Trading Workstation Pro** | 業種スライサー（SEC の SIC 大分類）、銘柄マトリックス（購入額・取引件数・平均取得単価・業種・EDGARリンク）、選んだ銘柄の Form 4 取引一覧と EDGAR の Form 4 一覧へのリンク | 1M/3M/6M リターン、株価チャート（ボリンジャーバンド・RSI）、Yahoo 由来のセクター、Finviz/TradingView へのリンク |
| 📊 **Daily Compare（Form4×8-K）** | 最新提出日・件数・購入額の KPI、購入額上位の Form 4 提出一覧、選んだ提出の前後 N 日の 8-K を時系列に並べた図と一覧（提出日からの日数つき） | 提出後の騰落率カーブ、平均騰落率・勝率、日次ヒートマップ、株価・RSI・出来高チャート |

Form 4 の「取得単価」「金額」は、Form 4 に書かれた内部者の取引価格で、市場の株価ではありません。

## データ源と更新頻度

- **インサイダー取引**：米国証券取引委員会（SEC）の EDGAR に提出される **Form 4**。[edgartools](https://github.com/dgunning/edgartools) で取得し、リポジトリ内の `insider.db`（SQLite）に保存しています。1件の書類あたりの購入総額が 10万ドル以上のものを収集対象にしています。
- **速報（8-K）**：SEC EDGAR の **8-K** を、Daily Compare ページで表示する時に取得します（SECに接続できない環境では表示を省略します）。
- **業種（SIC）**：`edgar_only` では、SEC の [Submissions API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)（`data.sec.gov`）から企業の SIC コード・業種名を取ります（購入額上位50社。CIK ごとに1週間キャッシュ）。SEC の利用ルールに合わせて User-Agent に名前と連絡先を付け、毎秒10リクエスト未満に抑えています（`sec_company.py`。secrets の `sec_user_agent` で変更可）。
- **株価・テクニカル指標・オプション・セクター**（`full` モードのみ）：[yfinance](https://github.com/ranaroussi/yfinance)（Yahoo Finance）から画面を開いた時に取得します。

**更新頻度**：GitHub Actions（`.github/workflows/auto_update.yml`）が**米国の平日の夜（日本時間 火〜土の 13:17 ごろ）に毎日** Form 4 を取り込み、`insider.db` を自動コミットします。アプリは最新のコミット時点の `insider.db` を読みます。株価・オプションは表示時点の値です（yfinance 側の遅延があります）。

## 起動方法

Python 3.12 を想定しています。

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

ブラウザで http://localhost:8501 が開きます。`streamlit_app.py` が唯一の入口で、3つの画面はその中のページとして動きます。
各画面のスクリプト（`app.py` / `app_bi_dashboard.py` / `app_compare_dashboard.py`）を単体で `streamlit run` する使い方はサポートしません（画面設定を入口でまとめて行っているため）。

Streamlit Community Cloud に公開する場合も、メインファイルに `streamlit_app.py` を指定します。

### 招待制ベータ（招待コードと同意画面）

secrets に `invite_codes`（文字列のリスト）を置くと、招待コードを入れた人だけが画面を見られます。入場後、セッションごとに1回「日本に住んでいる」「投資助言ではないことを理解した」の同意を求めます（`access_gate.py`）。

- 形は `.streamlit/secrets.toml.example` を参照。ローカルでは `.streamlit/secrets.toml` にコピーして値を入れます（git には入りません）。Streamlit Community Cloud ではアプリの Settings → Secrets に同じ形で貼ります。
- `invite_codes` が無い時（ローカル開発・CI）は、ゲートも同意画面も出ず、今まで通り表示されます。
- 招待コード自体は、ソースや README には書かないでください。推測されにくい長めのコードを使い、配るのをやめたコードは secrets から消します（消したコードで入っていた人は入口に戻ります）。
- ブラウザを再読み込みすると新しいセッションになり、もう一度コードと同意が必要です。

### データモード（`data_mode`）

どのデータ源を使うかは、secrets の `data_mode` で1か所で決めます（`data_mode.py`）。

| 値 | 使うデータ | 用途 |
|---|---|---|
| `edgar_only` | SEC EDGAR の開示だけ（Form 4・8-K・SIC）。yfinance は **import も呼び出しもしません** | 招待制ベータ |
| `full` | SEC EDGAR ＋ Yahoo Finance（yfinance）の株価・オプション・セクター | ローカル開発 |

- `data_mode` を書かない時の既定: 招待コードのゲートが有効（`invite_codes` がある）なら `edgar_only`、無ければ（ローカル開発・CI）`full`。
- 不正な値の時は `edgar_only`（株価を出さない側）になります。
- フッターの出典は、`edgar_only` では SEC EDGAR だけを書きます。
- ベータを EDGAR のみにしているのは、MVP の範囲（EDGAR のみ・株価なし）と、Yahoo Finance の利用条件（商用での再配信）への懸念のためです。株価は将来、正規に契約したデータで戻す可能性があります。
- `auto_update.yml` が使う取り込み（`a5_backfill_v3.py`）は edgartools だけで、yfinance は使いません。`a7_backtest.py`（手元で動かすバックテスト）は yfinance を使い、アプリからは呼ばれません。

### テスト

```bash
pip install pytest
pytest -q   # 単体テスト・招待ゲートと同意画面・3ページの起動スモークテスト（full と edgar_only）
```

## ファイル構成

| ファイル | 役割 |
|---|---|
| `streamlit_app.py` | 入口。ページ設定・共通スタイル・招待ゲート・ナビゲーション・共通のヘッダー/フッター |
| `access_gate.py` | 招待コードのゲートと初回の同意画面 |
| `data_mode.py` | データモード（`edgar_only` / `full`）の決定 |
| `sec_company.py` / `edgar_views.py` | SEC Submissions API の SIC 取得／EDGAR だけで成り立つ表示部品（Form 4 取引一覧） |
| `page_flow.py` | ページの途中で描画を終える仕組み（`st.stop()` だとフッターまで消えるため） |
| `data_status.py` / `data_quality.py` | データの鮮度・出典・免責の表示／誤データの除外・補正 |
| `app.py` / `app_bi_dashboard.py` / `app_compare_dashboard.py` | 各ページ |
| `data_loader.py` / `charts.py` / `guide_renderer.py` / `compare_logic.py` | データ読み込み・チャート描画・ガイド表示・比較計算 |
| `a5_backfill_v3.py` | SEC EDGAR から Form 4 を取り込み `insider.db` を更新するスクリプト（GitHub Actions から実行） |
| `deep_link.py` | メールからの深いリンク（`?ticker=`）でその銘柄を選んだ状態で開く |
| `digest.py` | 毎朝のメール「昨夜のインサイダー大口買い Top5」を作って配信（`.github/workflows/daily_digest.yml` から実行） |
| `insider.db` | インサイダー取引データ（自動更新。手で編集しないでください） |

## 毎朝のメール（インサイダー大口買い Top5）

`digest.py` が、米国東部の前営業日に提出された Form 4 の市場での買い（取引コード P）を `data_quality.py` の基準で除外・補正したうえで、1社あたりの合計金額の上位5社を日本語のメールにします。株価は使わず、事実（誰が・何株・いくらで・いつ・どの書類）と EDGAR の原典リンク、直近30日の買いの件数、同じ日の 8-K の項目だけを書きます。

```bash
python digest.py --dry-run                 # 前営業日の分を digest_out/ に HTML とテキストで書き出す（送らない）
python digest.py --date 2026-11-20 --dry-run --no-8k
```

GitHub Actions（`daily_digest.yml`）が日本時間の火〜土 06:30（米国東部の当日の夕方）に動きます。送る直前に、ワークフロー内の作業コピーの `insider.db` へ EDGAR の最新提出フィードから当日分を取り込み（取り込みスクリプトの `--daily --current`。12分で打ち切り、コミットはしない）、本文に「米国東部 X時 までの提出分」と締め時刻を書きます。取り込みが失敗した時は、取り込み前の `insider.db` の直近の提出日で作り、本文の冒頭に【遅れ】と書きます。

メール内のダッシュボードへのリンクは `?ticker=KNOP` の形で、開くとその銘柄を選んだ状態になります（招待コード・同意の画面を通った後も保持。`deep_link.py`）。

設定は Settings → Secrets and variables → Actions で行い、リポジトリには書きません。

| 種類 | 名前 | 内容 |
|---|---|---|
| secret | `BUTTONDOWN_API_KEY` | これがある時だけ Buttondown で送る。無ければ dry-run（実行サマリとアーティファクトに文面を残す） |
| secret | `SEC_USER_AGENT` | SEC へのアクセスに付ける「名前 連絡先」（任意） |
| variable | `DIGEST_SENDER_NAME` / `DIGEST_SENDER_CONTACT` | メール末尾の送信者の表示 |
| variable | `DIGEST_DASHBOARD_URL` | ダッシュボードの URL。`{ticker}` を含めると銘柄ごとに差し込む（例: `https://<アプリのURL>/?ticker={ticker}`） |
| variable | `DIGEST_UNSUBSCRIBE_URL` | 配信停止のページ（任意。Buttondown で送る時は無ければ Buttondown の停止リンク） |

対象日のデータが無い日（休場日など）は送りません。手動実行（workflow_dispatch）は既定で dry-run です。

## 出典の表記について

画面のフッターに出典と取得時点を出しています。`edgar_only`（ベータ）では「出典: U.S. SEC EDGAR（提出書類）」だけ、`full` では「出典: U.S. SEC EDGAR（提出書類）／株価: Yahoo Finance（yfinance 経由）」です。本アプリは個人が作った非公式のツールで、SEC・Yahoo とは関係がなく、承認・提携も受けていません。SEC のロゴは使いません。

## 免責事項

本アプリは情報提供を目的としたものであり、**投資助言ではありません**。表示されるデータ・指標・戦略例の正確性や完全性は保証されません。データには取得元の誤りや遅延、取り込み時の誤りが含まれる場合があります。投資判断はご自身の責任で、必要に応じて一次情報（SEC EDGAR 等）を確認のうえ行ってください。
