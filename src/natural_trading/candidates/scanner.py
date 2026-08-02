"""REQ-007: candidate sourcing from the IBKR scanner — batched, deduplicated, major US
exchanges, USD only, stop at 9 qualifying stocks or scan codes exhausted. REQ-008:
rights, warrants, and ETFs excluded from the candidate pool before pattern-matching.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Protocol

EXCLUDED_STOCK_TYPES = {"RIGHT", "WARRANT", "ETF"}

# Order matters: broad/liquid rankings first, more niche ones as fallback depth. A
# single scanner subscription caps at 50 rows on this account regardless of
# numberOfRows (preliminary/find_lunar_stocks.py), so batches of 100 are built by
# combining distinct scan rankings.
SCAN_CODES = [
    "MOST_ACTIVE",
    "HOT_BY_VOLUME",
    "TOP_TRADE_COUNT",
    "TOP_TRADE_RATE",
    "TOP_PERC_GAIN",
    "TOP_PERC_LOSE",
]
BATCH_SIZE = 100
TARGET_COUNT = 9


class ScannerClient(Protocol):
    def scan(self, scan_code: str, location_code: str, currency: str) -> list[str]: ...

    def stock_type(self, symbol: str) -> str: ...


def is_excluded_stock_type(stock_type: str) -> bool:
    return stock_type in EXCLUDED_STOCK_TYPES


def filter_excluded(client: ScannerClient, symbols: Iterable[str]) -> list[str]:
    return [s for s in symbols if not is_excluded_stock_type(client.stock_type(s))]


def pull_fresh_batch(
    client: ScannerClient,
    seen: set[str],
    scan_codes: Iterator[str],
    batch_size: int = BATCH_SIZE,
) -> list[str]:
    """Draws from the shared `scan_codes` iterator until `batch_size` symbols not
    already in `seen` are collected, or the scan codes are exhausted."""
    batch: list[str] = []
    for scan_code in scan_codes:
        for symbol in client.scan(scan_code, location_code="STK.US.MAJOR", currency="USD"):
            if symbol in seen:
                continue
            seen.add(symbol)
            batch.append(symbol)
            if len(batch) >= batch_size:
                return batch
    return batch


def run_candidate_search(
    client: ScannerClient,
    qualifies: Callable[[str], bool],
    scan_codes: Sequence[str] = tuple(SCAN_CODES),
    batch_size: int = BATCH_SIZE,
    target_count: int = TARGET_COUNT,
) -> list[str]:
    """REQ-007: pulls fresh batches (deduplicated, STK.US.MAJOR/USD), filters excluded
    stock types (REQ-008), and screens each remaining candidate via `qualifies` until
    `target_count` qualifying symbols are found or the scan codes are exhausted."""
    found: list[str] = []
    seen: set[str] = set()
    cursor = iter(scan_codes)
    while True:
        batch = pull_fresh_batch(client, seen, cursor, batch_size)
        if not batch:
            break
        for symbol in filter_excluded(client, batch):
            if qualifies(symbol):
                found.append(symbol)
                if len(found) >= target_count:
                    return found
    return found
