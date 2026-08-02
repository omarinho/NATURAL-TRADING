# Preliminary concept test

Not the production system — a throwaway script to measure how fast the pipeline
(IBKR scanner → historical price fetch → pattern check) can find 3 candidate "lunar
stocks." The pattern check here is plain code, on purpose, purely to time-test the
surrounding mechanics; the production system replaces that specific check with LLM
reasoning (see `../../Agentic/inputs/INSTRUCTIONS.md`).

## Setup

1. Have IB Gateway (or TWS) running locally in **paper trading** mode, API access
   enabled, on the default paper port (`4002` for Gateway, `7497` for TWS — the script
   defaults to `4002`, edit `PORT` in `find_lunar_stocks.py` if you're using TWS).
2. `pip install -r requirements.txt`

## Run

```bash
python find_lunar_stocks.py
```

Prints the computed lunar phase dates, per-iteration scan+screening timing (100 fresh
symbols per iteration), and the first 3 qualifying symbols found (or however many turned
up before hitting `MAX_ITERATIONS`).

## Known simplifications (prototype only)

- Assumes "now" is exactly the instant of the most recent real New Moon, rather than
  waiting for an actual one — for a first speed test we don't need to wait for the sky.
- Season (BUY vs SELL) is derived from the same instant via the most recent solstice, and
  only that season's pattern is checked — matching the production rule.
- A single IBKR scanner subscription caps at 50 rows on this account regardless of
  `numberOfRows` (confirmed empirically), so each 100-symbol batch is built by combining
  multiple distinct scan codes (`SCAN_CODES` in the script), deduplicated against every
  symbol already seen across the whole run.
- Symbols with no close bar yet for V's date (today) are discarded, not resolved via a
  live price quote — faster and avoids the "delayed data" subscription errors/latency the
  live-ticker fallback hit in testing, at the cost of skipping legitimately-still-open
  candidates. Fine for a speed test; the production system needs a real decision here
  (discard vs. live price vs. wait for close) since a real run happens at a specific
  instant, not after the fact.
