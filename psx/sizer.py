"""
psx/sizer.py: Institutional Position Sizing & Risk Management Calculator
Ensures traders risk a fixed percentage of capital per trade rather than arbitrary share quantities.
"""

def calculate_position_size(capital: float, risk_pct: float, entry_price: float, stop_loss: float) -> dict:
    """
    Calculates exact share count, total capital required, and PnL targets.
    Example: capital=500000, risk_pct=1.5% -> max risk = Rs. 7500.
    """
    if not entry_price or not stop_loss or entry_price <= stop_loss:
        return {"error": "Invalid entry or stop loss price"}

    risk_per_share = round(entry_price - stop_loss, 2)
    max_risk_amount = round(capital * (risk_pct / 100.0), 2)
    
    # Calculate shares allowed based on risk
    raw_shares = int(max_risk_amount / risk_per_share) if risk_per_share > 0 else 0
    # Standard PSX lot rounding (multiples of 100 or 500 for liquid stocks, minimum 1 share)
    shares = max(1, raw_shares)
    
    total_investment = round(shares * entry_price, 2)
    actual_risk = round(shares * risk_per_share, 2)
    
    return {
        "capital": capital,
        "risk_pct": risk_pct,
        "max_risk_amount": max_risk_amount,
        "risk_per_share": risk_per_share,
        "shares": shares,
        "total_investment": total_investment,
        "actual_risk": actual_risk,
        "investment_pct": round((total_investment / capital) * 100, 1) if capital else 0
    }
