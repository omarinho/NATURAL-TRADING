# Natural Trading

A fully rule-based, astronomically-timed swing trading system over Interactive
Brokers. Trades are opened and closed on lunar phase days, with the trade direction
(long/short) determined by the solstice-defined season — no technical indicators, no
discretionary calls.

> **Status:** business logic complete and fully tested (149/149 tests, 22/22
> requirements). `main.py` wires the full perpetual scheduling loop plus live IBKR
> scanner/pricing/account/order-submitter implementations end-to-end — it has not
> been run against a live Gateway yet. See
> [Before going live](#before-going-live) for the one open item to confirm first.

## How the strategy works

### Seasons

- **BUY season** — from the exact instant of the **Winter Solstice** to the following
  **Summer Solstice**: the system opens **long** positions.
- **SELL season** — from the exact instant of the **Summer Solstice** to the following
  **Winter Solstice**: the system opens **short** positions.

Season boundaries come from real solstice instants (via the astro source, see below),
never a hardcoded calendar date.

### Trading cadence

- Open positions in qualifying "lunar stocks" on the day of **New Moon**.
- Close all open positions on the day of the following **Full Moon**.
- Hold 100% cash from Full Moon until the next New Moon.
- A lunar cycle that straddles a solstice (New Moon in one season, Full Moon in the
  next) is **skipped entirely** — no position is opened, the system just stays in cash
  for that cycle.

### What makes a stock a "lunar stock"

For the immediately preceding completed lunar cycle, take the close price on each of
the 4 main phase days:

- `X` = close on the former New Moon
- `Y` = close on the following First Quarter
- `Z` = close on the following Full Moon
- `W` = close on the following Last Quarter
- `V` = price on today's New Moon (close if the session has ended, otherwise the live
  price; last available close if there's no session at all that day)

A stock qualifies if:

- **BUY season:** `X < Y < Z`, then `Z > W`, then `W > V`
- **SELL season:** `X > Y > Z`, then `Z < W`, then `W < V`

This comparison is deliberately **not** a coded numeric filter — it's performed by an
LLM (Claude, via the Anthropic Messages API) reading and reasoning over the five
prices, to avoid the class of bugs (off-by-one, silent parsing errors) a hand-written
comparison script is prone to. See [`screening/llm_screen.py`](src/natural_trading/screening/llm_screen.py);
a static test (`test_screening_module_has_no_deterministic_xyzwv_comparison`) fails the
build if a numeric X/Y/Z/W/V comparison is ever added to that module.

Weekend/holiday phase days fall back to the most recent prior session's close.

### Candidate sourcing

Candidates come from IBKR's market scanner (most active by volume, top trade
count/rate, top gainers/losers, ...), pulled 100 at a time and deduplicated, until **9
qualifying lunar stocks** are found or the scanner categories are exhausted. Scoped to
major US exchanges, USD only. Rights, warrants, and ETFs are excluded before the
pattern check ever sees them.

### Position sizing — no stops

This build is a deliberate experiment: **no protective stop orders of any kind.**
Positions are held unsupervised for the full New Moon → Full Moon window; the only
exit is the scheduled Full Moon close.

- **Equal-weight:** capital is split evenly across the N qualifying stocks (`1/N`
  each).
- **20% single-position cap** — excess is left unused, not redistributed.
- **Buying-power check:** current buying power / short-sale availability is fetched
  live from IBKR immediately before every order, never a cached figure.

### Orders

- **MARKET orders only** — both opening and closing. No LIMIT orders: guaranteed
  entry/exit on schedule matters more here than fill price.
- Submitted **immediately** at the exact New Moon / Full Moon instant, regardless of
  market hours — a MARKET order placed while the market is closed simply executes at
  the next session's open.

## Architecture

```
src/natural_trading/
  astro/          Astronomical event sourcing (solstices, moon phases)
    base.py         AstroSource protocol, MoonPhase / SolsticeKind enums
    usno.py         Primary: USNO Astronomical Applications API (free, no key)
    ephem_source.py Fallback: offline `ephem` library
    combined.py     CombinedAstroSource — tries primary, falls back on any error
    season.py       Season detection + solstice-straddle detection
  pricing/         X/Y/Z/W/V price resolution
    session.py      Trading-session state classification
    resolver.py     Weekend/holiday fallback, local-day resolution from coordinates
    ibkr_prices.py  IBKR-only historical/live price client (IBPriceClient)
  candidates/
    scanner.py      IBKR scanner batching, dedup, rights/warrants/ETF exclusion
  screening/       The zero-scripts LLM pattern check
    llm_screen.py       Prompt-building + response parsing, no numeric comparison
    anthropic_client.py Live Anthropic Messages API client
  sizing.py        Equal-weight sizing, 20% cap, buying-power check
  orders.py        MARKET-only opening/closing order builders
  state.py         Full Moon -> New Moon cash-holding window logic
  account/
    ibkr_account.py Live (uncached) IBKR buying-power fetch
  scheduler.py     Ties it all together: next-trigger computation, New Moon / Full
                   Moon cycle runners
  config.py        Loads coordinates.input / anthropic.input / ibkr.input
  main.py          Entrypoint — wires everything; scheduling loop is a documented TODO

tests/             149 pytest tests, one file per module above
preliminary/       Reference-only prototype (find_lunar_stocks.py) used to validate
                   IBKR scanner mechanics during research — not production code
```

### Astronomical data source

[USNO Astronomical Applications API](https://aa.usno.navy.mil/data/api) — free, no API
key, single authoritative source for both moon-phase and solstice/equinox data — with
the offline `ephem` library as a fallback if USNO is unreachable. `CombinedAstroSource`
tries USNO first and falls back automatically, logging which source served each
instant.

Solstice and moon-phase instants are **geocentric** (location-independent) for both
backends, so `coordinates.input` does not (and should not) change *when* those events
occur. What coordinates *do* control is the local-time "day of" boundary used to
resolve weekend/holiday phase prices (`pricing/resolver.py`'s `local_date_of`) — e.g.
whether a given UTC instant falls on a Saturday in Bogotá.

## Configuration

Three `key=value` files at the repo root, read at runtime (never hardcoded). Only
`anthropic.input` holds a secret and is gitignored; `coordinates.input` and
`ibkr.input` contain no sensitive data and are committed with safe paper-trading
defaults:

**`coordinates.input`** — geographic coordinates used for local-day resolution.
```
latitude=4.73104
longitude=-74.0417
```

**`ibkr.input`** — IBKR Gateway/TWS connection. Migrating from paper to a live account
is a config change (port), not a code change.
```
host=127.0.0.1
port=4002
client_id=7
```

**`anthropic.input`** — Anthropic API key for the LLM screening step. Gitignored;
never commit a real key.
```
api_key=REPLACE_WITH_YOUR_ANTHROPIC_API_KEY
```

## Setup

Requires Python 3.11+ and a running IBKR Gateway/TWS with a paper trading account.

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -e ".[dev]"
```

Fill in `anthropic.input` with a real Anthropic API key before running anything that
touches the screening step.

## Running tests

```bash
pytest -v          # 149 tests
ruff check .        # lint
mypy .              # type check
black --check .     # format check
```

## Implementation status

The business logic (season/pattern detection, sizing, order construction,
buying-power fetch) and the live IBKR wiring are both fully implemented and unit
tested:

- `main.py`'s perpetual scheduling loop — computes the next trigger instant, sleeps
  until it fires via `ib.sleep()`, and dispatches to `scheduler.run_new_moon_cycle_live`
  / `run_full_moon_cycle`.
- Concrete `IBScannerClient` / `IBOrderSubmitter` / `IBPriceClient` /
  `IBAccountClient` implementations wired against a real IBKR Gateway connection (the
  scanner and order-submission code is also written against protocols and covered with
  fakes in tests).
- The pipeline-assembly step (`pricing/pipeline.py`) that turns raw IBKR historical
  bars into `PhasePrices`, calling `pricing/resolver.py`'s
  `resolve_phase_price_for_instant` / `resolve_v_price_for_instant`.

None of this has been exercised end-to-end against a live IBKR Gateway yet — the test
suite covers it with fakes, not a real connection.

## Before going live

Confirm IBKR's unified `BuyingPower` account-summary tag is an
acceptable proxy for short-sale-specific buying power on your account type (see the
comment in `account/ibkr_account.py::fetch_short_sale_buying_power`) — the IBKR API
exposes no distinct short-sale-availability dollar tag on a standard margin account.
