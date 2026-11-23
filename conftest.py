"""テスト共通: 手元の .streamlit/secrets.toml（本物の招待コードなど）をテストに持ち込まない。

AppTest は at.secrets が空だと st.secrets（= 手元の secrets.toml）を使うため、ゲートが有効になってしまう。
各テストは空の secrets から始め、必要なテストだけ at.secrets に値を入れる。
"""
import pytest
import streamlit as st
from streamlit.runtime.secrets import Secrets


@pytest.fixture(autouse=True)
def empty_secrets(monkeypatch):
    s = Secrets()
    s._secrets = {}
    monkeypatch.setattr(st, "secrets", s)
