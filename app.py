"""Portfolio Decision Tool — Streamlit frontend (skeleton)."""
import streamlit as st
import pandas as pd

from data import TICKERS, load_universe

st.set_page_config(page_title="Portfolio Decision Tool", layout="wide")
st.title("Portfolio Decision Tool")
st.caption("Stress-test capital allocations against real historical data.")

prices = load_universe()

with st.sidebar:
    st.header("Data")
    st.write(f"**Tickers loaded:** {len(prices.columns)}")
    st.write(f"**Date range:** {prices.index.min().date()} → {prices.index.max().date()}")
    st.write(f"**Trading days:** {len(prices):,}")

st.subheader("Available tickers")
st.dataframe(
    pd.DataFrame(
        [(t, name) for t, name in TICKERS.items()],
        columns=["Ticker", "Description"],
    ),
    hide_index=True,
    use_container_width=True,
)

st.subheader("Price history (last 250 days)")
st.line_chart(prices.tail(250))
