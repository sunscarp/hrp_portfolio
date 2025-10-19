import streamlit as st
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import yfinance as yf
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Import your existing functions (make sure these are in your project)
from hrp_functions import get_base_hrp_weights, regime_aware_hrp_with_drawdown, detect_regimes_hmm_responsive

# Page configuration
st.set_page_config(
    page_title="Portfolio App",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# Title and description
st.markdown('<h1 class="main-header">Portfolio App</h1>', unsafe_allow_html=True)
st.write("""
This app allows you to explore portfolio analytics and download market data.
""")

# Sidebar for inputs
st.sidebar.header("🔧 Configuration")

# Custom ticker input
st.sidebar.subheader("Custom Portfolio Tickers")
custom_tickers = st.sidebar.text_input(
    "Enter tickers (comma-separated):",
    value="SPY,QQQ,IWM,EEM,TLT,GLD"
)
# Parse tickers
selected_assets = [t.strip().upper() for t in custom_tickers.split(",") if t.strip()]

# Date range
st.sidebar.subheader("Date Range")
end_date = datetime.now()
start_date = end_date - timedelta(days=5*365)  # 5 years default

col1, col2 = st.sidebar.columns(2)
with col1:
    start_date = st.date_input("Start Date", start_date)
with col2:
    end_date = st.date_input("End Date", end_date)

# Max volatility input
st.sidebar.subheader("Max Volatility")
max_volatility = st.sidebar.number_input(
     "Set maximum annualized volatility (%)",
     min_value=1.0,
     max_value=100.0,
     value=20.0,
     step=0.5,
     help="Portfolio volatility will be constrained to this maximum (if supported by the algorithm)."
)
max_volatility = max_volatility / 100  # convert to decimal for calculations

# Option to allow cash (weights sum < 1)
allow_cash = st.sidebar.checkbox(
    "Allow cash (weights sum < 1)",
    value=True,
    help="If checked, portfolio can hold cash to meet volatility constraint. If unchecked, weights will be optimized to sum to 1."
)


# Use default defensive assets in code
defensive_assets = ["GLD", "TLT"]

@st.cache_data(ttl=3600)  # Cache for 1 hour
def download_data(tickers, start_date, end_date):
    """Download stock data from Yahoo Finance"""
    try:
        raw_data = yf.download(tickers, start=start_date, end=end_date)
        # Handle both 'Adj Close' and 'Close' columns (API changes)
        if 'Adj Close' in raw_data.columns:
            data = raw_data['Adj Close']
        elif 'Close' in raw_data.columns:
            data = raw_data['Close']
        else:
            st.error("Neither 'Adj Close' nor 'Close' column found. Possible reasons: wrong asset symbols, no data for date range, or Yahoo Finance API issue.")
            st.write("Downloaded columns:", raw_data.columns.tolist())
            return None
        returns = data.pct_change().dropna()
        return returns
    except Exception as e:
        st.error(f"Error downloading data: {e}")
        return None

def main():
    # Data download section
    st.header("📥 Data Download")
    if not selected_assets:
        st.warning("Please select at least one asset from the sidebar.")
        return
    with st.spinner("Downloading market data..."):
        returns = download_data(selected_assets, start_date, end_date)
    if returns is None or returns.empty:
        st.error("Failed to download data. Please check your asset symbols and date range.")
        return
    st.success(f"Downloaded data for {len(selected_assets)} assets from {start_date} to {end_date}")

    # Display data summary
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Period", f"{len(returns)} trading days")
    with col2:
        st.metric("Assets", len(selected_assets))
    with col3:
        st.metric("Date Range", f"{returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}")
    # Show returns statistics
    st.subheader("📊 Returns Statistics")
    st.dataframe(returns.describe())

    # ===============================
    # RUN HRP
    # ===============================
    with st.expander("🔗 HRP Portfolio (click to expand)", expanded=False):
        hrp_weights = get_base_hrp_weights(returns)
        corr = returns.corr()
        from scipy.cluster.hierarchy import linkage, dendrogram
        from scipy.spatial.distance import squareform
        dist = np.sqrt((1 - corr).clip(upper=1)) / 2
        link = linkage(squareform(dist), 'ward')
        import seaborn as sns

        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("**Correlation Heatmap**")
            fig1, ax1 = plt.subplots(figsize=(2.8, 2.2))
            sns.heatmap(corr, annot=True, cmap='coolwarm', ax=ax1, cbar=False)
            ax1.set_title("Correlation", fontsize=9)
            ax1.set_xlabel("")
            ax1.set_ylabel("")
            st.pyplot(fig1, use_container_width=True)
        with col2:
            st.markdown("**Dendrogram**")
            fig2, ax2 = plt.subplots(figsize=(2.8, 2.2))
            dendrogram(link, labels=returns.columns, leaf_rotation=90, ax=ax2)
            ax2.set_title("Dendrogram", fontsize=9)
            ax2.set_xlabel("")
            ax2.set_ylabel("")
            st.pyplot(fig2, use_container_width=True)
        with col3:
            st.markdown("**HRP Weights**")
            fig3, ax3 = plt.subplots(figsize=(2.2, 1.5))
            hrp_weights.plot(kind='bar', ax=ax3)
            ax3.set_title("Weights", fontsize=9)
            ax3.set_ylabel("")
            ax3.set_xlabel("")
            ax3.tick_params(axis='x', labelrotation=45, labelsize=7)
            ax3.tick_params(axis='y', labelsize=7)
            st.pyplot(fig3, use_container_width=True)

            # Calculate and show expected return and volatility for HRP
            mean_returns = returns.mean()
            cov_matrix = returns.cov()
            port_return = float((hrp_weights * mean_returns).sum()) * 252  # annualized
            port_vol = float(np.sqrt(np.dot(hrp_weights.values, np.dot(cov_matrix.values, hrp_weights.values)))) * np.sqrt(252)
        # Enforce max volatility constraint
        if port_vol > max_volatility and port_vol > 0:
            if allow_cash:
                scale = max_volatility / port_vol
                hrp_weights = hrp_weights * scale
                # Do NOT renormalize, allow sum(weights) < 1 (cash)
                port_return = float((hrp_weights * mean_returns).sum()) * 252
                port_vol = float(np.sqrt(np.dot(hrp_weights.values, np.dot(cov_matrix.values, hrp_weights.values)))) * np.sqrt(252)
                st.warning(f"Weights scaled down to meet max volatility constraint: {max_volatility:.2%}. Cash holding: {1-hrp_weights.sum():.2%}")
            else:
                # Optimization: minimize difference from HRP weights, subject to volatility <= max_volatility and sum(weights)=1
                from scipy.optimize import minimize
                def port_vol_func(w):
                    return np.sqrt(np.dot(w, np.dot(cov_matrix.values, w))) * np.sqrt(252)
                cons = [
                    {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
                    {'type': 'ineq', 'fun': lambda w: max_volatility - port_vol_func(w)}
                ]
                bounds = [(0, 1) for _ in hrp_weights]
                res = minimize(
                    lambda w: np.sum((w - hrp_weights.values) ** 2),
                    hrp_weights.values,
                    method='SLSQP',
                    bounds=bounds,
                    constraints=cons
                )
                if res.success:
                    hrp_weights = pd.Series(res.x, index=hrp_weights.index)
                    port_return = float((hrp_weights * mean_returns).sum()) * 252
                    port_vol = float(np.sqrt(np.dot(hrp_weights.values, np.dot(cov_matrix.values, hrp_weights.values)))) * np.sqrt(252)
                    st.warning(f"Weights optimized to meet max volatility constraint: {max_volatility:.2%} (no cash allowed)")
                else:
                    st.error("Optimization failed to meet volatility constraint. Showing original HRP weights.")
            st.info(f"**Expected Return:** {port_return:.2%}  |  **Volatility:** {port_vol:.2%}")

        st.success("\n✅ Final HRP Weights:")
        st.dataframe(hrp_weights)

    # ===============================
    # Regime-Aware HRP Section
    # ===============================
    with st.expander("🧠 Regime-Aware HRP (click to expand)", expanded=False):
        st.markdown("**Regime-Aware HRP Portfolio**")
        # Use regime_aware_hrp_with_drawdown (already imported)
        regime_result = regime_aware_hrp_with_drawdown(
            returns,
            detect_fn=detect_regimes_hmm_responsive,
            defensive_assets=defensive_assets,
            confidence_threshold=0.55,
            drawdown_control=True
        )
        regime_weights = regime_result.get('regime_weights', hrp_weights)
        final_weights = regime_result.get('final_weights', hrp_weights)

        # Determine regime label (if available)
        try:
            regimes = detect_regimes_hmm_responsive(returns)
            current_regime = regimes.iloc[-1] if len(regimes) > 0 else 'Unknown'
        except Exception:
            current_regime = 'Unknown'

        st.info(f"Current Regime: **{current_regime}**")

        # Show correlation heatmap and dendrogram for regime-aware HRP
        import seaborn as sns
        from scipy.cluster.hierarchy import linkage, dendrogram
        from scipy.spatial.distance import squareform
        corr_regime = returns.corr()
        dist_regime = np.sqrt((1 - corr_regime).clip(upper=1)) / 2
        link_regime = linkage(squareform(dist_regime), 'ward')

        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("**Correlation Heatmap**")
            fig1, ax1 = plt.subplots(figsize=(2.8, 2.2))
            sns.heatmap(corr_regime, annot=True, cmap='coolwarm', ax=ax1, cbar=False)
            ax1.set_title("Correlation", fontsize=9)
            ax1.set_xlabel("")
            ax1.set_ylabel("")
            st.pyplot(fig1, use_container_width=True)
        with col2:
            st.markdown("**Dendrogram**")
            fig2, ax2 = plt.subplots(figsize=(2.8, 2.2))
            dendrogram(link_regime, labels=returns.columns, leaf_rotation=90, ax=ax2)
            ax2.set_title("Dendrogram", fontsize=9)
            ax2.set_xlabel("")
            ax2.set_ylabel("")
            st.pyplot(fig2, use_container_width=True)
        with col3:
            st.markdown("**Base HRP Weights vs Regime-Aware Weights**")
            weights_df = pd.DataFrame({
                'Base HRP': regime_weights,
                'Regime-Aware': final_weights
            })
            weights_df = weights_df.fillna(0.0)
            fig3, ax3 = plt.subplots(figsize=(2.2, 1.5))
            weights_df.plot(kind='bar', ax=ax3, width=0.8)
            ax3.set_title("Base vs Regime-Aware Weights", fontsize=10)
            ax3.set_ylabel("Weight", fontsize=9)
            ax3.set_xlabel("")
            ax3.tick_params(axis='x', labelrotation=45, labelsize=8)
            ax3.tick_params(axis='y', labelsize=8)
            ax3.legend(fontsize=8)
            st.pyplot(fig3, use_container_width=True)

            # Calculate and show expected return and volatility for regime-aware portfolio
            mean_returns = returns.mean()
            cov_matrix = returns.cov()
            port_return = float((final_weights * mean_returns).sum()) * 252  # annualized
            port_vol = float(np.sqrt(np.dot(final_weights.values, np.dot(cov_matrix.values, final_weights.values)))) * np.sqrt(252)
        # Enforce max volatility constraint
        if port_vol > max_volatility and port_vol > 0:
            if allow_cash:
                scale = max_volatility / port_vol
                final_weights = final_weights * scale
                # Do NOT renormalize, allow sum(weights) < 1 (cash)
                port_return = float((final_weights * mean_returns).sum()) * 252
                port_vol = float(np.sqrt(np.dot(final_weights.values, np.dot(cov_matrix.values, final_weights.values)))) * np.sqrt(252)
                st.warning(f"Weights scaled down to meet max volatility constraint: {max_volatility:.2%}. Cash holding: {1-final_weights.sum():.2%}")
            else:
                # Optimization: minimize difference from regime-aware weights, subject to volatility <= max_volatility and sum(weights)=1
                from scipy.optimize import minimize
                def port_vol_func(w):
                    return np.sqrt(np.dot(w, np.dot(cov_matrix.values, w))) * np.sqrt(252)
                cons = [
                    {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
                    {'type': 'ineq', 'fun': lambda w: max_volatility - port_vol_func(w)}
                ]
                bounds = [(0, 1) for _ in final_weights]
                res = minimize(
                    lambda w: np.sum((w - final_weights.values) ** 2),
                    final_weights.values,
                    method='SLSQP',
                    bounds=bounds,
                    constraints=cons
                )
                if res.success:
                    final_weights = pd.Series(res.x, index=final_weights.index)
                    port_return = float((final_weights * mean_returns).sum()) * 252
                    port_vol = float(np.sqrt(np.dot(final_weights.values, np.dot(cov_matrix.values, final_weights.values)))) * np.sqrt(252)
                    st.warning(f"Weights optimized to meet max volatility constraint: {max_volatility:.2%} (no cash allowed)")
                else:
                    st.error("Optimization failed to meet volatility constraint. Showing original regime-aware weights.")
            st.info(f"**Expected Return:** {port_return:.2%}  |  **Volatility:** {port_vol:.2%}")

        st.success("\n✅ Regime-Aware Portfolio Weights:")
        st.dataframe(weights_df)

# Run the app
if __name__ == "__main__":
    main()