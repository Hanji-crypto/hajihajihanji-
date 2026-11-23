"""Whale-Eye の唯一の入口（Streamlit マルチページアプリ）。

起動: streamlit run streamlit_app.py

各画面は既存のスクリプトをそのままページとして読み込む。
st.set_page_config はここで1回だけ呼び、各ページ側では呼ばない。
"""
import streamlit as st

from data_status import render_page_header

st.set_page_config(
    page_title="Whale-Eye",
    page_icon="🐋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 全ページ共通: 上部ナビゲーションのヘッダーを各画面のダーク背景になじませる。
# 画面ごとの配色・カードなどのCSSは、見た目を変えないよう各ページ側に残している。
st.html(
    """
    <style>
    [data-testid="stHeader"] { background-color: #0B0F19; }
    [data-testid="stHeader"] a, [data-testid="stHeader"] span { color: #E2E8F0 !important; }
    /* 画面幅が狭いとナビはサイドバーに入る。各ページのCSSが文字を白にするため背景もダークにそろえる */
    [data-testid="stSidebar"] { background-color: #111827; border-right: 1px solid #1F2937; }
    [data-testid="stSidebar"] a, [data-testid="stSidebar"] span { color: #E2E8F0 !important; }
    </style>
    """
)

pages = [
    st.Page(
        "app.py",
        title="Whale-Eye: オプション＆インサイダー",
        icon="🐋",
        url_path="whale-eye",
        default=True,
    ),
    st.Page(
        "app_bi_dashboard.py",
        title="Insider Trading Workstation Pro",
        icon="📈",
        url_path="workstation",
    ),
    st.Page(
        "app_compare_dashboard.py",
        title="Daily Compare（Form4×騰落率×8-K）",
        icon="📊",
        url_path="compare",
    ),
]

nav = st.navigation(pages, position="top")
# 全ページ共通: データの最新提出日・最終更新時刻・古さの警告・品質チェック・免責
render_page_header("insider.db")
nav.run()
