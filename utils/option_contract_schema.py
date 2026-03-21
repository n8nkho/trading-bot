"""
Option decision/position schema normalizer.

The codebase contains multiple agents that may produce option-shaped dicts with
inconsistent keys. This module canonicalizes them into a predictable schema
so `orchestrator.py` and `exit_monitor.py` can operate safely.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from dateutil import parser as date_parser


OCC_STRIKE_SCALE = 1000  # OCC used by this project scales strike by 1000
OCC_EXP_LEN = 6  # yymmdd
OCC_TYPE_LEN = 1  # C/P
OCC_STRIKE_LEN = 8  # strike*1000, padded
OCC_TAIL_LEN = OCC_EXP_LEN + OCC_TYPE_LEN + OCC_STRIKE_LEN  # 15


def format_option_symbol(underlying_ticker: str, expiration: str, strike: float, call: bool = True) -> str:
    """
    Format an option symbol in OCC-like format for this project.
    """
    exp_date = date_parser.parse(expiration)
    exp_str = exp_date.strftime("%y%m%d")
    option_type = "C" if call else "P"
    strike_int = int(round(float(strike) * OCC_STRIKE_SCALE))
    strike_str = f"{strike_int:08d}"
    return f"{underlying_ticker.upper()}{exp_str}{option_type}{strike_str}"


def parse_occ_option_symbol(option_symbol: str) -> Dict[str, Any]:
    """
    Parse an OCC-like option symbol produced by `format_option_symbol`.

    Returns:
      {
        underlying_ticker: str,
        expiration: 'YYYY-MM-DD',
        strike: float,
        call: bool
      }
    """
    s = option_symbol.strip().upper()
    if len(s) < OCC_TAIL_LEN + 1:
        raise ValueError(f"Option symbol too short to parse: {option_symbol}")

    underlying_ticker = s[:-OCC_TAIL_LEN]
    exp_str = s[-OCC_TAIL_LEN : -OCC_TAIL_LEN + OCC_EXP_LEN]  # yymmdd
    option_type = s[-OCC_TAIL_LEN + OCC_EXP_LEN : -OCC_TAIL_LEN + OCC_EXP_LEN + OCC_TYPE_LEN]  # C/P
    strike_str = s[-OCC_STRIKE_LEN:]

    exp_date = datetime.strptime(exp_str, "%y%m%d").date()
    strike = int(strike_str) / OCC_STRIKE_SCALE
    call = option_type == "C"

    return {
        "underlying_ticker": underlying_ticker,
        "expiration": exp_date.isoformat(),
        "strike": float(strike),
        "call": call,
    }


def normalize_option_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize an option trade decision into a canonical dict expected by `orchestrator.py`.

    Expected output keys (subset):
      - trade_type: 'OPTION'
      - action: 'BUY'|'SKIP'
      - ticker: underlying equity ticker (NOT the option symbol)
      - strike: float
      - expiration: 'YYYY-MM-DD'
      - contracts: int
      - call: bool
      - entry_price: float (option premium)
      - position_size: float (premium cost in dollars; contracts*premium*100)
    """
    out = dict(decision)

    out["trade_type"] = "OPTION"
    out["action"] = out.get("action") or "BUY"
    out["call"] = bool(out.get("call", True))

    # underlying_ticker: by convention in this repo `decision['ticker']` is underlying
    underlying = out.get("ticker")
    if not underlying:
        underlying = out.get("underlying_ticker")
    if not underlying:
        raise ValueError("Option decision missing underlying ticker (decision['ticker'] or ['underlying_ticker'])")
    out["ticker"] = underlying

    # strike & expiration can be on the decision or inside option_details
    if out.get("strike") is None and isinstance(out.get("option_details"), dict):
        out["strike"] = out["option_details"].get("strike")
    if out.get("expiration") is None and isinstance(out.get("option_details"), dict):
        out["expiration"] = out["option_details"].get("expiration")

    if out.get("strike") is None or out.get("expiration") is None:
        # Try parsing from any contract symbol if present.
        maybe_symbol = out.get("option_symbol") or out.get("contract_symbol") or out.get("contract")
        if maybe_symbol:
            parsed = parse_occ_option_symbol(str(maybe_symbol))
            out["ticker"] = parsed["underlying_ticker"]
            out["strike"] = parsed["strike"]
            out["expiration"] = parsed["expiration"]
            out["call"] = parsed["call"]
        else:
            raise ValueError("Option decision missing 'strike'/'expiration' and no parseable option symbol is present")

    out["strike"] = float(out["strike"])
    out["expiration"] = str(out["expiration"])
    out["call"] = bool(out["call"])

    # contracts
    if out.get("contracts") is None:
        out["contracts"] = out.get("qty") or out.get("position_qty") or 0
    out["contracts"] = int(out["contracts"])
    if out["contracts"] < 0:
        out["contracts"] = 0

    # premium/entry_price
    if out.get("entry_price") is None:
        if isinstance(out.get("option_details"), dict):
            out["entry_price"] = out["option_details"].get("premium") or out["option_details"].get("entry_premium")
    if out.get("entry_price") is None:
        # Some versions used filled_price or premium
        out["entry_price"] = out.get("premium") or out.get("filled_price")
    if out.get("entry_price") is None:
        raise ValueError("Option decision missing premium (entry_price/premium)")
    out["entry_price"] = float(out["entry_price"])

    # position_size (premium cost)
    if out.get("position_size") is None:
        if isinstance(out.get("option_details"), dict) and out["option_details"].get("cost") is not None:
            out["position_size"] = float(out["option_details"]["cost"])
        else:
            out["position_size"] = float(out["contracts"]) * out["entry_price"] * 100.0
    out["position_size"] = float(out["position_size"])

    # reasoning/reason harmonization
    out["reasoning"] = out.get("reasoning") or out.get("reason") or ""

    return out


def normalize_option_position(position: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a saved option position for `exit_monitor.check_option_exit()`.

    Expected output keys:
      - type: 'OPTION'
      - ticker: option_symbol (OCC-like)
      - underlying_ticker: underlying equity ticker
      - qty: contracts remaining (int)
      - entry_premium: float
      - strike: float
      - expiration_date: 'YYYY-MM-DD'
      - call: bool
      - tiers_sold: {tier1: bool, tier2: bool, tier3: bool}
    """
    out = dict(position)
    out["type"] = "OPTION"

    tiers = out.get("tiers_sold")
    if not isinstance(tiers, dict):
        tiers = {"tier1": False, "tier2": False, "tier3": False}
    else:
        tiers = {
            "tier1": bool(tiers.get("tier1", False)),
            "tier2": bool(tiers.get("tier2", False)),
            "tier3": bool(tiers.get("tier3", False)),
        }
    out["tiers_sold"] = tiers

    # qty
    qty = out.get("qty")
    if qty is None:
        qty = out.get("contracts") or out.get("position_qty") or 0
    out["qty"] = int(qty)

    # entry_premium
    if out.get("entry_premium") is None:
        out["entry_premium"] = out.get("entry_price") or out.get("premium")
    if out.get("entry_premium") is None:
        # If missing, we cannot compute P&L; keep as None and allow caller to HOLD.
        out["entry_premium"] = None
    else:
        out["entry_premium"] = float(out["entry_premium"])

    # If we already have contract symbol, parse missing fields.
    option_symbol = out.get("ticker")
    underlying = out.get("underlying_ticker")
    strike = out.get("strike")
    expiration_date = out.get("expiration_date") or out.get("expiration")
    call = out.get("call")

    if option_symbol and (strike is None or expiration_date is None or underlying is None or call is None):
        parsed = parse_occ_option_symbol(str(option_symbol))
        underlying = underlying or parsed["underlying_ticker"]
        strike = strike if strike is not None else parsed["strike"]
        expiration_date = expiration_date if expiration_date is not None else parsed["expiration"]
        call = call if call is not None else parsed["call"]

    # If contract symbol missing but we have underlying/strike/expiration/call, build it.
    if not option_symbol:
        if underlying and strike is not None and expiration_date and call is not None:
            option_symbol = format_option_symbol(underlying, expiration_date, float(strike), bool(call))
            out["ticker"] = option_symbol
        else:
            out["ticker"] = None

    out["underlying_ticker"] = underlying
    if strike is not None:
        out["strike"] = float(strike)
    if expiration_date is not None:
        # Normalize to YYYY-MM-DD
        out["expiration_date"] = str(date_parser.parse(str(expiration_date)).date().isoformat())
    if call is not None:
        out["call"] = bool(call)

    # Hard validation: option exit logic needs these fields to compute premium P&L.
    # If we can't guarantee them, raise so callers fail-safe to HOLD.
    if (
        out.get("underlying_ticker") is None
        or out.get("strike") is None
        or out.get("expiration_date") is None
        or out.get("call") is None
        or out.get("entry_premium") is None
        or out.get("qty", 0) <= 0
    ):
        raise ValueError(f"Cannot fully normalize option position: {out.get('ticker')}")

    return out

