"""REQ-016: the buying-power / short-sale-availability check must query current IBKR
account state immediately before order submission — never a stale/cached value.
`sizing.apply_buying_power_check()` is a pure function of whatever figure it is given;
this module is the missing live-fetch boundary that supplies it one, mirroring
`pricing/ibkr_prices.py`'s `IBPriceClient` pattern (a thin wrapper over an ib_async `IB`
connection, holding no cached state of its own)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BUYING_POWER_TAG = "BuyingPower"
NET_LIQUIDATION_TAG = "NetLiquidation"


@dataclass
class IBAccountClient:
    """Thin wrapper over an ib_async `IB` connection — the sole source of account
    buying-power figures used by the sizing/order-submission pipeline. Every call
    re-queries `ib.accountSummary()`; nothing is cached, so the caller always gets the
    value as of the instant it asks (REQ-016 requires "immediately before submission")."""

    ib: Any

    def fetch_buying_power(self) -> float:
        """Buying power available for new LONG orders, freshly queried on every call."""
        return self._fetch_tag(BUYING_POWER_TAG)

    def fetch_short_sale_buying_power(self) -> float:
        """Buying power available for new SHORT orders, freshly queried on every call.

        Only a rough, upfront sizing signal — NOT an accurate prediction of whether a
        specific short order will be accepted. IBKR's `accountSummary()` reports a
        single unified 'BuyingPower' figure reflecting standard Reg T leverage (4x
        equity in this account), but the API exposes no separate short-sale-specific
        dollar tag, and confirmed empirically against the real paper Gateway: real
        margin requirements for shorting a specific security — especially a
        volatile/low-priced one — can be far higher than this figure suggests (a
        $10,000 BuyingPower reading still had real orders rejected needing $7,890 of
        initial margin against $2,500 of equity). The accurate, per-order check is
        `ib_order_submitter.IBOrderSubmitter.submit()`'s `ib.whatIfOrder()` call
        immediately before each real submission — this method only feeds the coarse
        pre-submission sizing pass in `sizing.apply_buying_power_check`, which still
        catches wildly-oversized requests before they ever reach the real check.
        """
        return self._fetch_tag(BUYING_POWER_TAG)

    def fetch_net_liquidation(self) -> float:
        """Account equity used as the base for REQ-014's equal-weight sizing —
        `sizing.compute_position_sizes`'s `equity` argument, freshly queried on every
        call like the buying-power tags above."""
        return self._fetch_tag(NET_LIQUIDATION_TAG)

    def fetch_positions(self) -> dict[str, float]:
        """Live open-position snapshot (symbol -> signed size, positive=long,
        negative=short) queried directly from IBKR rather than carried in an
        in-memory dict across the New Moon -> Full Moon window — correct even if the
        process restarts in between, since it is never a cached/reused value."""
        return {p.contract.symbol: float(p.position) for p in self.ib.positions()}

    def _fetch_tag(self, tag: str) -> float:
        for account_value in self.ib.accountSummary():
            if account_value.tag == tag:
                return float(account_value.value)
        raise ValueError(f"IBKR accountSummary() returned no {tag!r} value")
