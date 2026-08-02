"""
Preliminary concept test — NOT the production system.

Measures how fast we can find 3 "lunar stock" candidates by:
  1. Pulling 100 fresh liquid US tickers per iteration. A single IBKR scanner
     subscription is capped at 50 rows regardless of `numberOfRows` (a market-data
     permission limit on this account, confirmed empirically), so each iteration
     combines multiple distinct scan rankings (MOST_ACTIVE, HOT_BY_VOLUME, etc.),
     deduplicated against every symbol already seen, until 100 fresh symbols are
     collected or the scan-code list is exhausted.
  2. Fetching each candidate's close prices on the 4 main lunar-phase days of the most
     recently completed lunar cycle (New Moon, First Quarter, Full Moon, Last Quarter),
     plus the price on the last real New Moon (V) — this run assumes "now" is exactly
     that instant, using the coordinates in ../coordinates.input to resolve local dates.
  3. Determining the active season (BUY: Winter Solstice -> Summer Solstice, SELL: Summer
     Solstice -> Winter Solstice) from the same "last New Moon" instant, and checking ONLY
     the pattern for that season (BUY: X<Y<Z, Z>W>V | SELL: X>Y>Z, Z<W<V) — not both.
  4. Stopping as soon as 9 candidates match the active season's pattern.

The pattern check here is a plain deterministic function, on purpose — this script exists
to time-test the scanner/data-fetch pipeline, not to validate the production screening
logic. Per INSTRUCTIONS.md, the real system replaces this specific check with LLM
reasoning; everything else (scanning, historical data fetch, weekend/holiday fallback) is
legitimately ordinary code in both the prototype and the final system.

Symbols with no close bar yet for V's date (today) are discarded rather than falling back
to a live price quote — simpler and faster for this prototype; see README for the tradeoff.

Assumes an IB Gateway (or TWS) is already running locally in paper trading mode.
"""

import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import ephem
from ib_async import IB, ScannerSubscription, Stock

HOST = "127.0.0.1"
PORT = 4002          # IB Gateway paper trading default
CLIENT_ID = 7

BATCH_SIZE = 100      # candidates pulled fresh each iteration
MAX_ITERATIONS = 10   # safety cap
TARGET_COUNT = 9

HISTORY_DURATION = "45 D"  # comfortably covers one lunar cycle (~29.5 days) + fallback slack

EXCLUDED_STOCK_TYPES = {"RIGHT", "WARRANT", "ETF"}

# A single scanner subscription caps out at 50 rows on this account regardless of
# numberOfRows, so batches of 100 are built by combining distinct scan rankings.
# Order matters: broad/liquid rankings first, more niche ones as fallback depth.
SCAN_CODES = [
    "MOST_ACTIVE",
    "HOT_BY_VOLUME",
    "TOP_TRADE_COUNT",
    "TOP_TRADE_RATE",
    "TOP_PERC_GAIN",
    "TOP_PERC_LOSE",
]
# Not artificially capped in the request — IBKR previously returned only 50 rows per
# scan regardless of the requested number (confirmed empirically, likely a market-data
# permission limit on this account), but we ask for the full pool rather than pre-limiting.
SCANNER_ROW_CAP = 1000

COORDINATES_FILE = Path(__file__).resolve().parent.parent / "coordinates.input"


def read_coordinates(path: Path) -> tuple[float, float]:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = float(val.strip())
    return values["latitude"], values["longitude"]


def local_date_of(instant: "ephem.Date", longitude_deg: float) -> date:
    """Local calendar date via longitude-based mean solar time offset (no timezone DB
    needed — matches INSTRUCTIONS.md's 'day of' rule being tied to configured coordinates)."""
    offset_hours = longitude_deg / 15.0
    return (instant.datetime() + timedelta(hours=offset_hours)).date()


@dataclass
class PhaseDates:
    x_date: date  # former New Moon
    y_date: date  # First Quarter
    z_date: date  # Full Moon
    w_date: date  # Last Quarter
    v_date: date  # today (next New Moon reference point)
    season: str   # "BUY" or "SELL" — active at the V instant


def determine_season(instant) -> str:
    """BUY season: Winter Solstice -> Summer Solstice. SELL season: Summer Solstice ->
    Winter Solstice. Determined by whichever solstice most recently preceded `instant`."""
    last_winter = ephem.previous_winter_solstice(instant)
    last_summer = ephem.previous_summer_solstice(instant)
    return "BUY" if last_winter > last_summer else "SELL"


def compute_phase_dates(longitude_deg: float) -> PhaseDates:
    """Assumes we are exactly at the instant of the most recent real New Moon (V) —
    all phase dates are converted to the local calendar date implied by `longitude_deg`."""
    now = ephem.now()
    v = ephem.previous_new_moon(now)      # the last New Moon's exact instant
    x = ephem.previous_new_moon(v - 1)    # the New Moon before that one
    y = ephem.next_first_quarter_moon(x)
    z = ephem.next_full_moon(x)
    w = ephem.next_last_quarter_moon(x)
    return PhaseDates(
        x_date=local_date_of(ephem.Date(x), longitude_deg),
        y_date=local_date_of(ephem.Date(y), longitude_deg),
        z_date=local_date_of(ephem.Date(z), longitude_deg),
        w_date=local_date_of(ephem.Date(w), longitude_deg),
        v_date=local_date_of(ephem.Date(v), longitude_deg),
        season=determine_season(v),
    )


def closest_close_on_or_before(bars, target: date):
    """Weekend/holiday fallback: last available close on or before `target`."""
    candidates = [b for b in bars if b.date <= target]
    if not candidates:
        return None
    return max(candidates, key=lambda b: b.date).close


def fetch_prices(ib: IB, symbol: str, phases: PhaseDates):
    contract_details = ib.reqContractDetails(Stock(symbol, "SMART", "USD"))
    if not contract_details:
        return None  # unresolvable symbol (delisted, wrong exchange, etc.)

    details = contract_details[0]
    if details.stockType in EXCLUDED_STOCK_TYPES:
        return None  # rights/warrants: tiny prices make the pattern trivially easy to satisfy

    contract = details.contract
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=HISTORY_DURATION,
        barSizeSetting="1 day",
        whatToShow="TRADES",
        useRTH=True,
    )
    if not bars:
        return None

    x = closest_close_on_or_before(bars, phases.x_date)
    y = closest_close_on_or_before(bars, phases.y_date)
    z = closest_close_on_or_before(bars, phases.z_date)
    w = closest_close_on_or_before(bars, phases.w_date)

    v_bar = next((b for b in bars if b.date == phases.v_date), None)
    if v_bar is None:
        return None  # no close for V's date yet — discard rather than fetch a live price
    v = v_bar.close

    if None in (x, y, z, w, v):
        return None
    return x, y, z, w, v


def matches_buy_pattern(x, y, z, w, v) -> bool:
    return x < y < z and z > w and w > v


def matches_sell_pattern(x, y, z, w, v) -> bool:
    return x > y > z and z < w and w < v


def scan_one_code(ib: IB, scan_code: str) -> list[str]:
    sub = ScannerSubscription(
        instrument="STK",
        locationCode="STK.US.MAJOR",
        scanCode=scan_code,
        numberOfRows=SCANNER_ROW_CAP,
    )
    results = ib.reqScannerData(sub)
    return [r.contractDetails.contract.symbol for r in results]


def pull_fresh_batch(ib: IB, seen: set[str], scan_code_cursor, batch_size: int) -> list[str]:
    """Draws from `scan_code_cursor` (a shared iterator over SCAN_CODES) until `batch_size`
    symbols not already in `seen` are collected, or the scan codes are exhausted."""
    batch = []
    for scan_code in scan_code_cursor:
        for symbol in scan_one_code(ib, scan_code):
            if symbol in seen:
                continue
            seen.add(symbol)
            batch.append(symbol)
            if len(batch) >= batch_size:
                return batch
    return batch


def main():
    latitude, longitude = read_coordinates(COORDINATES_FILE)
    print(f"Coordinates: {latitude}, {longitude} (from {COORDINATES_FILE})")

    phases = compute_phase_dates(longitude)
    print(f"Assuming 'now' = the exact instant of the last New Moon.")
    print(f"Phase dates (former cycle): X={phases.x_date} Y={phases.y_date} "
          f"Z={phases.z_date} W={phases.w_date} | V(last New Moon)={phases.v_date}")
    print(f"Active season: {phases.season} "
          f"({'LONG/BUY' if phases.season == 'BUY' else 'SHORT/SELL'} orders only)")

    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID)

    t_start = time.monotonic()
    found = []
    checked = 0
    seen: set[str] = set()
    scan_code_cursor = iter(SCAN_CODES)

    for iteration in range(1, MAX_ITERATIONS + 1):
        iter_start = time.monotonic()
        batch = pull_fresh_batch(ib, seen, scan_code_cursor, BATCH_SIZE)

        if not batch:
            print(f"Iteration {iteration}: scan codes exhausted at {len(seen)} symbols total, stopping.")
            break
        if len(batch) < BATCH_SIZE:
            print(f"Iteration {iteration}: only {len(batch)} fresh symbols left "
                  f"(scan codes nearly exhausted).")

        iter_checked = 0
        for symbol in batch:
            checked += 1
            iter_checked += 1
            prices = fetch_prices(ib, symbol, phases)
            if prices is None:
                continue
            x, y, z, w, v = prices
            matches = (matches_buy_pattern(x, y, z, w, v) if phases.season == "BUY"
                       else matches_sell_pattern(x, y, z, w, v))
            if matches:
                found.append((symbol, phases.season, x, y, z, w, v))

            if len(found) >= TARGET_COUNT:
                break

        iter_elapsed = time.monotonic() - iter_start
        print(f"Iteration {iteration}: checked {iter_checked} of {len(batch)} pulled symbols "
              f"in {iter_elapsed:.2f}s | total found so far: {len(found)}")

        if len(found) >= TARGET_COUNT:
            break

    t_end = time.monotonic()
    print(f"\nChecked {checked} symbols total in {t_end - t_start:.2f}s")
    print(f"Found {len(found)} qualifying lunar stock(s):")
    for symbol, direction, x, y, z, w, v in found:
        print(f"  {symbol:8s} {direction:4s}  X={x} Y={y} Z={z} W={w} V={v}")

    ib.disconnect()


if __name__ == "__main__":
    main()
