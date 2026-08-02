"""REQ-006: all phase prices (X, Y, Z, W, V) are sourced from IBKR historical/live
data only — no third-party market-data provider anywhere in this module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from natural_trading.pricing.resolver import DailyBar

HISTORY_DURATION = "45 D"  # comfortably covers one lunar cycle (~29.5 days) + fallback slack


@dataclass
class IBPriceClient:
    """Thin wrapper over an ib_async `IB` connection — the sole source of price data
    for the screening pipeline (never a third-party HTTP price API)."""

    ib: Any

    def fetch_daily_bars(self, symbol: str) -> list[DailyBar]:
        from ib_async import Stock

        contract = Stock(symbol, "SMART", "USD")
        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=HISTORY_DURATION,
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
        )
        return [DailyBar(trading_date=b.date, close=b.close) for b in bars]

    def fetch_live_price(self, symbol: str) -> float:
        from ib_async import Stock

        contract = Stock(symbol, "SMART", "USD")
        # reqMktData hashes the contract by conId internally to track the ticker —
        # an unqualified contract has no conId yet and raises ValueError on that hash
        # (confirmed empirically against the real Gateway). qualifyContracts fills it
        # in; reqHistoricalData/reqContractDetails above don't need this, only
        # reqMktData's ticker-tracking does.
        self.ib.qualifyContracts(contract)
        ticker = self.ib.reqMktData(contract)
        return float(ticker.last)

    def fetch_session_reference(self, symbol: str = "SPY") -> tuple[str, str]:
        """Returns (liquidHours, timeZoneId) from IBKR's own ContractDetails for
        `symbol` — the raw material `pricing.session.determine_session_state` parses
        to classify REQ-005's session state. Defaults to SPY as a single reference
        for "is the US market open right now", since every candidate here trades on
        the same major US exchanges' shared regular session."""
        from ib_async import Stock

        contract = Stock(symbol, "SMART", "USD")
        details = self.ib.reqContractDetails(contract)
        if not details:
            raise ValueError(f"IBKR reqContractDetails returned no contract for {symbol!r}")
        return details[0].liquidHours, details[0].timeZoneId
