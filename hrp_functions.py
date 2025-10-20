import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform
from typing import Optional, Dict

# Hierarchical Risk Parity (HRP) base weights

def get_base_hrp_weights(returns: pd.DataFrame) -> pd.Series:
    """
    Compute Hierarchical Risk Parity (HRP) weights for the provided returns DataFrame.

    Returns a Series of weights aligned with returns.columns.
    If covariance calculation fails or inputs are invalid, returns equal weights.
    """
    tickers = returns.columns
    if len(tickers) == 0:
        print("[HRP] No tickers provided.")
        return pd.Series(dtype=float)

    # If only one ticker, return 100% weight
    if len(tickers) == 1:
        print("[HRP] Only one ticker, assigning 100% weight.")
        return pd.Series([1.0], index=tickers)

    try:
        # Calculate correlation matrix
        corr = returns.corr()
        
        # Check for invalid correlations
        if corr.isnull().values.any():
            print("[HRP] NaN in correlation matrix, falling back to equal weights.")
            raise ValueError("NaN in correlation matrix")
        
        # Replace diagonal to ensure it's exactly 1
        np.fill_diagonal(corr.values, 1.0)
        
        # Compute distance matrix using proper formula
        # distance = sqrt((1 - correlation) / 2) for correlation-based distance
        # Or use: distance = sqrt(1 - correlation) for angular distance
        dist = np.sqrt((1 - corr) / 2)
        dist = dist.clip(lower=0)  # Ensure non-negative
        
        if dist.isnull().values.any():
            print("[HRP] NaN in distance matrix, falling back to equal weights.")
            raise ValueError("NaN in distance matrix")
        
        # Convert to condensed distance matrix
        dist_condensed = squareform(dist.values, checks=False)
        
        # Perform hierarchical clustering using single linkage
        link = linkage(dist_condensed, method='single')
        
        # Quasi-diagonalization
        sort_ix = _get_quasi_diag(link)
        sorted_tickers = tickers[sort_ix]
        
        # Recursive bisection
        hrp = _recursive_bisection(returns, sorted_tickers)
        
        # Ensure series is aligned and normalized
        hrp = hrp.reindex(tickers).fillna(0.0)
        
        if hrp.sum() == 0:
            print("[HRP] HRP weights sum to zero, falling back to equal weights.")
            return pd.Series(1.0 / len(tickers), index=tickers)
        
        # Clip negative weights (shouldn't happen but just in case)
        if (hrp < 0).any():
            print(f"[HRP] Negative weights detected: {hrp}, clipping.")
            hrp = hrp.clip(lower=0)
        
        # Final normalization
        return hrp / hrp.sum()
        
    except Exception as e:
        print(f"[HRP] Exception in HRP calculation: {e}, falling back to equal weights.")
        return pd.Series(1.0 / len(tickers), index=tickers)

def _get_quasi_diag(link):
    """
    Reorganize the dendrogram to get a quasi-diagonal order.
    """
    link = link.astype(int)
    num_items = link[-1, 3]  # Total number of items
    
    # Start with the last merge (root)
    sort_ix = pd.Series([link[-1, 0], link[-1, 1]])
    
    # Recursively expand clusters into individual items
    while sort_ix.max() >= num_items:
        sort_ix.index = range(0, sort_ix.shape[0] * 2, 2)  # Even indices
        
        # Find cluster nodes (>= num_items)
        df0 = sort_ix[sort_ix >= num_items]
        
        if len(df0) == 0:
            break
            
        i = df0.index
        j = df0.values - num_items  # Convert to link array index
        
        # Replace cluster with its two children
        sort_ix.loc[i] = link[j, 0]
        
        # Create new series for the right children with proper indexing
        new_indices = i + 1
        new_values = link[j, 1]
        df1 = pd.Series(new_values, index=new_indices)
        
        # Concatenate the series properly
        sort_ix = pd.concat([sort_ix, df1], ignore_index=False)
        sort_ix = sort_ix.sort_index()
        sort_ix = sort_ix.reset_index(drop=True)
    
    return sort_ix.astype(int).values

def _recursive_bisection(returns, sorted_tickers):
    """
    Recursively allocate weights using inverse-variance allocation.
    """
    # Initialize equal weights
    w = pd.Series(1.0, index=sorted_tickers)
    clusters = [list(sorted_tickers)]
    
    while clusters:
        new_clusters = []
        for cluster in clusters:
            if len(cluster) == 1:
                continue
            
            # Split cluster in half
            split = len(cluster) // 2
            left = cluster[:split]
            right = cluster[split:]
            
            # Calculate variance of each sub-cluster
            var_left = _cluster_var(returns[left])
            var_right = _cluster_var(returns[right])
            
            # Inverse variance weighting
            if var_left + var_right == 0:
                alpha = 0.5
            else:
                # Allocate inversely proportional to variance
                alpha = 1 - var_left / (var_left + var_right)
            
            # Update weights
            w[left] = w[left] * alpha
            w[right] = w[right] * (1 - alpha)
            
            new_clusters.extend([left, right])
        
        clusters = new_clusters
    
    # Normalize
    if w.sum() > 0:
        w = w / w.sum()
    else:
        w = pd.Series(1.0 / len(sorted_tickers), index=sorted_tickers)
    
    return w

def _cluster_var(returns):
    """
    Calculate the variance of a cluster of assets.
    Variance of equally-weighted portfolio: w^T Σ w where w = [1/n, ..., 1/n]
    """
    if len(returns.columns) == 0:
        return 0.0
    
    cov = returns.cov()
    
    # Handle NaN values
    if cov.isnull().values.any():
        cov = cov.fillna(0.0)
    
    n = cov.shape[0]
    if n == 0:
        return 0.0
    
    # Equal weights
    w = np.ones(n) / n
    
    # Portfolio variance: w^T Σ w
    variance = np.dot(w, np.dot(cov.values, w))
    
    return max(float(variance), 1e-10)  # Ensure positive variance

# Regime-aware HRP with drawdown control
def regime_aware_hrp_with_drawdown(returns: pd.DataFrame,
                                   detect_fn=None,
                                   confidence_threshold: float = 0.55,
                                   drawdown_control: bool = True,
                                   drawdown_mode: str = 'B',
                                   drawdown_threshold: float = 0.10,
                                   defensive_assets: list = None,
                                   max_drawdown_allocation: float = 0.30,
                                   **kwargs) -> Dict[str, pd.Series]:
    """
    A regime-aware HRP implementation that uses a provided detection function
    `detect_fn(returns)` -> pd.Series of regime labels. The function returns a dict with
    'regime_weights' (HRP adjusted for regime) and 'final_weights' (after drawdown control).

    If detect_fn is None, returns plain HRP weights.
    
    Parameters:
    - returns: DataFrame of returns
    - detect_fn: Function to detect regimes
    - drawdown_control: Whether to apply drawdown control
    - defensive_assets: List of assets to use during drawdown regime (e.g., ["TLT", "GLD"])
    - max_drawdown_allocation: Maximum allocation to defensive assets during drawdown (0-1)
    
    When drawdown_control=True and in drawdown regime: 
        - Allocates up to max_drawdown_allocation to defensive assets (equal-weighted)
        - Remaining allocation goes to risky assets scaled down proportionally
    When drawdown_control=False: regime_weights = final_weights (no drawdown adjustment)
    """
    tickers = returns.columns
    
    # Validate and filter defensive assets
    if defensive_assets is None:
        defensive_assets = []
    else:
        defensive_assets = [asset for asset in defensive_assets if asset in tickers]
    
    if defensive_assets and len(defensive_assets) > 0:
        print(f"[Regime HRP] Using defensive assets: {defensive_assets}")
    
    # Ensure max_drawdown_allocation is valid
    max_drawdown_allocation = max(0.0, min(1.0, max_drawdown_allocation))

    # Baseline HRP
    base_w = get_base_hrp_weights(returns)

    if detect_fn is None:
        return {'regime_weights': base_w, 'final_weights': base_w}

    # Detect regimes
    try:
        regimes = detect_fn(returns, **kwargs)
    except TypeError:
        # Some detection fns expect only returns
        regimes = detect_fn(returns)

    # If detection failed, fallback
    if regimes is None or len(regimes) == 0:
        return {'regime_weights': base_w, 'final_weights': base_w}

    # Take the most recent regime
    current_regime = regimes.iloc[-1]

    # Apply regime-based adjustments to HRP weights
    regime_w = base_w.copy()

    # Regime-aware drawdown control: shift to defensive assets during drawdown
    if drawdown_control and current_regime == 'drawdown':
        final_w = pd.Series(0.0, index=tickers)
        
        if defensive_assets and len(defensive_assets) > 0:
            # Equal-weight the defensive assets and allocate max_drawdown_allocation
            defensive_weight = max_drawdown_allocation / len(defensive_assets)
            for asset in defensive_assets:
                final_w[asset] = defensive_weight
            
            # Remaining allocation to risky assets (scaled down proportionally)
            risky_allocation = 1.0 - max_drawdown_allocation
            risky_assets = [a for a in tickers if a not in defensive_assets]
            
            if risky_assets and risky_allocation > 0:
                # Scale risky asset weights proportionally
                risky_weights = regime_w[risky_assets].copy()
                if risky_weights.sum() > 0:
                    risky_weights = risky_weights / risky_weights.sum()
                    risky_weights = risky_weights * risky_allocation
                    final_w[risky_assets] = risky_weights
        else:
            # No defensive assets specified: scale down all risky assets by max_drawdown_allocation
            final_w = regime_w * (1.0 - max_drawdown_allocation)
            if final_w.sum() > 0:
                final_w = final_w / final_w.sum()
    else:
        # Normal regime: use HRP weights
        final_w = regime_w.copy()
        if final_w.sum() > 0:
            final_w = final_w / final_w.sum()
        else:
            # Fallback to equal weights if sum is zero
            final_w = pd.Series(1.0 / len(tickers), index=tickers)

    return {
        'regime_weights': regime_w.fillna(0.0),
        'final_weights': final_w.fillna(0.0)
    }

# Regime detection using HMM (stub)
def detect_regimes_hmm_responsive(returns: pd.DataFrame) -> pd.Series:
    """
    Dummy HMM-like regime detection. Returns 'normal' or 'drawdown' based on
    recent volatility and cumulative returns.
    """
    if len(returns) < 5:
        return pd.Series(['normal'] * len(returns), index=returns.index)
    
    # Calculate rolling volatility
    vol = returns.std(axis=1).rolling(window=5, min_periods=1).mean()
    median_vol = vol.median() if not vol.empty else 0.0
    
    # Calculate cumulative returns
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
        
        # Mark as drawdown if volatility is high AND in drawdown
        if current_vol > 1.5 * median_vol and drawdown < -0.05:
            regimes.iloc[i] = 'drawdown'
        else:
            regimes.iloc[i] = 'normal'
    
    return regimes


def apply_volatility_constraint(weights: pd.Series, returns: pd.DataFrame, 
                              max_volatility: float, allow_cash: bool = True) -> pd.Series:
    """
    Apply volatility constraint to portfolio weights.
    
    Parameters:
    - weights: Base portfolio weights
    - returns: Historical returns data  
    - max_volatility: Maximum allowed portfolio volatility (annualized)
    - allow_cash: If True, scale weights down and allow cash. If False, optimize to hit target.
    
    Returns:
    - Adjusted weights that satisfy volatility constraint
    """
    if len(weights) == 0 or max_volatility <= 0:
        return weights
    
    try:
        # Calculate portfolio volatility
        cov_matrix = returns.cov()
        if cov_matrix.isnull().values.any():
            return weights
            
        # Annualized volatility
        portfolio_var = np.dot(weights.values, np.dot(cov_matrix.values, weights.values))
        portfolio_vol = np.sqrt(portfolio_var * 252)
        
        if portfolio_vol <= max_volatility:
            # Already within constraint
            return weights
            
        if allow_cash:
            # Scale down weights to meet volatility constraint
            scale_factor = max_volatility / portfolio_vol
            adjusted_weights = weights * scale_factor
            
            # The remaining goes to cash (implicit)
            cash_allocation = 1.0 - adjusted_weights.sum()
            
            return adjusted_weights
        else:
            # Optimize weights to sum to 1 while meeting volatility constraint
            # Simple scaling approach - more sophisticated optimization could be used
            scale_factor = max_volatility / portfolio_vol
            adjusted_weights = weights * scale_factor
            
            # Renormalize to sum to 1
            if adjusted_weights.sum() > 0:
                adjusted_weights = adjusted_weights / adjusted_weights.sum()
            
            return adjusted_weights
            
    except Exception as e:
        print(f"Error applying volatility constraint: {e}")
        return weights


def get_hrp_weights_with_constraints(returns: pd.DataFrame, max_volatility: float = None, 
                                   allow_cash: bool = True, defensive_assets: list = None) -> pd.Series:
    """
    Get HRP weights with volatility constraints applied.
    
    Parameters:
    - returns: Historical returns data
    - max_volatility: Maximum allowed portfolio volatility (annualized) 
    - allow_cash: Whether to allow cash allocation
    - defensive_assets: List of defensive assets (excluded from display)
    
    Returns:
    - Portfolio weights with constraints applied
    """
    # Get base HRP weights
    base_weights = get_base_hrp_weights(returns)
    
    # Apply volatility constraint if specified
    if max_volatility is not None:
        base_weights = apply_volatility_constraint(base_weights, returns, max_volatility, allow_cash)
    
    return base_weights


def get_regime_weights_with_constraints(returns: pd.DataFrame, max_volatility: float = None,
                                      allow_cash: bool = True, defensive_assets: list = None,
                                      confidence_threshold: float = 0.55, drawdown_control: bool = True,
                                      drawdown_mode: str = 'B', drawdown_threshold: float = 0.10,
                                      max_drawdown_allocation: float = 0.30) -> Dict[str, pd.Series]:
    """
    Get regime-aware HRP weights with volatility constraints applied.
    
    Parameters:
    - returns: Historical returns data
    - max_volatility: Maximum allowed portfolio volatility (annualized)
    - allow_cash: Whether to allow cash allocation
    - defensive_assets: List of defensive assets to use during drawdown regime
    - max_drawdown_allocation: Maximum allocation to defensive assets during drawdown (0-1)
    
    Returns:
    - Dictionary with 'regime_weights' and 'final_weights'
    """
    # Get regime-aware weights
    regime_result = regime_aware_hrp_with_drawdown(
        returns, detect_regimes_hmm_responsive,
        confidence_threshold, drawdown_control, drawdown_mode, drawdown_threshold,
        defensive_assets=defensive_assets,
        max_drawdown_allocation=max_drawdown_allocation
    )
    
    # Apply volatility constraints to both regime_weights and final_weights
    if max_volatility is not None:
        regime_result['regime_weights'] = apply_volatility_constraint(
            regime_result['regime_weights'], returns, max_volatility, allow_cash
        )
        regime_result['final_weights'] = apply_volatility_constraint(
            regime_result['final_weights'], returns, max_volatility, allow_cash
        )
    
    return regime_result