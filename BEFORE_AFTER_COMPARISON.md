# Before & After Comparison: Regime-Aware Drawdown Logic

## OLD IMPLEMENTATION (Single Asset Allocation)

### Code Structure
```python
# OLD: regime_aware_hrp_with_drawdown()
def regime_aware_hrp_with_drawdown(returns, 
                                   detect_fn=None,
                                   defensive_asset: str = None,  # ← Single asset
                                   **kwargs):
    
    if drawdown_control and current_regime == 'drawdown':
        if defensive_asset is not None:
            # Allocate 100% to defensive asset
            final_w = pd.Series(0.0, index=tickers)
            final_w[defensive_asset] = 1.0  # ← ALL IN ONE ASSET
```

### UI Configuration (OLD)
```python
# OLD: app.py sidebar
defensive_asset = st.sidebar.selectbox(
    "Select defensive asset (for drawdown regime):",
    options=["None"] + selected_assets,
    index=(selected_assets.index("BIL")+1) if "BIL" in selected_assets else 0
)
if defensive_asset == "None":
    defensive_asset = None
```

### Portfolio Behavior (OLD)
**Scenario:** SPY 40%, QQQ 30%, TLT 20%, GLD 10%, defensive_asset=GLD

**During DRAWDOWN:**
- Portfolio becomes: **100% GLD**
- SPY: 0% | QQQ: 0% | TLT: 0% | GLD: 100%
- ❌ Complete sector rotation, loses diversification
- ❌ Single-asset risk concentration

---

## NEW IMPLEMENTATION (Multi-Asset Defensive Portfolio)

### Code Structure
```python
# NEW: regime_aware_hrp_with_drawdown()
def regime_aware_hrp_with_drawdown(returns,
                                   detect_fn=None,
                                   defensive_assets: list = None,  # ← Multiple assets
                                   max_drawdown_allocation: float = 0.30,  # ← Control allocation %
                                   **kwargs):
    
    if drawdown_control and current_regime == 'drawdown':
        final_w = pd.Series(0.0, index=tickers)
        
        if defensive_assets and len(defensive_assets) > 0:
            # Equal-weight the defensive assets
            defensive_weight = max_drawdown_allocation / len(defensive_assets)
            for asset in defensive_assets:
                final_w[asset] = defensive_weight  # ← DISTRIBUTED ALLOCATION
            
            # Remaining allocation to risky assets (scaled)
            risky_allocation = 1.0 - max_drawdown_allocation
            risky_assets = [a for a in tickers if a not in defensive_assets]
            
            if risky_assets and risky_allocation > 0:
                risky_weights = regime_w[risky_assets].copy()
                risky_weights = risky_weights / risky_weights.sum()
                risky_weights = risky_weights * risky_allocation
                final_w[risky_assets] = risky_weights  # ← PROPORTIONAL SCALING
```

### UI Configuration (NEW)
```python
# NEW: app.py sidebar
defensive_assets_selected = st.sidebar.multiselect(
    "Select defensive assets (for drawdown regime):",
    options=selected_assets,
    default=["BIL", "TLT"] if "BIL" in selected_assets and "TLT" in selected_assets else [],
    help="Assets to allocate to during drawdown regime (e.g., bonds, gold, cash)."
)

max_drawdown_allocation = st.sidebar.slider(
    "Max allocation to defensive assets during drawdown (%):",
    min_value=10,
    max_value=100,
    value=30,
    step=5,
    help="Maximum percentage of portfolio to allocate to defensive assets when in drawdown regime."
)
max_drawdown_allocation = max_drawdown_allocation / 100
```

### Portfolio Behavior (NEW)
**Scenario:** SPY 40%, QQQ 30%, TLT 20%, GLD 10%, defensive_assets=[TLT, GLD], max_drawdown_allocation=30%

**During DRAWDOWN:**
- Portfolio becomes: TLT 15% + GLD 15% + (70% of risky assets scaled)
  - TLT: 15% (defensive)
  - GLD: 15% (defensive)
  - SPY: 40% × 0.70 / 70% = 28%
  - QQQ: 30% × 0.70 / 70% = 21%
  - BIL: 10% × 0.70 / 70% = 7%

- ✅ Maintains diversification (5 assets instead of 1)
- ✅ Controlled defensive shift (only 30%, not 100%)
- ✅ Risk is spread across multiple defensive assets
- ✅ Risky assets still get 70% of portfolio

---

## Detailed Comparison Table

| Aspect | OLD Implementation | NEW Implementation |
|--------|-------------------|-------------------|
| **Defensive Assets** | Single asset only | Multiple assets |
| **User Control** | None (fixed to 100%) | Full control via slider (10-100%) |
| **Allocation Method** | All-in approach | Distributed equally |
| **Risky Asset Exposure** | 0% during drawdown | User-defined (70% default) |
| **Diversification** | Lost during drawdown | Maintained |
| **Risk Concentration** | High (single asset) | Low (multiple assets) |
| **Portfolio Transitions** | Binary on/off | Gradual adjustments |
| **Flexibility** | Fixed strategy | Customizable strategy |
| **Default** | "BIL" only | ["BIL", "TLT"] |
| **PDF Report** | Basic settings | Detailed strategy explanation |

---

## Example Calculations

### OLD: Single Asset (100% GLD)
```
Base Portfolio (Normal Regime):
├─ SPY:   $40,000 (40%)
├─ QQQ:   $30,000 (30%)
├─ TLT:   $20,000 (20%)
└─ GLD:   $10,000 (10%)
Total:   $100,000

Drawdown Regime Portfolio:
├─ SPY:       $0 (0%)
├─ QQQ:       $0 (0%)
├─ TLT:       $0 (0%)
└─ GLD:  $100,000 (100%) ← ALL EGGS IN ONE BASKET
Total:   $100,000
```

### NEW: Multiple Assets (30% defensive, 70% risky)
```
Base Portfolio (Normal Regime):
├─ SPY:   $40,000 (40%)
├─ QQQ:   $30,000 (30%)
├─ TLT:   $20,000 (20%)
└─ GLD:   $10,000 (10%)
Total:   $100,000

Drawdown Regime Portfolio:
├─ SPY:   $28,000 (28%) ← Reduced but still present
├─ QQQ:   $21,000 (21%) ← Reduced but still present
├─ TLT:   $15,000 (15%) ← Defensive
├─ GLD:   $15,000 (15%) ← Defensive
└─ BIL:    $7,000 (7%)  ← From original risky mix
Total:   $100,000

✅ Diversified across 5 assets
✅ Defensive assets increased to 30%
✅ Risky assets maintained at 70%
```

---

## Settings Stored in PDF Report

### OLD Report Settings:
```
PORTFOLIO CONFIGURATION:
• Max Volatility: 20.0%
• Allow Cash: True

BACKTEST SETTINGS:
• Rebalancing Frequency: 21 days
• Lookback Window: 252 days
```

### NEW Report Settings:
```
PORTFOLIO CONFIGURATION:
• Max Volatility: 20.0%
• Allow Cash: True

BACKTEST SETTINGS:
• Rebalancing Frequency: 21 days
• Lookback Window: 252 days

REGIME-AWARE SETTINGS:  ← NEW SECTION
• Defensive Assets: TLT, GLD
• Max Drawdown Allocation: 30.0%
• Drawdown Threshold: 5.0%
• Regime Vol Multiplier: 1.50x
```

---

## Key Improvements

### 1. **Risk Management** 🎯
- **OLD:** Single asset risk (GLD only)
- **NEW:** Diversified defensive basket (TLT + GLD)

### 2. **Flexibility** 🔧
- **OLD:** Fixed 100% allocation
- **NEW:** User-customizable 10-100%

### 3. **Optimization** 📊
- **OLD:** Static allocation
- **NEW:** Dynamic based on regime detection

### 4. **Transparency** 📄
- **OLD:** Basic settings
- **NEW:** Detailed strategy explanation in reports

### 5. **Scalability** 📈
- **OLD:** Works with 1 asset only
- **NEW:** Works with N assets

---

## Migration Notes

### For Existing Users:
1. ⚠️ Old setting `defensive_asset="GLD"` → New: `defensive_assets=["GLD"]`
2. ✅ Old allocation 100% → New default: 30% (more conservative)
3. ✅ Can now add multiple defensives: `defensive_assets=["TLT", "GLD", "BIL"]`
4. ✅ Can control allocation: `max_drawdown_allocation=0.50` for 50%

### For Developers:
- Update function calls to use `defensive_assets` (list) not `defensive_asset` (str)
- Update PDF report generation to include new settings
- Update backtest logic to pass new parameters
