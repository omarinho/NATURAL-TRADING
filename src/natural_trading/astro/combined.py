"""Wires the primary (USNO) and fallback (ephem) astro sources together: on any
primary failure (network/timeout/non-2xx error), fall back to the offline source, and
log which source served each computed instant (plan.json astro_source_decision)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from natural_trading.astro.base import AstroSource, MoonPhase, SolsticeKind

logger = logging.getLogger(__name__)


@dataclass
class CombinedAstroSource:
    primary: AstroSource
    fallback: AstroSource

    def solstice_at_or_before(self, instant: datetime, kind: SolsticeKind) -> datetime:
        return self._call("solstice_at_or_before", instant, kind)

    def solstice_after(self, instant: datetime, kind: SolsticeKind) -> datetime:
        return self._call("solstice_after", instant, kind)

    def moon_phase_at_or_before(self, instant: datetime, phase: MoonPhase) -> datetime:
        return self._call("moon_phase_at_or_before", instant, phase)

    def moon_phase_after(self, instant: datetime, phase: MoonPhase) -> datetime:
        return self._call("moon_phase_after", instant, phase)

    def _call(self, method_name: str, *args: object) -> datetime:
        try:
            result: datetime = getattr(self.primary, method_name)(*args)
            logger.info("astro source: USNO served %s%s", method_name, args)
            return result
        except Exception as exc:  # noqa: BLE001 - any primary failure triggers fallback
            logger.warning("astro source: USNO failed (%s) — falling back to ephem", exc)
            fallback_result: datetime = getattr(self.fallback, method_name)(*args)
            logger.info("astro source: ephem served %s%s", method_name, args)
            return fallback_result
