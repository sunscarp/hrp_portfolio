# Usage Guide: Updated Regime-Aware HRP with Multi-Asset Drawdown Control

## Quick Start

### Basic Setup
1. **Launch the app:**
   ```bash
   streamlit run app.py
   ```

2. **Configure in sidebar:**
   - Tickers: `SPY,QQQ,IWM,EEM,TLT,GLD,BIL`
   - Date Range: Last 5 years
   - Max Volatility: 20%
   - Allow Cash: ✓ Checked

3. **NEW - Drawdown Configuration:**
   - **Defensive Assets:** Select [TLT, GLD] (multi-select)
   - **Max Drawdown Allocation:** 30% (slider)

4. **Run Backtest:**
   - Click "Run Regime-Aware HRP Backtest"
   - Download PDF report

---

## Configuration Examples

### Example 1: Conservative (Maximum Defensive Shift)
```
Defensive Assets: [TLT, GLD, BIL]
Max Drawdown Allocation: 50%

Normal Regime Portfolio:
├─ SPY:    30%
├─ QQQ:    20%
├─ IWM:    20%
├─ EEM:    20%
├─ TLT:     5%
├─ GLD:     3%
└─ BIL:     2%

Drawdown Regime Portfolio:
├─ SPY:    15%  (30% × 50% / 100%)
├─ QQQ:    10%  (20% × 50% / 100%)
├─ IWM:    10%  (20% × 50% / 100%)
├─ EEM:    10%  (20% × 50% / 100%)
├─ TLT:    16.7% (50% / 3 defensives)
├─ GLD:    16.7% (50% / 3 defensives)
└─ BIL:    16.7% (50% / 3 defensives)

Result: Heavily defensive during stress (50% defensive assets)
```

### Example 2: Moderate (Balanced Approach)
```
Defensive Assets: [TLT, GLD]
Max Drawdown Allocation: 30%

Normal Regime Portfolio:
├─ SPY:    35%
├─ QQQ:    25%
├─ IWM:    20%
├─ EEM:    10%
├─ TLT:     5%
└─ GLD:     5%

Drawdown Regime Portfolio:
├─ SPY:    24.5%  (35% × 70% / 100%)
├─ QQQ:    17.5%  (25% × 70% / 100%)
├─ IWM:    14%    (20% × 70% / 100%)
├─ EEM:    7%     (10% × 70% / 100%)
├─ TLT:    15%    (30% / 2 defensives)
└─ GLD:    15%    (30% / 2 defensives)

Result: Moderate defensive shift (30% defensive assets)
```

### Example 3: Aggressive (Minimal Defensive Shift)
```
Defensive Assets: [GLD]
Max Drawdown Allocation: 15%

Normal Regime Portfolio:
├─ SPY:    40%
├─ QQQ:    30%
├─ IWM:    15%
├─ EEM:    10%
└─ GLD:     5%

Drawdown Regime Portfolio:
├─ SPY:    34%   (40% × 85% / 100%)
├─ QQQ:    25.5% (30% × 85% / 100%)
├─ IWM:    12.75%(15% × 85% / 100%)
├─ EEM:    8.5%  (10% × 85% / 100%)
└─ GLD:    15%   (100% of 15% allocation)

Result: Minimal defensive shift (only 15% to defensives)
```

### Example 4: Ultra-Conservative (Single Defensive Asset)
```
Defensive Assets: [BIL]
Max Drawdown Allocation: 40%

Normal Regime: 40% equity, 15% bonds, 45% others
Drawdown Regime: 60% equity (scaled), 40% cash (BIL)

Result: Direct shift to cash during stress
```

---

## PDF Report Sections

### Page 1: Settings
Shows all configuration including:
```
REGIME-AWARE SETTINGS:
• Defensive Assets: TLT, GLD
• Max Drawdown Allocation: 30.0%
• Drawdown Threshold: 5.0%
• Regime Vol Multiplier: 1.50x
```

### Page 4: Regime-Aware Analysis
Includes:
- **Weight Comparison Chart:** Base HRP vs Regime-Aware weights
- **Weight Adjustments Chart:** Shows percentage changes
- **Regime Detection Chart:** Visual timeline of drawdown periods
- **Strategy Explanation Box:**
  ```
  During NORMAL Regime:
  • Portfolio: Base HRP weights
  
  During DRAWDOWN Regime:
  • Defensive Assets: TLT, GLD
  • Max Defensive Allocation: 30.0% of portfolio
  • Allocation to each defensive asset: 15.0%
  • Remaining Risky Assets: 70.0% (scaled from base weights)
  ```

---

## Interpreting Results

### Portfolio Transition Example

**During market decline (drawdown detected):**

```
Time T: Normal Regime
SPY:  $40,000
QQQ:  $30,000
TLT:   $5,000
GLD:   $5,000
TOTAL: $80,000

↓ DRAWDOWN SIGNAL

Time T+1: Drawdown Regime (30% defensive, 70% risky)
SPY:  $28,000 ← 70% of original equity exposure
QQQ:  $21,000 ← 70% of original equity exposure
TLT:  $12,000 ← Increased to 30%/2 = 15% = $12,000
GLD:  $12,000 ← Increased to 30%/2 = 15% = $12,000
TOTAL: $80,000 ← Same total value, rebalanced

↓ MARKET RECOVERY

Time T+2: Back to Normal Regime
SPY:  $40,000 ← Returns to base HRP
QQQ:  $30,000 ← Returns to base HRP
TLT:   $5,000 ← Back to base HRP
GLD:   $5,000 ← Back to base HRP
TOTAL: $80,000
```

### Performance Metrics
The report shows:
- **Total Return:** How much portfolio gained/lost
- **Annualized Return:** Average annual return
- **Volatility:** Portfolio standard deviation
- **Sharpe Ratio:** Risk-adjusted returns
- **Max Drawdown:** Largest peak-to-trough decline

Compare between:
- Base HRP (no regime switching)
- Regime-Aware HRP (with defensive shifts)

---

## Advanced Configurations

### Multi-Regime Strategies

**Growth-Focused:**
```
defensive_assets = ["TLT"]  # Only bonds
max_drawdown_allocation = 0.15  # Only 15% shift
```

**Balanced:**
```
defensive_assets = ["TLT", "GLD"]  # Bonds + Gold
max_drawdown_allocation = 0.30  # 30% shift
```

**Protection-Focused:**
```
defensive_assets = ["TLT", "GLD", "BIL"]  # All defensives
max_drawdown_allocation = 0.50  # 50% shift
```

### Regime Detection Tuning

**Sensitive (Early Detection):**
```
regime_vol_mult = 1.2  # Detects drawdown earlier
drawdown_threshold = 0.03  # 3% drawdown triggers
```

**Balanced (Default):**
```
regime_vol_mult = 1.5  # Middle ground
drawdown_threshold = 0.05  # 5% drawdown triggers
```

**Conservative (Late Detection):**
```
regime_vol_mult = 2.0  # Only obvious drawdowns
drawdown_threshold = 0.10  # 10% drawdown triggers
```

---

## Troubleshooting

### Issue: Portfolio not shifting during drawdown
**Solution:** Check if drawdown is being detected
- Reduce `regime_vol_mult` (more sensitive)
- Reduce `drawdown_threshold` (easier to trigger)
- Verify data quality (no missing values)

### Issue: Defensive shift too extreme
**Solution:** Reduce `max_drawdown_allocation`
- Lower from 30% to 15%
- Keeps more risky assets during stress

### Issue: Defensive assets not selected
**Solution:** Ensure they're in the ticker list
- Must be in `selected_assets` first
- Use multi-select properly (Hold Ctrl/Cmd to select multiple)

### Issue: PDF report missing regime settings
**Solution:** Run backtest before downloading
- Settings captured when backtest runs
- Store in session_state
- Pass to PDF generator

---

## Comparing Strategies

### Same Data, Different Settings

**Dataset:** SPY, QQQ, IWM, EEM, TLT, GLD, BIL (5 years)

**Test 1: No Regime Switching**
- Base HRP only
- Total Return: X%
- Max Drawdown: -Y%

**Test 2: Regime Switching (15% Defensive)**
- defensive_assets = ["GLD"]
- max_drawdown_allocation = 0.15
- Total Return: X+A% (hopefully higher)
- Max Drawdown: -Y-B% (hopefully lower)

**Test 3: Regime Switching (30% Defensive)**
- defensive_assets = ["TLT", "GLD"]
- max_drawdown_allocation = 0.30
- Total Return: X+C%
- Max Drawdown: -Y-D% (even lower)

**Analysis:** More defensive shift = more protection but potentially lower returns

---

## Best Practices

### ✅ DO:
- Use diversified defensive assets (don't just use 1)
- Test different allocations with backtests
- Review PDF reports for strategy clarity
- Combine with other risk management techniques
- Monitor regime detection accuracy

### ❌ DON'T:
- Use illiquid assets as defensives
- Set max_drawdown_allocation too high (>50%)
- Ignore the regime detection parameters
- Over-optimize for past data
- Neglect correlation between defensive assets

---

## Formula Reference

### Defensive Asset Weight During Drawdown
```
Weight per defensive asset = max_drawdown_allocation / num_defensive_assets

Example: 30% allocation ÷ 2 assets = 15% each
```

### Risky Asset Weight During Drawdown
```
Risky allocation = 1.0 - max_drawdown_allocation
Weight per risky asset = base_weight × (risky_allocation / sum_base_risky_weights)

Example: 
- Base SPY weight: 40%, Risky allocation: 70%, Sum of risky: 100%
- Drawdown SPY weight: 40% × 70% / 100% = 28%
```

### Portfolio Reconstruction
```
Final Weights = Defensive Weights + Risky Weights
Final Weights sum = 1.0 (always)
```

---

## Video Guide (if available)
[Link to demo video showing setup and backtest]

---

## Support
For issues or questions:
1. Check VALIDATION_CHECKLIST.md
2. Review BEFORE_AFTER_COMPARISON.md
3. See IMPLEMENTATION_SUMMARY.md for technical details
