"""ページの途中で描画を終えるための仕組み。

st.stop() はスクリプト全体を止めるため、入口（streamlit_app.py）が各ページの後に出す
出典・免責のフッターまで消えてしまう。ページ側は st.stop() の代わりに end_page() を呼ぶ。
streamlit_app.py が EndPage を受け止めて、フッターを出してから終える。
"""


class EndPage(Exception):
    """ページの描画をここで終える（エラーではない）。"""


def end_page() -> None:
    raise EndPage
