"""Account-state clients — currently a single IBKR buying-power/short-sale-availability
client (REQ-016). Kept as its own package (distinct from `pricing/`, which sources
phase-price data) because it answers a different question: not "what did a symbol
trade at", but "what can the account currently afford"."""
