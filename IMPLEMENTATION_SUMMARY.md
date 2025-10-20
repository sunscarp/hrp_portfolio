# Updated Regime-Aware HRP Implementation Summary

## Overview
The regime-aware drawdown control logic has been completely refactored to replace the single-asset allocation approach with a flexible multi-asset defensive portfolio strategy.

## Key Changes

### 1. **Backend Functions (hrp_functions.py)**

#### `regime_aware_hrp_with_drawdown()` - MAJOR REFACTOR
**Previous Logic:**
- Allocated 100% to a single defensive asset (e.g., GLD) during drawdown

**New Logic:**
- Accepts `defensive_assets` (list) and `max_drawdown_allocation` (0-1 float)
- During **NORMAL regime**: Uses base HRP weights
- During **DRAWDOWN regime**:
  - Allocates `max_drawdown_allocation` equally across all defensive assets
  - Example: `defensive_assets=["TLT", "GLD"]`, `max_drawdown_allocation=0.30`
    - TLT: 15% | GLD: 15% | Remaining risky assets: 70% (scaled proportionally)
  - Remaining allocation scaled from base HRP weights

**New Parameters:**
```python
defensive_assets: list = None      # e.g., ["TLT", "GLD"]
max_drawdown_allocation: float = 0.30  # 0-1, e.g., 0.30 = 30% max to defensives
```

#### `get_regime_weights_with_constraints()` - UPDATED
- Now accepts `max_drawdown_allocation` parameter
- Passes it directly to `regime_aware_hrp_with_drawdown()`
- Removed old `defensive_asset` single-asset parameter

### 2. **User Interface (app.py)**

#### Sidebar Configuration - UPDATED
**Removed:**
- Single defensive asset selector (`st.selectbox`)

**Added:**
- **Multi-select for defensive assets:**
  - `st.multiselect("Select defensive assets (for drawdown regime):")`
  - Default: ["BIL", "TLT"] if available
  - Allows users to select any combination of assets

- **Slider for max drawdown allocation:**
  - Range: 10% - 100%
  - Default: 30%
  - Controls how much of portfolio shifts to defensive assets during drawdown

#### Function Signatures - UPDATED
**`backtest_strategies()`:**
```python
def backtest_strategies(returns, rebalance_freq=21, lookback_window=252, 
                       max_volatility=None, allow_cash=True, 
                       defensive_assets=None, max_drawdown_allocation=0.30,
                       drawdown_threshold=0.05, regime_vol_mult=1.5)
```

### 3. **Settings Storage - UPDATED**

#### HRP Settings (Session State):
```python
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
```

#### Regime Settings (Session State):
```python
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
```

### 4. **PDF Report Generation - ENHANCED**

#### Title Page (Page 1) - UPDATED Settings Section
Now includes:
```
REGIME-AWARE SETTINGS:
• Defensive Assets: TLT, GLD (or list of selected assets)
• Max Drawdown Allocation: 30% (or user-selected %)
• Drawdown Threshold: 5% (or user-selected %)
• Regime Vol Multiplier: 1.5x (or user-selected multiplier)
```

#### Regime-Aware HRP Analysis Page (Page 4) - ENHANCED
**New Addition - Strategy Explanation Section:**
- Shows defensive assets selected
- Shows allocation percentages during drawdown
- Shows remaining allocation to risky assets
- Displays regime detection parameters
- Includes visual explanation of how portfolio adjusts

Example output:
```
REGIME-AWARE DRAWDOWN STRATEGY LOGIC:

During NORMAL Regime:
• Portfolio: Base HRP weights
• Allocation: Risky assets at full HRP weights

During DRAWDOWN Regime:
• Defensive Assets: TLT, GLD
• Max Defensive Allocation: 30.0% of portfolio
• Allocation to each defensive asset: 15.0%
• Remaining Risky Assets: 70.0% (scaled from base weights)

Regime Detection Parameters:
• Drawdown Threshold: 5.0%
• Volatility Multiplier: 1.50x
```

## Usage Example

### User Workflow:
1. **Select Portfolio:**
   - Tickers: SPY, QQQ, IWM, EEM, TLT, GLD, BIL

2. **Configure Defensive Assets:**
   - Multi-select: [TLT, GLD]

3. **Set Max Drawdown Allocation:**
   - Slider: 30%

4. **Run Backtest:**
   - System automatically:
     - Detects drawdown regimes
     - During drawdown: Allocates 15% TLT + 15% GLD + 70% risky (scaled)
     - During normal: Uses base HRP weights

5. **Generate Report:**
   - PDF includes all settings and strategy explanation

## Portfolio Behavior During Drawdown

### Example Scenario:
- Base HRP: SPY 25% | QQQ 30% | IWM 10% | EEM 15% | TLT 5% | GLD 10% | BIL 5%
- Defensive Assets: [TLT, GLD]
- Max Drawdown Allocation: 30%

**When DRAWDOWN detected:**
1. Allocate 15% to TLT (defensive)
2. Allocate 15% to GLD (defensive)
3. Remaining 70% goes to risky assets (SPY, QQQ, IWM, EEM, BIL):
   - SPY: 25% × 0.70 / (25+30+10+15+5) ≈ 11.67%
   - QQQ: 30% × 0.70 / (25+30+10+15+5) ≈ 14.00%
   - IWM: 10% × 0.70 / (25+30+10+15+5) ≈ 4.67%
   - EEM: 15% × 0.70 / (25+30+10+15+5) ≈ 7.00%
   - BIL: 5% × 0.70 / (25+30+10+15+5) ≈ 2.33%

**Result:** Portfolio maintains risk control while still holding some risky assets

## Benefits Over Previous Implementation

1. **Flexibility:** Users can select any defensive assets
2. **Scalability:** Works with any number of defensive assets
3. **Control:** Users set exactly how much to allocate to defensives
4. **Transparency:** Clear explanation in reports of strategy employed
5. **Diversification:** Defensive allocation spreads across multiple assets instead of single asset concentration

## Backward Compatibility

⚠️ **Breaking Changes:**
- Old `defensive_asset` parameter (single string) → `defensive_assets` (list)
- Any code using the old single-asset approach needs updating

✅ **Automatic Migration:**
- App automatically uses new multi-select UI
- Settings stored with new parameter names
- Reports generate correctly with new logic
