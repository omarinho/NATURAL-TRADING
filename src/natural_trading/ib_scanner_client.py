"""REQ-007: the live IBKR market-scanner boundary behind `candidates/scanner.py`'s
`ScannerClient` protocol. Mirrors account/ibkr_account.py's pattern: a thin dataclass
wrapper over an ib_async `IB` connection, holding no cached state of its own. Scanner
mechanics (locationCode, the 50-row-per-subscription cap on this account, contract
details for stock type) were validated in preliminary/find_lunar_stocks.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Not artificially capped in the request — IBKR previously returned only 50 rows per
# scan regardless of the requested number (confirmed empirically in
# preliminary/find_lunar_stocks.py, likely a market-data permission limit on this
# account), but we ask for the full pool rather than pre-limiting.
SCANNER_ROW_CAP = 1000


@dataclass
class IBScannerClient:
    """`currency` is accepted for ScannerClient protocol conformance / call-site
    explicitness — it applies no additional filter here because `location_code`
    "STK.US.MAJOR" already scopes results to USD-denominated major US exchanges
    (same assumption preliminary/find_lunar_stocks.py relied on)."""

    ib: Any

    def scan(self, scan_code: str, location_code: str, currency: str) -> list[str]:
        from ib_async import ScannerSubscription

        subscription = ScannerSubscription(
            instrument="STK",
            locationCode=location_code,
            scanCode=scan_code,
            numberOfRows=SCANNER_ROW_CAP,
        )
        results = self.ib.reqScannerData(subscription)
        return [r.contractDetails.contract.symbol for r in results]

    def stock_type(self, symbol: str) -> str:
        from ib_async import Stock

        contract_details = self.ib.reqContractDetails(Stock(symbol, "SMART", "USD"))
        if not contract_details:
            raise ValueError(f"IBKR reqContractDetails returned no contract for {symbol!r}")
        stock_type: str = contract_details[0].stockType
        return stock_type
