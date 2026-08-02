"""Entrypoint: `python -m natural_trading.main`.

Wires configuration (coordinates.input, anthropic.input, ibkr.input at the repo root)
to the astro source, the IBKR Gateway connection, and the Anthropic screening client,
then runs the perpetual scheduling loop: compute the next New Moon/Full Moon trigger
via `scheduler.next_trigger_instant`, sleep until it fires, then dispatch to a New
Moon cycle (candidate search -> screening -> live sizing -> order submission) or a
Full Moon cycle (fetch live positions -> close everything).

Deliberately synchronous, not asyncio-based: every concrete IBKR client here
(IBAccountClient, IBPriceClient, IBScannerClient, IBOrderSubmitter) uses ib_async's
synchronous API (e.g. `ib.reqHistoricalData()`), which internally runs its own nested
event loop via `ib_async.util.run()`. Calling that from inside an already-running
`asyncio.run()` loop raises "This event loop is already running" — confirmed against
the real Gateway. `ib.connect()` (sync) and `ib.sleep()` (which "keeps processing in
the background" per its own docstring, unlike `time.sleep()`) are the correct pairing
for a long-running wait without blocking IBKR's message pump.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from ib_async import IB

from natural_trading.account.ibkr_account import IBAccountClient
from natural_trading.astro.base import AstroSource, MoonPhase
from natural_trading.astro.combined import CombinedAstroSource
from natural_trading.astro.ephem_source import EphemSource
from natural_trading.astro.season import determine_season, is_solstice_straddling_cycle
from natural_trading.astro.usno import UsnoSource
from natural_trading.candidates.scanner import run_candidate_search
from natural_trading.config import (
    Coordinates,
    load_anthropic_config,
    load_coordinates,
    load_ibkr_config,
)
from natural_trading.ib_order_submitter import IBOrderSubmitter
from natural_trading.ib_scanner_client import IBScannerClient
from natural_trading.pricing.ibkr_prices import IBPriceClient
from natural_trading.pricing.pipeline import resolve_symbol_phase_prices
from natural_trading.pricing.session import determine_session_state
from natural_trading.scheduler import (
    resolve_next_action,
    run_full_moon_cycle,
    run_new_moon_cycle_live,
)
from natural_trading.screening.anthropic_client import LiveAnthropicClient
from natural_trading.screening.llm_screen import screen_candidate
from natural_trading.state import load_last_processed_trigger, save_last_processed_trigger

REPO_ROOT = Path(__file__).resolve().parents[2]
COORDINATES_FILE = REPO_ROOT / "coordinates.input"
ANTHROPIC_FILE = REPO_ROOT / "anthropic.input"
IBKR_FILE = REPO_ROOT / "ibkr.input"
TRIGGER_STATE_FILE = REPO_ROOT / "last_trigger.state"

logger = logging.getLogger(__name__)


def build_astro_source(coordinates: Coordinates) -> CombinedAstroSource:
    # REQ-018: coordinates is threaded through to both backends so the configured
    # location genuinely flows end-to-end (see UsnoSource/EphemSource docstrings for
    # why it does not alter these specific geocentric instant computations).
    return CombinedAstroSource(
        primary=UsnoSource(coordinates=coordinates),
        fallback=EphemSource(coordinates=coordinates),
    )


def build_account_client(ib: IB) -> IBAccountClient:
    return IBAccountClient(ib=ib)


def run_new_moon_trigger(
    trigger_instant: datetime,
    astro: AstroSource,
    coordinates: Coordinates,
    price_client: IBPriceClient,
    scanner_client: IBScannerClient,
    llm_client: LiveAnthropicClient,
    account: IBAccountClient,
    submitter: IBOrderSubmitter,
) -> None:
    following_full = astro.moon_phase_after(trigger_instant, MoonPhase.FULL)
    if is_solstice_straddling_cycle(trigger_instant, following_full, astro):
        logger.info(
            "New Moon at %s starts a solstice-straddling cycle — skipped, staying in cash.",
            trigger_instant,
        )
        return

    season = determine_season(trigger_instant, astro)
    liquid_hours, timezone_id = price_client.fetch_session_reference()
    session_state = determine_session_state(liquid_hours, timezone_id, datetime.now(UTC))
    logger.info(
        "New Moon trigger at %s — season=%s, session_state=%s",
        trigger_instant,
        season,
        session_state,
    )

    # Populated as a side effect of qualifies() below: each qualifying symbol's V
    # (today's New Moon price) is captured at screening time and reused for sizing,
    # rather than fetching a separately-timed live quote later (see
    # scheduler.run_new_moon_cycle_live's docstring for why that matters).
    qualifying_prices: dict[str, float] = {}

    def qualifies(symbol: str) -> bool:
        prices = resolve_symbol_phase_prices(
            symbol, trigger_instant, astro, coordinates, price_client, session_state
        )
        if prices is None:
            return False
        result = screen_candidate(llm_client, symbol, prices, season)
        if result:
            qualifying_prices[symbol] = prices.v
        return result

    qualifying_symbols = run_candidate_search(scanner_client, qualifies)
    logger.info("Found %d qualifying symbols: %s", len(qualifying_symbols), qualifying_symbols)

    equity = account.fetch_net_liquidation()
    result = run_new_moon_cycle_live(
        new_moon_instant=trigger_instant,
        following_full_moon_instant=following_full,
        astro=astro,
        qualifying_symbols=qualifying_symbols,
        equity=equity,
        prices=qualifying_prices,
        account=account,
        submitter=submitter,
    )
    logger.info("New Moon cycle complete — %d orders submitted.", len(result.orders_submitted))


def run_full_moon_trigger(account: IBAccountClient, submitter: IBOrderSubmitter) -> None:
    # REQ-021/REQ-010: fetched live rather than carried in memory from the New Moon
    # cycle, so a process restart in between still closes the real open positions.
    open_positions = account.fetch_positions()
    orders = run_full_moon_cycle(open_positions, submitter)
    logger.info("Full Moon cycle complete — %d closing orders submitted.", len(orders))


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    coordinates = load_coordinates(COORDINATES_FILE)
    anthropic_config = load_anthropic_config(ANTHROPIC_FILE)
    ibkr_config = load_ibkr_config(IBKR_FILE)
    logger.info("Loaded coordinates: %s, %s", coordinates.latitude, coordinates.longitude)

    llm_client = LiveAnthropicClient(api_key=anthropic_config.api_key)
    logger.info("Anthropic client ready: %s", type(llm_client).__name__)

    astro = build_astro_source(coordinates)
    logger.info("Astro source ready: %s", type(astro).__name__)

    ib = IB()
    ib.connect(ibkr_config.host, ibkr_config.port, clientId=ibkr_config.client_id)
    logger.info(
        "Connected to IBKR Gateway at %s:%s (clientId=%s)",
        ibkr_config.host,
        ibkr_config.port,
        ibkr_config.client_id,
    )

    account = build_account_client(ib)
    price_client = IBPriceClient(ib=ib)
    scanner_client = IBScannerClient(ib=ib)
    submitter = IBOrderSubmitter(ib=ib)

    last_processed = load_last_processed_trigger(TRIGGER_STATE_FILE)
    if last_processed is not None:
        logger.info("Last processed trigger on disk: %s", last_processed)

    try:
        logger.info("Natural Trading scheduler ready — entering perpetual loop.")
        while True:
            now = datetime.now(UTC)
            trigger_instant, phase = resolve_next_action(now, astro, last_processed)
            sleep_seconds = (trigger_instant - datetime.now(UTC)).total_seconds()
            if sleep_seconds > 0:
                logger.info(
                    "Sleeping %.0fs until next trigger at %s (%s)",
                    sleep_seconds,
                    trigger_instant,
                    phase,
                )
                ib.sleep(sleep_seconds)
            else:
                # resolve_next_action returned a trigger already in the past -- a
                # cold start caught up on one within CATCH_UP_WINDOW rather than
                # skipping to the next one ~14.75 days away.
                logger.info(
                    "Catching up on trigger at %s (%s) — %.0fs after its exact instant.",
                    trigger_instant,
                    phase,
                    -sleep_seconds,
                )

            if phase is MoonPhase.NEW:
                run_new_moon_trigger(
                    trigger_instant,
                    astro,
                    coordinates,
                    price_client,
                    scanner_client,
                    llm_client,
                    account,
                    submitter,
                )
            else:
                run_full_moon_trigger(account, submitter)

            save_last_processed_trigger(TRIGGER_STATE_FILE, trigger_instant)
            last_processed = trigger_instant
    finally:
        ib.disconnect()


if __name__ == "__main__":
    main()
