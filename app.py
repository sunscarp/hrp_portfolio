import streamlit as st
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import yfinance as yf
from datetime import datetime, timedelta
import warnings
import seaborn as sns
import io
import base64
from fpdf import FPDF
from matplotlib.backends.backend_pdf import PdfPages
import tempfile
import os
warnings.filterwarnings('ignore')

# Import your existing functions (make sure these are in your project)
from hrp_functions import (get_base_hrp_weights, regime_aware_hrp_with_drawdown, 
                          detect_regimes_hmm_responsive, get_hrp_weights_with_constraints,
                          get_regime_weights_with_constraints)

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
    value="SPY,QQQ,IWM,EEM,TLT,GLD,BIL"
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

# Defensive asset selection
st.sidebar.subheader("Drawdown Regime Configuration")
defensive_assets_selected = st.sidebar.multiselect(
    "Select defensive assets (for drawdown regime):",
    options=selected_assets,
    default=["BIL", "TLT"] if "BIL" in selected_assets and "TLT" in selected_assets else (
        ["BIL"] if "BIL" in selected_assets else (
        ["TLT"] if "TLT" in selected_assets else selected_assets[:1] if selected_assets else []
    )),
    help="Assets to allocate to during drawdown regime (e.g., bonds, gold, cash)."
)

# Max drawdown allocation (percentage of portfolio)
max_drawdown_allocation = st.sidebar.slider(
    "Max allocation to defensive assets during drawdown (%):",
    min_value=10,
    max_value=100,
    value=30,
    step=5,
    help="Maximum percentage of portfolio to allocate to defensive assets when in drawdown regime."
)
max_drawdown_allocation = max_drawdown_allocation / 100

# Drawdown threshold
st.sidebar.subheader("Drawdown Threshold (%)")
drawdown_threshold = st.sidebar.slider(
    "Drawdown threshold for regime detection:",
    min_value=1,
    max_value=20,
    value=5,
    step=1,
    help="Threshold (in %) for identifying drawdown regime."
)
drawdown_threshold = drawdown_threshold / 100

# Regime detection sensitivity (volatility multiplier)
st.sidebar.subheader("Regime Detection Sensitivity")
regime_vol_mult = st.sidebar.slider(
    "Volatility multiplier for drawdown regime:",
    min_value=1.0,
    max_value=3.0,
    value=1.5,
    step=0.1,
    help="How sensitive regime detection is to volatility spikes."
)

# Markdown explanation
st.markdown("""
### Regime-Aware Drawdown Control
This app implements a regime-aware portfolio that shifts to a defensive asset (e.g., cash or bonds) during detected drawdown regimes. You can control the defensive asset, drawdown threshold, and regime detection sensitivity in the sidebar. The logic and results are visualized below.
""")


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

def backtest_strategies(returns, rebalance_freq=21, lookback_window=252, max_volatility=None, allow_cash=True, 
                        defensive_assets=None, max_drawdown_allocation=0.30, drawdown_threshold=0.05, regime_vol_mult=1.5):
    """
    Backtest both HRP and Regime-Aware HRP strategies
    
    Parameters:
    - returns: DataFrame of asset returns
    - rebalance_freq: Rebalancing frequency in trading days (default 21 = monthly)
    - lookback_window: Historical data window for weight calculation (default 252 = 1 year)
    - max_volatility: Maximum allowed portfolio volatility (annualized)
    - allow_cash: Whether to allow cash allocation
    - defensive_assets: List of defensive assets for drawdown regime
    - max_drawdown_allocation: Maximum allocation to defensive assets during drawdown
    - drawdown_threshold: Threshold for identifying drawdown regime
    - regime_vol_mult: Volatility multiplier for regime detection
    """
    if defensive_assets is None:
        defensive_assets = []
    # Only pure data processing, no widgets
    if len(returns) < lookback_window + rebalance_freq:
        return None
    dates = returns.index[lookback_window:]
    hrp_portfolio_values = []
    regime_portfolio_values = []
    hrp_weights_history = []
    regime_weights_history = []
    regime_history = []
    hrp_value = 1.0
    regime_value = 1.0
    current_hrp_weights = pd.Series(1.0/len(returns.columns), index=returns.columns)
    current_regime_weights = pd.Series(1.0/len(returns.columns), index=returns.columns)
    rebalance_counter = 0
    for i, date in enumerate(dates):
        # Check if it's time to rebalance
        if rebalance_counter % rebalance_freq == 0:
            hist_start = max(0, i + lookback_window - lookback_window)
            hist_end = i + lookback_window
            hist_returns = returns.iloc[hist_start:hist_end]
            if len(hist_returns) >= 20:
                try:
                    current_hrp_weights = get_hrp_weights_with_constraints(hist_returns, max_volatility, allow_cash)
                    # Use new regime-aware HRP with drawdown control and user params
                    from hrp_functions import regime_aware_hrp_with_drawdown, detect_regimes_hmm_responsive
                    def custom_detect_fn(returns):
                        # Use user regime_vol_mult and drawdown_threshold
                        vol = returns.std(axis=1).rolling(window=5, min_periods=1).mean()
                        median_vol = vol.median() if not vol.empty else 0.0
                        cum_returns = (1 + returns.mean(axis=1)).cumprod()
                        regimes = pd.Series(index=returns.index, dtype=object)
                        for i, idx in enumerate(returns.index):
                            if i < 5:
                                regimes.iloc[i] = 'normal'
                                continue
                            current_vol = vol.iloc[i]
                            current_cum = cum_returns.iloc[i]
                            max_cum = cum_returns.iloc[:i+1].max()
                            drawdown = (current_cum - max_cum) / max_cum if max_cum > 0 else 0
                            if current_vol > regime_vol_mult * median_vol and drawdown < -drawdown_threshold:
                                regimes.iloc[i] = 'drawdown'
                            else:
                                regimes.iloc[i] = 'normal'
                        return regimes
                    regime_result = regime_aware_hrp_with_drawdown(
                        hist_returns,
                        detect_fn=custom_detect_fn,
                        drawdown_control=True,
                        drawdown_mode='B',
                        drawdown_threshold=drawdown_threshold,
                        defensive_assets=defensive_assets,
                        max_drawdown_allocation=max_drawdown_allocation
                    )
                    current_regime_weights = regime_result.get('final_weights', current_hrp_weights)
                    try:
                        regimes = custom_detect_fn(hist_returns)
                        current_regime = regimes.iloc[-1] if len(regimes) > 0 else 'normal'
                    except:
                        current_regime = 'normal'
                except Exception:
                    current_regime = 'normal'
        daily_returns = returns.loc[date]
        hrp_daily_return = (current_hrp_weights * daily_returns).sum()
        regime_daily_return = (current_regime_weights * daily_returns).sum()
        hrp_value *= (1 + hrp_daily_return)
        regime_value *= (1 + regime_daily_return)
        hrp_portfolio_values.append(hrp_value)
        regime_portfolio_values.append(regime_value)
        hrp_weights_history.append(current_hrp_weights.copy())
        regime_weights_history.append(current_regime_weights.copy())
        if rebalance_counter % rebalance_freq == 0:
            regime_history.append(current_regime)
        else:
            regime_history.append(regime_history[-1] if regime_history else 'normal')
        rebalance_counter += 1
    results = pd.DataFrame({
        'Date': dates,
        'HRP_Portfolio': hrp_portfolio_values,
        'Regime_HRP_Portfolio': regime_portfolio_values,
        'Regime': regime_history
    }).set_index('Date')
    hrp_returns = pd.Series(hrp_portfolio_values, index=dates).pct_change().dropna()
    regime_returns = pd.Series(regime_portfolio_values, index=dates).pct_change().dropna()
    metrics = {
        'HRP': {
            'Total Return': (hrp_portfolio_values[-1] - 1) * 100,
            'Annualized Return': (hrp_portfolio_values[-1] ** (252/len(hrp_returns)) - 1) * 100,
            'Volatility': hrp_returns.std() * np.sqrt(252) * 100,
            'Sharpe Ratio': (hrp_returns.mean() * 252) / (hrp_returns.std() * np.sqrt(252)),
            'Max Drawdown': ((hrp_returns + 1).cumprod() / (hrp_returns + 1).cumprod().expanding().max() - 1).min() * 100
        },
        'Regime-Aware HRP': {
            'Total Return': (regime_portfolio_values[-1] - 1) * 100,
            'Annualized Return': (regime_portfolio_values[-1] ** (252/len(regime_returns)) - 1) * 100,
            'Volatility': regime_returns.std() * np.sqrt(252) * 100,
            'Sharpe Ratio': (regime_returns.mean() * 252) / (regime_returns.std() * np.sqrt(252)),
            'Max Drawdown': ((regime_returns + 1).cumprod() / (regime_returns + 1).cumprod().expanding().max() - 1).min() * 100
        }
    }
    return {
        'portfolio_values': results,
        'metrics': metrics,
        'hrp_weights_history': hrp_weights_history,
        'regime_weights_history': regime_weights_history
    }

def generate_pdf_report(returns, hrp_weights, regime_weights, final_weights, 
                       hrp_backtest=None, regime_backtest=None, settings=None):
    """
    Generate a comprehensive PDF report with all analysis results
    """
    # Defensive: check for None weights and raise a clear error
    if hrp_weights is None or regime_weights is None or final_weights is None:
        raise ValueError("One or more portfolio weights (HRP, Regime-Aware, Final) are None. Please ensure weights are computed and passed correctly.")
    # Create a temporary file for the PDF
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
    temp_filename = temp_file.name
    temp_file.close()
    
    # Do NOT recalculate weights here. Use the ones passed as arguments from the app.
    
    # Defensive assets logic removed from display
    display_assets = list(returns.columns)
    
    try:
        with PdfPages(temp_filename) as pdf:
            # Page 1: Title and Settings
            fig = plt.figure(figsize=(8.5, 11))
            fig.suptitle('Portfolio Analysis Report', fontsize=20, fontweight='bold', y=0.95)
            
            # Settings section
            settings_text = f"""
Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

PORTFOLIO CONFIGURATION:
• Assets: {', '.join(display_assets)}
• Period: {returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}
• Trading Days: {len(returns)}
• Max Volatility: {settings.get('max_volatility', 0.2)*100:.1f}%
• Allow Cash: {settings.get('allow_cash', True)}

BACKTEST SETTINGS:
• Rebalancing Frequency: {settings.get('rebalance_freq', 21)} days
• Lookback Window: {settings.get('lookback_window', 252)} days

REGIME-AWARE SETTINGS:
• Defensive Assets: {', '.join(settings.get('defensive_assets', [])) if settings.get('defensive_assets') else 'None'}
• Max Drawdown Allocation: {settings.get('max_drawdown_allocation', 0.30)*100:.1f}%
• Drawdown Threshold: {settings.get('drawdown_threshold', 0.05)*100:.1f}%
• Regime Vol Multiplier: {settings.get('regime_vol_mult', 1.5):.2f}x
"""
            
            plt.text(0.1, 0.8, settings_text, fontsize=12, fontfamily='monospace',
                    verticalalignment='top', transform=fig.transFigure)
            plt.axis('off')
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()
            
            # Page 2: Data Overview and Statistics
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(11, 8.5))
            fig.suptitle('Data Overview and Statistics', fontsize=16, fontweight='bold')
            
            # Cumulative returns
            cum_returns = (1 + returns).cumprod()
            cum_returns.plot(ax=ax1, title='Cumulative Returns', legend=True)
            ax1.set_ylabel('Cumulative Return')
            ax1.grid(True, alpha=0.3)
            
            # Correlation heatmap
            corr = returns.corr()
            sns.heatmap(corr, annot=True, cmap='coolwarm', ax=ax2, cbar=True, 
                       fmt='.2f', square=True)
            ax2.set_title('Correlation Matrix')
            
            # Returns distribution
            returns.mean().plot(kind='bar', ax=ax3, title='Average Daily Returns')
            ax3.set_ylabel('Return')
            ax3.tick_params(axis='x', rotation=45)
            
            # Volatility
            (returns.std() * np.sqrt(252)).plot(kind='bar', ax=ax4, title='Annualized Volatility')
            ax4.set_ylabel('Volatility')
            ax4.tick_params(axis='x', rotation=45)
            
            plt.tight_layout()
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()
            
            # Page 3: HRP Analysis
            fig = plt.figure(figsize=(11, 8.5))
            fig.suptitle('Hierarchical Risk Parity (HRP) Analysis', fontsize=16, fontweight='bold')
            
            # Create subplots
            gs = fig.add_gridspec(2, 3, hspace=0.3, wspace=0.3)
            
            # Dendrogram
            ax1 = fig.add_subplot(gs[0, :2])
            from scipy.cluster.hierarchy import linkage, dendrogram
            from scipy.spatial.distance import squareform
            dist = np.sqrt((1 - corr).clip(upper=1)) / 2
            link = linkage(squareform(dist), 'ward')
            dendrogram(link, labels=returns.columns, leaf_rotation=90, ax=ax1)
            ax1.set_title('Asset Clustering Dendrogram')
            
            # HRP Weights (excluding defensive assets from display)
            ax2 = fig.add_subplot(gs[0, 2])
            hrp_weights_display = hrp_weights[display_assets] if display_assets else hrp_weights
            hrp_weights_display.plot(kind='bar', ax=ax2, color='steelblue')
            ax2.set_title('HRP Weights')
            ax2.set_ylabel('Weight')
            ax2.tick_params(axis='x', rotation=45)
            
            # Portfolio metrics
            ax3 = fig.add_subplot(gs[1, :])
            mean_returns = returns.mean()
            cov_matrix = returns.cov()
            port_return = float((hrp_weights * mean_returns).sum()) * 252
            port_vol = float(np.sqrt(np.dot(hrp_weights.values, np.dot(cov_matrix.values, hrp_weights.values)))) * np.sqrt(252)
            
            cash_allocation = 1.0 - hrp_weights.sum()
            sharpe_ratio = port_return/port_vol if port_vol > 0 else 0
            
            metrics_text = f"""
HRP PORTFOLIO METRICS:
• Expected Annual Return: {port_return:.2%}
• Expected Annual Volatility: {port_vol:.2%}
• Sharpe Ratio: {sharpe_ratio:.2f}
• Sum of Weights: {hrp_weights.sum():.3f}
• Cash Allocation: {cash_allocation:.1%}

ASSET ALLOCATION:
"""
            for asset, weight in hrp_weights.items():
                if asset in display_assets:  # Only show non-defensive assets
                    metrics_text += f"• {asset}: {weight:.1%}\n"
            
            if cash_allocation > 0.01:  # Show cash if significant
                metrics_text += f"• Cash: {cash_allocation:.1%}\n"
            
            ax3.text(0.1, 0.9, metrics_text, fontsize=11, fontfamily='monospace',
                    verticalalignment='top', transform=ax3.transAxes)
            ax3.axis('off')
            
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()
            
            # Page 4: Regime-Aware HRP Analysis
            fig = plt.figure(figsize=(11, 8.5))
            fig.suptitle('Regime-Aware HRP Analysis', fontsize=16, fontweight='bold')
            
            gs = fig.add_gridspec(3, 2, hspace=0.4, wspace=0.3)
            
            # Weight comparison (excluding defensive assets from display)
            ax1 = fig.add_subplot(gs[0, 0])
            weights_df = pd.DataFrame({
                'Base HRP': hrp_weights,
                'Regime-Aware': final_weights
            }).fillna(0.0)
            
            # Filter to display assets only (assets are in the index)
            if display_assets:
                # Get intersection of display_assets and weights_df index
                assets_to_show = [asset for asset in display_assets if asset in weights_df.index]
                weights_df_display = weights_df.loc[assets_to_show] if assets_to_show else weights_df
            else:
                weights_df_display = weights_df
                
            weights_df_display.plot(kind='bar', ax=ax1, width=0.8)
            ax1.set_title('Base vs Regime-Aware Weights')
            ax1.set_ylabel('Weight')
            ax1.tick_params(axis='x', rotation=45)
            ax1.legend()
            
            # Weight difference (excluding defensive assets from display)
            ax2 = fig.add_subplot(gs[0, 1])
            weight_diff = final_weights - hrp_weights
            
            # Filter to display assets only
            if display_assets:
                assets_to_show = [asset for asset in display_assets if asset in weight_diff.index]
                weight_diff_display = weight_diff[assets_to_show] if assets_to_show else weight_diff
            else:
                weight_diff_display = weight_diff
                
            weight_diff_display.plot(kind='bar', ax=ax2, color='orange')
            ax2.set_title('Weight Adjustments')
            ax2.set_ylabel('Weight Difference')
            ax2.tick_params(axis='x', rotation=45)
            ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
            
            # Regime detection visualization
            ax3 = fig.add_subplot(gs[1, :])
            try:
                regimes = detect_regimes_hmm_responsive(returns)
                regime_numeric = (regimes == 'drawdown').astype(int)
                ax3.fill_between(regimes.index, 0, regime_numeric, alpha=0.3, color='red', 
                                label='Drawdown Regime')
                ax3.set_title('Regime Detection Over Time')
                ax3.set_ylabel('Regime (0=Normal, 1=Drawdown)')
                ax3.legend()
            except:
                ax3.text(0.5, 0.5, 'Regime detection visualization unavailable', 
                        ha='center', va='center', transform=ax3.transAxes)
                ax3.set_title('Regime Detection')
            
            # Regime-Aware Drawdown Strategy Explanation
            ax4 = fig.add_subplot(gs[2, :])
            defensive_assets_str = ', '.join(settings.get('defensive_assets', [])) if settings.get('defensive_assets') else 'None'
            strategy_text = f"""
REGIME-AWARE DRAWDOWN STRATEGY LOGIC:

During NORMAL Regime:
• Portfolio: Base HRP weights (optimized hierarchical risk parity)
• Allocation: Risky assets at full HRP weights

During DRAWDOWN Regime:
• Defensive Assets: {defensive_assets_str}
• Max Defensive Allocation: {settings.get('max_drawdown_allocation', 0.30)*100:.1f}% of portfolio
• Allocation to each defensive asset: {settings.get('max_drawdown_allocation', 0.30)*100/max(len(settings.get('defensive_assets', [1])), 1):.1f}%
• Remaining Risky Assets: {100 - settings.get('max_drawdown_allocation', 0.30)*100:.1f}% (scaled proportionally from base weights)

Regime Detection Parameters:
• Drawdown Threshold: {settings.get('drawdown_threshold', 0.05)*100:.1f}%
• Volatility Multiplier: {settings.get('regime_vol_mult', 1.5):.2f}x (enters drawdown if vol > {settings.get('regime_vol_mult', 1.5):.2f}x median vol)

Portfolio adjusts dynamically between these allocations based on market conditions detected by the regime detection algorithm.
"""
            ax4.text(0.05, 0.95, strategy_text, fontsize=10, fontfamily='monospace',
                    verticalalignment='top', transform=ax4.transAxes, bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.3))
            ax4.axis('off')
            
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()
            
            # Page 5: Portfolio Weights Comparison Table
            fig = plt.figure(figsize=(8.5, 11))
            fig.suptitle('Portfolio Weights Comparison', fontsize=16, fontweight='bold')
            
            # Create weights comparison table
            weights_comparison = pd.DataFrame({
                'Base HRP': hrp_weights,
                'Regime-Aware HRP': final_weights
            }).fillna(0.0)
            
            # Calculate differences and ratios
            weights_comparison['Difference'] = weights_comparison['Regime-Aware HRP'] - weights_comparison['Base HRP']
            weights_comparison['% Change'] = ((weights_comparison['Regime-Aware HRP'] / weights_comparison['Base HRP']) - 1) * 100
            weights_comparison['% Change'] = weights_comparison['% Change'].replace([np.inf, -np.inf], np.nan)
            
            # Filter to display assets only (exclude defensive assets)
            if display_assets:
                assets_to_show = [asset for asset in display_assets if asset in weights_comparison.index]
                weights_display = weights_comparison.loc[assets_to_show] if assets_to_show else weights_comparison
            else:
                weights_display = weights_comparison
            
            # Format the table for display
            weights_formatted = weights_display.copy()
            weights_formatted['Base HRP'] = weights_formatted['Base HRP'].apply(lambda x: f"{x:.2%}")
            weights_formatted['Regime-Aware HRP'] = weights_formatted['Regime-Aware HRP'].apply(lambda x: f"{x:.2%}")
            weights_formatted['Difference'] = weights_formatted['Difference'].apply(lambda x: f"{x:+.2%}")
            weights_formatted['% Change'] = weights_formatted['% Change'].apply(lambda x: f"{x:+.1f}%" if not pd.isna(x) else "N/A")
            
            # Create table text
            table_text = "PORTFOLIO WEIGHTS COMPARISON\n\n"
            table_text += f"{'Asset':<8} {'Base HRP':<10} {'Regime-Aware':<12} {'Difference':<12} {'% Change':<10}\n"
            table_text += "-" * 65 + "\n"
            
            for asset in weights_formatted.index:
                table_text += f"{asset:<8} {weights_formatted.loc[asset, 'Base HRP']:<10} "
                table_text += f"{weights_formatted.loc[asset, 'Regime-Aware HRP']:<12} "
                table_text += f"{weights_formatted.loc[asset, 'Difference']:<12} "
                table_text += f"{weights_formatted.loc[asset, '% Change']:<10}\n"
            
            # Add summary statistics
            table_text += "\n" + "-" * 65 + "\n"
            table_text += f"{'TOTALS':<8} {weights_display['Base HRP'].sum():<10.2%} "
            table_text += f"{weights_display['Regime-Aware HRP'].sum():<12.2%} "
            table_text += f"{weights_display['Difference'].sum():+<12.2%}\n"
            
            cash_base = 1.0 - weights_display['Base HRP'].sum()
            cash_regime = 1.0 - weights_display['Regime-Aware HRP'].sum()
            if cash_base > 0.001 or cash_regime > 0.001:
                table_text += f"{'CASH':<8} {cash_base:<10.2%} {cash_regime:<12.2%} {cash_regime - cash_base:+<12.2%}\n"
            
            plt.text(0.1, 0.9, table_text, fontsize=10, fontfamily='monospace',
                    verticalalignment='top', transform=fig.transFigure)
            plt.axis('off')
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()
            
            # Page 6: Backtest Results (if available)
            if hrp_backtest or regime_backtest:
                fig, axes = plt.subplots(2, 2, figsize=(11, 8.5))
                fig.suptitle('Backtest Results', fontsize=16, fontweight='bold')
                
                # Initialize variables to track if we have data
                has_hrp_data = False
                has_regime_data = False
                
                # Portfolio performance chart
                if hrp_backtest and isinstance(hrp_backtest, dict) and 'portfolio_values' in hrp_backtest:
                    portfolio_values = hrp_backtest['portfolio_values']
                    if isinstance(portfolio_values, pd.DataFrame) and 'HRP_Portfolio' in portfolio_values.columns:
                        portfolio_values['HRP_Portfolio'].plot(ax=axes[0,0], label='HRP', color='blue', linewidth=2)
                        has_hrp_data = True
                
                if regime_backtest and isinstance(regime_backtest, dict) and 'portfolio_values' in regime_backtest:
                    regime_portfolio = regime_backtest['portfolio_values']
                    if isinstance(regime_portfolio, pd.DataFrame) and 'Regime_HRP_Portfolio' in regime_portfolio.columns:
                        regime_portfolio['Regime_HRP_Portfolio'].plot(ax=axes[0,0], label='Regime-Aware HRP', color='red', linewidth=2)
                        has_regime_data = True
                
                if has_hrp_data or has_regime_data:
                    axes[0,0].set_title('Portfolio Performance Comparison')
                    axes[0,0].set_ylabel('Portfolio Value ($)')
                    axes[0,0].legend()
                    axes[0,0].grid(True, alpha=0.3)
                else:
                    axes[0,0].text(0.5, 0.5, 'No portfolio performance data available', 
                                  ha='center', va='center', transform=axes[0,0].transAxes)
                    axes[0,0].set_title('Portfolio Performance')
                
                # Performance metrics table
                metrics_text = "BACKTEST PERFORMANCE METRICS:\n\n"
                metrics_available = False
                
                if hrp_backtest and 'metrics' in hrp_backtest:
                    for strategy, metrics in hrp_backtest['metrics'].items():
                        metrics_text += f"{strategy}:\n"
                        for metric, value in metrics.items():
                            if 'Return' in metric or 'Volatility' in metric or 'Drawdown' in metric:
                                metrics_text += f"  {metric}: {value:.2f}%\n"
                            else:
                                metrics_text += f"  {metric}: {value:.3f}\n"
                        metrics_text += "\n"
                        metrics_available = True
                
                if regime_backtest and 'metrics' in regime_backtest:
                    for strategy, metrics in regime_backtest['metrics'].items():
                        if strategy != 'HRP':  # Avoid duplicate HRP metrics
                            metrics_text += f"{strategy}:\n"
                            for metric, value in metrics.items():
                                if 'Return' in metric or 'Volatility' in metric or 'Drawdown' in metric:
                                    metrics_text += f"  {metric}: {value:.2f}%\n"
                                else:
                                    metrics_text += f"  {metric}: {value:.3f}\n"
                            metrics_text += "\n"
                            metrics_available = True
                
                if not metrics_available:
                    metrics_text = "No backtest metrics available"
                
                axes[0,1].text(0.05, 0.95, metrics_text, fontsize=9, fontfamily='monospace',
                              verticalalignment='top', transform=axes[0,1].transAxes)
                axes[0,1].set_title('Performance Metrics')
                axes[0,1].axis('off')
                
                # Drawdown analysis
                drawdown_plotted = False
                
                if hrp_backtest and 'portfolio_values' in hrp_backtest:
                    portfolio_values = hrp_backtest['portfolio_values']
                    if isinstance(portfolio_values, pd.DataFrame) and 'HRP_Portfolio' in portfolio_values.columns:
                        hrp_cumulative = portfolio_values['HRP_Portfolio']
                        hrp_drawdown = (hrp_cumulative / hrp_cumulative.expanding().max() - 1) * 100
                        axes[1,0].fill_between(hrp_drawdown.index, hrp_drawdown, 0, alpha=0.3, color='blue', label='HRP DD')
                        axes[1,0].plot(hrp_drawdown.index, hrp_drawdown, color='blue', linewidth=1)
                        drawdown_plotted = True
                
                if regime_backtest and 'portfolio_values' in regime_backtest:
                    regime_portfolio = regime_backtest['portfolio_values']
                    if isinstance(regime_portfolio, pd.DataFrame) and 'Regime_HRP_Portfolio' in regime_portfolio.columns:
                        regime_cumulative = regime_portfolio['Regime_HRP_Portfolio']
                        regime_drawdown = (regime_cumulative / regime_cumulative.expanding().max() - 1) * 100
                        axes[1,0].fill_between(regime_drawdown.index, regime_drawdown, 0, alpha=0.3, color='red', label='Regime-Aware DD')
                        axes[1,0].plot(regime_drawdown.index, regime_drawdown, color='red', linewidth=1)
                        drawdown_plotted = True
                
                if drawdown_plotted:
                    axes[1,0].set_title('Drawdown Analysis')
                    axes[1,0].set_ylabel('Drawdown (%)')
                    axes[1,0].legend()
                    axes[1,0].grid(True, alpha=0.3)
                    axes[1,0].axhline(y=0, color='black', linestyle='-', alpha=0.5)
                else:
                    axes[1,0].text(0.5, 0.5, 'No drawdown data available', 
                                  ha='center', va='center', transform=axes[1,0].transAxes)
                    axes[1,0].set_title('Drawdown Analysis')
                
                # Rolling Sharpe ratio or additional analysis
                rolling_analysis_text = "ROLLING ANALYSIS:\n\n"
                
                try:
                    if hrp_backtest and 'portfolio_values' in hrp_backtest:
                        pv = hrp_backtest['portfolio_values']
                        if 'HRP_Portfolio' in pv.columns:
                            hrp_returns = pv['HRP_Portfolio'].pct_change().dropna()
                            rolling_sharpe = hrp_returns.rolling(window=63).apply(
                                lambda x: (x.mean() * 252) / (x.std() * np.sqrt(252)) if x.std() > 0 else 0
                            )
                            rolling_analysis_text += f"HRP 3M Rolling Sharpe (Latest): {rolling_sharpe.iloc[-1]:.3f}\n"
                            rolling_analysis_text += f"HRP 3M Rolling Sharpe (Avg): {rolling_sharpe.mean():.3f}\n\n"
                    
                    if regime_backtest and 'portfolio_values' in regime_backtest:
                        pv = regime_backtest['portfolio_values']
                        if 'Regime_HRP_Portfolio' in pv.columns:
                            regime_returns = pv['Regime_HRP_Portfolio'].pct_change().dropna()
                            rolling_sharpe = regime_returns.rolling(window=63).apply(
                                lambda x: (x.mean() * 252) / (x.std() * np.sqrt(252)) if x.std() > 0 else 0
                            )
                            rolling_analysis_text += f"Regime HRP 3M Rolling Sharpe (Latest): {rolling_sharpe.iloc[-1]:.3f}\n"
                            rolling_analysis_text += f"Regime HRP 3M Rolling Sharpe (Avg): {rolling_sharpe.mean():.3f}\n"
                    
                except Exception as e:
                    rolling_analysis_text += f"Rolling analysis error: {str(e)[:100]}"
                
                axes[1,1].text(0.1, 0.9, rolling_analysis_text, fontsize=10, fontfamily='monospace',
                              verticalalignment='top', transform=axes[1,1].transAxes)
                axes[1,1].set_title('Rolling Performance Analysis')
                axes[1,1].axis('off')
                
                plt.tight_layout()
                pdf.savefig(fig, bbox_inches='tight')
                plt.close()
            else:
                # Create a page indicating no backtest results available
                fig = plt.figure(figsize=(11, 8.5))
                fig.suptitle('Backtest Results', fontsize=16, fontweight='bold')
                plt.text(0.5, 0.5, 'No backtest results available.\nRun backtests first to generate performance charts.', 
                        ha='center', va='center', fontsize=14, transform=fig.transFigure)
                plt.axis('off')
                pdf.savefig(fig, bbox_inches='tight')
                plt.close()
        
        # Read the PDF file and return as bytes
        with open(temp_filename, 'rb') as f:
            pdf_bytes = f.read()
        
        return pdf_bytes
        
    finally:
        # Clean up temporary file
        if os.path.exists(temp_filename):
            os.unlink(temp_filename)

def main():
    # Use defensive assets from user selection
    defensive_assets = defensive_assets_selected if defensive_assets_selected else []
    
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

    # Store returns data in session state for PDF generation
    st.session_state['returns_data'] = returns

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
        hrp_weights = get_hrp_weights_with_constraints(returns, max_volatility, allow_cash, defensive_assets)
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

            # Calculate expected return and volatility for HRP
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

        # Show expected return and volatility for HRP only once, after all adjustments
        st.info(f"**Expected Return:** {port_return:.2%}  |  **Volatility:** {port_vol:.2%}")

        st.success("\n✅ Final HRP Weights:")
        st.dataframe(hrp_weights)
        
        # Backtesting section for HRP
        st.subheader("📈 HRP Strategy Backtest")
        
        col1, col2 = st.columns(2)
        with col1:
            rebalance_freq = st.selectbox("Rebalancing Frequency", 
                                        options=[21, 63, 126, 252], 
                                        format_func=lambda x: f"{x} days ({'Monthly' if x==21 else 'Quarterly' if x==63 else 'Semi-Annual' if x==126 else 'Annual'})",
                                        index=0, key="hrp_rebal")
        with col2:
            lookback_options = [126, 252, 504]
            lookback_window = st.selectbox("Lookback Window", 
                                         options=lookback_options, 
                                         format_func=lambda x: f"{x} days ({x//252:.1f} years)",
                                         index=1, key="hrp_lookback")
            custom_lookback = st.number_input("Or enter custom lookback (days)", min_value=30, max_value=len(returns), value=lookback_window, step=1, key="hrp_custom_lookback")
            if custom_lookback not in lookback_options:
                lookback_window = int(custom_lookback)
        
        if st.button("Run HRP Backtest", key="hrp_backtest_btn"):
            if len(returns) >= lookback_window + rebalance_freq:
                with st.spinner("Running HRP backtest..."):
                    backtest_results = backtest_strategies(returns, rebalance_freq, lookback_window, max_volatility, allow_cash,
                                                          defensive_assets, max_drawdown_allocation, drawdown_threshold, regime_vol_mult)
                
                if backtest_results:
                    # Performance metrics
                    st.subheader("📊 HRP Performance Metrics")
                    hrp_metrics = backtest_results['metrics']['HRP']
                    
                    col1, col2, col3, col4, col5 = st.columns(5)
                    with col1:
                        st.metric("Total Return", f"{hrp_metrics['Total Return']:.2f}%")
                    with col2:
                        st.metric("Annualized Return", f"{hrp_metrics['Annualized Return']:.2f}%")
                    with col3:
                        st.metric("Volatility", f"{hrp_metrics['Volatility']:.2f}%")
                    with col4:
                        st.metric("Sharpe Ratio", f"{hrp_metrics['Sharpe Ratio']:.2f}")
                    with col5:
                        st.metric("Max Drawdown", f"{hrp_metrics['Max Drawdown']:.2f}%")
                    
                    # Portfolio value chart
                    st.subheader("📈 HRP Portfolio Performance")
                    fig, ax = plt.subplots(figsize=(12, 6))
                    ax.plot(backtest_results['portfolio_values'].index, 
                           backtest_results['portfolio_values']['HRP_Portfolio'], 
                           label='HRP Strategy', linewidth=2)
                    ax.set_title('HRP Strategy Backtest Performance')
                    ax.set_xlabel('Date')
                    ax.set_ylabel('Portfolio Value')
                    ax.legend()
                    ax.grid(True, alpha=0.3)
                    st.pyplot(fig)
                    
                    # Weights evolution (show last 10 rebalancing dates)
                    st.subheader("🔄 Recent Weight Evolution")
                    recent_weights = pd.DataFrame(backtest_results['hrp_weights_history'][-10:], 
                                                index=backtest_results['portfolio_values'].index[-10:])
                    
                    fig, ax = plt.subplots(figsize=(12, 6))
                    recent_weights.plot(kind='area', stacked=True, ax=ax, alpha=0.7)
                    ax.set_title('HRP Weights Evolution (Last 10 Rebalances)')
                    ax.set_xlabel('Date')
                    ax.set_ylabel('Weight')
                    ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
                    st.pyplot(fig)
                    
                    # Store backtest results for PDF generation
                    st.session_state['hrp_backtest_results'] = backtest_results
                    st.session_state['hrp_weights'] = hrp_weights
                    st.session_state['hrp_settings'] = {
                        'rebalance_freq': rebalance_freq,
                        'lookback_window': lookback_window,
                        'max_volatility': max_volatility,
                        'allow_cash': allow_cash,
                        'defensive_assets': defensive_assets,
                        'max_drawdown_allocation': max_drawdown_allocation,
                        'drawdown_threshold': drawdown_threshold,
                        'regime_vol_mult': regime_vol_mult
                    }
                    
            else:
                st.error(f"Insufficient data for backtesting. Need at least {lookback_window + rebalance_freq} days, but have {len(returns)} days.")

    # ===============================
    # Regime-Aware HRP Section
    # ===============================
    with st.expander("🧠 Regime-Aware HRP (click to expand)", expanded=False):
        st.markdown("**Regime-Aware HRP Portfolio**")
        
        # Calculate base HRP weights with constraints for comparison
        base_hrp_weights = get_hrp_weights_with_constraints(returns, max_volatility, allow_cash, defensive_assets)
        
        # Use regime-aware HRP with constraints
        regime_result = get_regime_weights_with_constraints(
            returns, max_volatility, allow_cash, defensive_assets,
            confidence_threshold=0.55, drawdown_control=True,
            max_drawdown_allocation=max_drawdown_allocation
        )
        regime_weights = regime_result.get('regime_weights', base_hrp_weights)
        final_weights = regime_result.get('final_weights', base_hrp_weights)

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
            st.markdown("**Base HRP vs Regime-Aware Weights**")
            weights_df = pd.DataFrame({
                'Base HRP': base_hrp_weights,
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

        # Detailed Weights Comparison Table
        st.markdown("**Portfolio Weights Comparison**")
        weights_comparison = pd.DataFrame({
            'Base HRP (%)': (base_hrp_weights * 100).round(2),
            'Regime-Aware (%)': (final_weights * 100).round(2)
        })
        weights_comparison['Difference (%)'] = (weights_comparison['Regime-Aware (%)'] - weights_comparison['Base HRP (%)']).round(2)
        weights_comparison['% Change'] = ((final_weights / base_hrp_weights - 1) * 100).replace([np.inf, -np.inf], np.nan).round(1)
        
        # Filter out defensive assets from display if specified
        defensive_assets = defensive_assets or []
        display_assets = [asset for asset in weights_comparison.index if asset not in defensive_assets]
        
        if display_assets:
            weights_display = weights_comparison.loc[display_assets]
        else:
            weights_display = weights_comparison
            
        # Add totals row
        totals_row = pd.DataFrame({
            'Base HRP (%)': [weights_display['Base HRP (%)'].sum()],
            'Regime-Aware (%)': [weights_display['Regime-Aware (%)'].sum()],
            'Difference (%)': [weights_display['Difference (%)'].sum()],
            '% Change': [np.nan]
        }, index=['TOTAL'])
        
        weights_display_with_totals = pd.concat([weights_display, totals_row])
        
        # Show cash allocation if significant
        cash_base = 100 - weights_display['Base HRP (%)'].sum()
        cash_regime = 100 - weights_display['Regime-Aware (%)'].sum()
        
        if abs(cash_base) > 0.1 or abs(cash_regime) > 0.1:
            cash_row = pd.DataFrame({
                'Base HRP (%)': [cash_base],
                'Regime-Aware (%)': [cash_regime],
                'Difference (%)': [cash_regime - cash_base],
                '% Change': [np.nan]
            }, index=['CASH'])
            weights_display_with_totals = pd.concat([weights_display_with_totals, cash_row])
        
        st.dataframe(weights_display_with_totals, use_container_width=True)

        # Calculate expected return and volatility for regime-aware portfolio
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

        # Show expected return and volatility for Regime-Aware HRP only once, after all adjustments
        st.info(f"**Expected Return:** {port_return:.2%}  |  **Volatility:** {port_vol:.2%}")

        st.success("\n✅ Regime-Aware Portfolio Weights:")
        st.dataframe(weights_df)
        
        # Backtesting section for Regime-Aware HRP
        st.subheader("📈 Regime-Aware HRP Strategy Backtest")
        
        col1, col2 = st.columns(2)
        with col1:
            regime_rebalance_freq = st.selectbox("Rebalancing Frequency", 
                                               options=[21, 63, 126, 252], 
                                               format_func=lambda x: f"{x} days ({'Monthly' if x==21 else 'Quarterly' if x==63 else 'Semi-Annual' if x==126 else 'Annual'})",
                                               index=0, key="regime_rebal")
        with col2:
            regime_lookback_options = [126, 252, 504]
            regime_lookback_window = st.selectbox("Lookback Window", 
                                                options=regime_lookback_options, 
                                                format_func=lambda x: f"{x} days ({x//252:.1f} years)",
                                                index=1, key="regime_lookback")
            regime_custom_lookback = st.number_input("Or enter custom lookback (days)", min_value=30, max_value=len(returns), value=regime_lookback_window, step=1, key="regime_custom_lookback")
            if regime_custom_lookback not in regime_lookback_options:
                regime_lookback_window = int(regime_custom_lookback)
        
        if st.button("Run Regime-Aware HRP Backtest", key="regime_backtest_btn"):
            if len(returns) >= regime_lookback_window + regime_rebalance_freq:
                with st.spinner("Running Regime-Aware HRP backtest..."):
                    backtest_results = backtest_strategies(returns, regime_rebalance_freq, regime_lookback_window, max_volatility, allow_cash,
                                                          defensive_assets, max_drawdown_allocation, drawdown_threshold, regime_vol_mult)
                
                if backtest_results:
                    # Performance comparison
                    st.subheader("📊 Strategy Comparison")
                    
                    # Side by side metrics
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**HRP Strategy**")
                        hrp_metrics = backtest_results['metrics']['HRP']
                        st.metric("Total Return", f"{hrp_metrics['Total Return']:.2f}%")
                        st.metric("Annualized Return", f"{hrp_metrics['Annualized Return']:.2f}%")
                        st.metric("Volatility", f"{hrp_metrics['Volatility']:.2f}%")
                        st.metric("Sharpe Ratio", f"{hrp_metrics['Sharpe Ratio']:.2f}")
                        st.metric("Max Drawdown", f"{hrp_metrics['Max Drawdown']:.2f}%")
                    
                    with col2:
                        st.markdown("**Regime-Aware HRP Strategy**")
                        regime_metrics = backtest_results['metrics']['Regime-Aware HRP']
                        st.metric("Total Return", f"{regime_metrics['Total Return']:.2f}%", 
                                delta=f"{regime_metrics['Total Return'] - hrp_metrics['Total Return']:.2f}%")
                        st.metric("Annualized Return", f"{regime_metrics['Annualized Return']:.2f}%",
                                delta=f"{regime_metrics['Annualized Return'] - hrp_metrics['Annualized Return']:.2f}%")
                        st.metric("Volatility", f"{regime_metrics['Volatility']:.2f}%",
                                delta=f"{regime_metrics['Volatility'] - hrp_metrics['Volatility']:.2f}%")
                        st.metric("Sharpe Ratio", f"{regime_metrics['Sharpe Ratio']:.2f}",
                                delta=f"{regime_metrics['Sharpe Ratio'] - hrp_metrics['Sharpe Ratio']:.2f}")
                        st.metric("Max Drawdown", f"{regime_metrics['Max Drawdown']:.2f}%",
                                delta=f"{regime_metrics['Max Drawdown'] - hrp_metrics['Max Drawdown']:.2f}%")
                    
                    # Portfolio comparison chart
                    st.subheader("📈 Strategy Performance Comparison")
                    fig, ax = plt.subplots(figsize=(12, 6))
                    ax.plot(backtest_results['portfolio_values'].index, 
                           backtest_results['portfolio_values']['HRP_Portfolio'], 
                           label='HRP Strategy', linewidth=2, alpha=0.8)
                    ax.plot(backtest_results['portfolio_values'].index, 
                           backtest_results['portfolio_values']['Regime_HRP_Portfolio'], 
                           label='Regime-Aware HRP Strategy', linewidth=2, alpha=0.8)
                    ax.set_title('HRP vs Regime-Aware HRP Strategy Comparison')
                    ax.set_xlabel('Date')
                    ax.set_ylabel('Portfolio Value')
                    ax.legend()
                    ax.grid(True, alpha=0.3)
                    st.pyplot(fig)
                    
                    # Regime timeline and defensive asset annotation
                    st.subheader("🧠 Regime Detection Timeline & Defensive Shifts")
                    regime_data = backtest_results['portfolio_values']['Regime']
                    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

                    # Portfolio values with regime background
                    ax1.plot(backtest_results['portfolio_values'].index,
                            backtest_results['portfolio_values']['Regime_HRP_Portfolio'],
                            label='Regime-Aware HRP', linewidth=2)

                    # Color background based on regime
                    drawdown_periods = regime_data == 'drawdown'
                    if drawdown_periods.any():
                        drawdown_starts = drawdown_periods & ~drawdown_periods.shift(1, fill_value=False)
                        drawdown_ends = ~drawdown_periods & drawdown_periods.shift(1, fill_value=False)
                        for start_idx in drawdown_starts[drawdown_starts].index:
                            end_indices = drawdown_ends[drawdown_ends.index > start_idx]
                            end_idx = end_indices.index[0] if len(end_indices) > 0 else regime_data.index[-1]
                            ax1.axvspan(start_idx, end_idx, alpha=0.3, color='red', label='Drawdown Regime' if start_idx == drawdown_starts[drawdown_starts].index[0] else "")
                            # Annotate defensive asset shift
                            if defensive_assets and len(defensive_assets) > 0:
                                def_assets_str = ", ".join(defensive_assets[:2])  # Show first 2
                                ax1.annotate(f"Defensive: {def_assets_str}", xy=(start_idx, ax1.get_ylim()[1]), xycoords='data',
                                             xytext=(0, 10), textcoords='offset points', color='red', fontsize=10,
                                             arrowprops=dict(arrowstyle='->', color='red'))

                    ax1.set_ylabel('Portfolio Value')
                    ax1.set_title('Portfolio Performance with Regime Detection and Defensive Shifts')
                    ax1.legend()
                    ax1.grid(True, alpha=0.3)

                    # Regime indicator
                    regime_numeric = (regime_data == 'drawdown').astype(int)
                    ax2.fill_between(regime_data.index, 0, regime_numeric, alpha=0.5, color='red', label='Drawdown Regime')
                    ax2.set_ylabel('Regime')
                    ax2.set_xlabel('Date')
                    ax2.set_yticks([0, 1])
                    ax2.set_yticklabels(['Normal', 'Drawdown'])
                    ax2.grid(True, alpha=0.3)

                    plt.tight_layout()
                    st.pyplot(fig)

                    st.markdown("""
**How to interpret:**
- Red shaded regions indicate detected drawdown regimes.
- If a defensive asset is selected, the portfolio shifts 100% to that asset during these periods (see annotation).
- Otherwise, the portfolio shifts to cash (all weights zero).
""")
                    
                    # Weight comparison for recent periods
                    st.subheader("⚖️ Weight Allocation Comparison (Recent)")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**HRP Weights Evolution**")
                        recent_hrp_weights = pd.DataFrame(backtest_results['hrp_weights_history'][-10:], 
                                                        index=backtest_results['portfolio_values'].index[-10:])
                        
                        fig, ax = plt.subplots(figsize=(10, 6))
                        recent_hrp_weights.plot(kind='area', stacked=True, ax=ax, alpha=0.7)
                        ax.set_title('HRP Weights (Last 10 Rebalances)')
                        ax.set_xlabel('Date')
                        ax.set_ylabel('Weight')
                        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
                        st.pyplot(fig)
                    
                    with col2:
                        st.markdown("**Regime-Aware HRP Weights Evolution**")
                        recent_regime_weights = pd.DataFrame(backtest_results['regime_weights_history'][-10:], 
                                                           index=backtest_results['portfolio_values'].index[-10:])
                        
                        fig, ax = plt.subplots(figsize=(10, 6))
                        recent_regime_weights.plot(kind='area', stacked=True, ax=ax, alpha=0.7)
                        ax.set_title('Regime-Aware HRP Weights (Last 10 Rebalances)')
                        ax.set_xlabel('Date')
                        ax.set_ylabel('Weight')
                        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
                        st.pyplot(fig)
                        
                        # Store regime backtest results for PDF generation
                        st.session_state['regime_backtest_results'] = backtest_results
                        st.session_state['regime_weights'] = regime_weights
                        st.session_state['final_weights'] = final_weights
                        st.session_state['base_hrp_weights'] = base_hrp_weights  # Store for PDF comparison
                        st.session_state['regime_settings'] = {
                            'rebalance_freq': regime_rebalance_freq,
                            'lookback_window': regime_lookback_window,
                            'max_volatility': max_volatility,
                            'allow_cash': allow_cash,
                            'defensive_assets': defensive_assets,
                            'max_drawdown_allocation': max_drawdown_allocation,
                            'drawdown_threshold': drawdown_threshold,
                            'regime_vol_mult': regime_vol_mult
                        }
            else:
                st.error(f"Insufficient data for backtesting. Need at least {regime_lookback_window + regime_rebalance_freq} days, but have {len(returns)} days.")

    # ===============================
    # PDF REPORT GENERATION
    # ===============================
    st.header("📄 Download PDF Report")
    
    # Check if we have results to generate a report
    has_hrp_results = 'hrp_backtest_results' in st.session_state and 'hrp_weights' in st.session_state
    has_regime_results = 'regime_backtest_results' in st.session_state and 'regime_weights' in st.session_state
    has_returns_data = 'returns_data' in st.session_state
    
    if (has_hrp_results or has_regime_results) and has_returns_data:
        stored_returns = st.session_state['returns_data']
        
        col1, col2, col3 = st.columns(3)
        
        # HRP-only report
        if has_hrp_results:
            with col1:
                if st.button("📊 Download HRP Report", key="download_hrp_report"):
                    with st.spinner("Generating HRP PDF report..."):
                        try:
                            # Prepare data for PDF generation
                            hrp_weights = st.session_state['hrp_weights']
                            hrp_settings = st.session_state['hrp_settings']
                            hrp_backtest = st.session_state.get('hrp_backtest_results', None)
                            
                            # Debug info
                            st.write(f"Debug: HRP backtest data type: {type(hrp_backtest)}")
                            if hrp_backtest:
                                st.write(f"Debug: HRP backtest keys: {list(hrp_backtest.keys())}")
                            
                            # Generate PDF
                            pdf_bytes = generate_pdf_report(
                                returns=stored_returns,
                                hrp_weights=hrp_weights,
                                regime_weights=hrp_weights,  # Use HRP weights for both
                                final_weights=hrp_weights,
                                hrp_backtest=hrp_backtest,
                                regime_backtest=None,  # No regime results for HRP-only report
                                settings=hrp_settings
                            )
                            
                            # Create download link
                            b64 = base64.b64encode(pdf_bytes).decode()
                            href = f'<a href="data:application/pdf;base64,{b64}" download="HRP_Portfolio_Report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf">Click here to download HRP Report</a>'
                            st.markdown(href, unsafe_allow_html=True)
                            st.success("✅ HRP PDF report generated successfully!")
                            
                        except Exception as e:
                            st.error(f"Error generating HRP report: {str(e)}")
                            import traceback
                            st.text(f"Full error: {traceback.format_exc()}")
        
        # Regime-Aware HRP-only report
        if has_regime_results:
            with col2:
                if st.button("🧠 Download Regime-Aware Report", key="download_regime_report"):
                    with st.spinner("Generating Regime-Aware HRP PDF report..."):
                        try:
                            # Prepare data for PDF generation
                            regime_weights = st.session_state['regime_weights']
                            final_weights = st.session_state['final_weights']
                            base_hrp_weights = st.session_state.get('base_hrp_weights', st.session_state.get('hrp_weights'))
                            regime_settings = st.session_state['regime_settings']
                            regime_backtest = st.session_state.get('regime_backtest_results', None)
                            # Fallback: if base_hrp_weights is None, recalculate it
                            if base_hrp_weights is None:
                                base_hrp_weights = get_hrp_weights_with_constraints(
                                    stored_returns,
                                    regime_settings.get('max_volatility'),
                                    regime_settings.get('allow_cash', True),
                                    regime_settings.get('defensive_assets', [])
                                )
                            # Generate PDF
                            pdf_bytes = generate_pdf_report(
                                returns=stored_returns,
                                hrp_weights=base_hrp_weights,  # Use base HRP weights for comparison
                                regime_weights=regime_weights,
                                final_weights=final_weights,
                                hrp_backtest=None,  # No HRP backtest for regime-only report
                                regime_backtest=regime_backtest,
                                settings=regime_settings
                            )
                            # Create download link
                            b64 = base64.b64encode(pdf_bytes).decode()
                            href = f'<a href="data:application/pdf;base64,{b64}" download="Regime_Aware_HRP_Report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf">Click here to download Regime-Aware HRP Report</a>'
                            st.markdown(href, unsafe_allow_html=True)
                            st.success("✅ Regime-Aware HRP PDF report generated successfully!")
                        except Exception as e:
                            st.error(f"Error generating Regime-Aware HRP report: {str(e)}")
                            import traceback
                            st.text(f"Full error: {traceback.format_exc()}")
        
        # Combined report (if both results are available)
        if has_hrp_results and has_regime_results:
            with col3:
                if st.button("📈 Download Combined Report", key="download_combined_report"):
                    with st.spinner("Generating Combined PDF report..."):
                        try:
                            # Prepare data for PDF generation
                            hrp_weights = st.session_state.get('base_hrp_weights', st.session_state.get('hrp_weights'))
                            regime_weights = st.session_state['regime_weights']
                            final_weights = st.session_state['final_weights']
                            hrp_settings = st.session_state.get('hrp_settings', {})
                            regime_settings = st.session_state.get('regime_settings', {})
                            hrp_backtest = st.session_state.get('hrp_backtest_results', None)
                            regime_backtest = st.session_state.get('regime_backtest_results', None)
                            
                            # Debug info
                            st.write(f"Debug: Combined - HRP backtest: {type(hrp_backtest)}")
                            st.write(f"Debug: Combined - Regime backtest: {type(regime_backtest)}")
                            
                            # Merge settings (use regime settings as base, add HRP-specific info)
                            combined_settings = regime_settings.copy()
                            combined_settings['hrp_rebalance_freq'] = hrp_settings['rebalance_freq']
                            combined_settings['hrp_lookback_window'] = hrp_settings['lookback_window']
                            
                            # Generate PDF
                            pdf_bytes = generate_pdf_report(
                                returns=stored_returns,
                                hrp_weights=hrp_weights,
                                regime_weights=regime_weights,
                                final_weights=final_weights,
                                hrp_backtest=hrp_backtest,
                                regime_backtest=regime_backtest,
                                settings=combined_settings
                            )
                            
                            # Create download link
                            b64 = base64.b64encode(pdf_bytes).decode()
                            href = f'<a href="data:application/pdf;base64,{b64}" download="Combined_Portfolio_Report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf">Click here to download Combined Report</a>'
                            st.markdown(href, unsafe_allow_html=True)
                            st.success("✅ Combined PDF report generated successfully!")
                            
                        except Exception as e:
                            st.error(f"Error generating Combined report: {str(e)}")
                            import traceback
                            st.text(f"Full error: {traceback.format_exc()}")
    else:
        st.info("🔍 Please run at least one backtest (HRP or Regime-Aware HRP) to generate a PDF report.")
        st.write("The PDF report will include:")
        st.write("- Portfolio configuration and settings")
        st.write("- Data overview and statistics")
        st.write("- Asset correlation analysis and clustering")
        st.write("- Weight allocations and comparisons")
        st.write("- Backtest performance metrics")
        st.write("- Portfolio performance charts")
        st.write("- Regime detection analysis (for Regime-Aware HRP)")
        st.write("- Drawdown analysis")

# Run the app
if __name__ == "__main__":
    main()