# Whale-Eye：米国株インサイダー＆オプション分析ダッシュボード

米国株の**インサイダー（会社役員・大株主）による株式売買**と、株価・テクニカル指標・オプション市場の動きを1つの画面で追うための Streamlit アプリです。
「大口（クジラ）が何を買っているか」を毎日確かめ、銘柄ごとに深掘りできます。

## 見られる画面

アプリは3ページ構成で、画面上部のナビゲーションで切り替えます（画面が狭い時は左上の `»` から開くメニューに入ります）。

| ページ | 見られること |
|---|---|
| 🐋 **Whale-Eye：オプション＆インサイダー**（最初に開く画面） | 全銘柄スクリーナー（インサイダーのネット買い越し額など）、選んだ銘柄の株価・テクニカル分析チャート、オプションチェーン、ボラティリティ・スキュー、相場診断ガイド、推奨オプション戦略と損益図 |
| 📈 **Insider Trading Workstation Pro** | セクター別スライサー、絞り込みと連動する銘柄マトリックス（購入額・取引件数・EDGARへのリンク）、銘柄ごとの株価分析 |
| 📊 **Daily Compare（Form4×騰落率×8-K）** | Form 4 の提出日を 0% とした提出後の騰落率の推移、日次ヒートマップ、銘柄詳細（株価・RSI・出来高に速報 8-K を重ねて表示） |

## データ源と更新頻度

- **インサイダー取引**：米国証券取引委員会（SEC）の EDGAR に提出される **Form 4**。[edgartools](https://github.com/dgunning/edgartools) で取得し、リポジトリ内の `insider.db`（SQLite）に保存しています。1件の書類あたりの購入総額が 10万ドル以上のものを収集対象にしています。
- **速報（8-K）**：SEC EDGAR の **8-K** を、Daily Compare ページで表示する時に取得します（SECに接続できない環境では表示を省略します）。
- **株価・テクニカル指標・オプション**：[yfinance](https://github.com/ranaroussi/yfinance)（Yahoo Finance）から画面を開いた時に取得します。

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

### テスト

```bash
pip install pytest
pytest test_compare_logic.py
```

## ファイル構成

| ファイル | 役割 |
|---|---|
| `streamlit_app.py` | 入口。ページ設定・共通スタイル・ナビゲーション |
| `app.py` / `app_bi_dashboard.py` / `app_compare_dashboard.py` | 各ページ |
| `data_loader.py` / `charts.py` / `guide_renderer.py` / `compare_logic.py` | データ読み込み・チャート描画・ガイド表示・比較計算 |
| `a5_backfill_v3.py` | SEC EDGAR から Form 4 を取り込み `insider.db` を更新するスクリプト（GitHub Actions から実行） |
| `insider.db` | インサイダー取引データ（自動更新。手で編集しないでください） |

## 免責事項

本アプリは情報提供を目的としたものであり、**投資助言ではありません**。表示されるデータ・指標・戦略例の正確性や完全性は保証されません。データには取得元の誤りや遅延、取り込み時の誤りが含まれる場合があります。投資判断はご自身の責任で、必要に応じて一次情報（SEC EDGAR 等）を確認のうえ行ってください。
