"""Public instrument names; finding a page never confirms account eligibility."""
CATALOG = {
    "SOXL": ("Direxion Daily Semiconductor Bull 3X ETF", "https://www.binance.com/en/stocks/EQ_SOXL"),
    "XSD": ("State Street SPDR S&P Semiconductor ETF", "https://www.binance.com/en/stocks/EQ_XSD"),
    "SMH": ("VanEck Semiconductor ETF", "https://www.binance.com/en/stocks/EQ_SMH"),
    "SOXX": ("iShares Semiconductor ETF", "https://www.binance.com/en/stocks/EQ_SOXX"),
    "QQQ": ("Invesco QQQ Trust, Series 1", "https://www.binance.com/en/stocks/EQ_QQQ"),
    "TQQQ": ("ProShares UltraPro QQQ", "https://www.binance.com/en/stocks/EQ_TQQQ"),
    "SPY": ("State Street SPDR S&P 500 ETF Trust", "https://www.binance.com/en/stocks/EQ_SPY"),
    "RSP": ("Invesco S&P 500 Equal Weight ETF", "https://www.invesco.com/us/financial-products/etfs/product-detail?productId=RSP"),
}
CHECKED = "2026-10-05"


def name(symbol):
    return CATALOG.get(symbol, (symbol, ""))[0]


def render(symbols):
    import streamlit as st
    st.caption("产品全名来自公开页面（核对日：" + CHECKED + "）；名称不用于行情下载，账户可买卖状态仍以你的设置为准。RSP仅找到发行方名称，尚未确认币安对应产品。")
    for symbol in dict.fromkeys(symbols):
        if symbol in CATALOG:
            full, url = CATALOG[symbol]
            label = "发行方资料" if symbol == "RSP" else "币安股票页面"
            st.markdown(f"**{symbol}** · {full} · [{label}]({url})")
