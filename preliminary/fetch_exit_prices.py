import sys
from datetime import date

from ib_async import IB, Stock

HOST = "127.0.0.1"
PORT = 4002
CLIENT_ID = 9

SYMBOLS = ["SCYX", "SM", "WETH", "RYDE", "SHPH", "GCTK", "HOWL", "YYAI", "HUN"]
TARGET = date(2026, 7, 29)


def closest_close_on_or_before(bars, target):
    candidates = [b for b in bars if b.date <= target]
    if not candidates:
        return None
    return max(candidates, key=lambda b: b.date)


def main():
    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID)

    for symbol in SYMBOLS:
        contract_details = ib.reqContractDetails(Stock(symbol, "SMART", "USD"))
        if not contract_details:
            print(f"{symbol}: unresolvable")
            continue
        contract = contract_details[0].contract
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="20260801 00:00:00",
            durationStr="20 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
        )
        bar = closest_close_on_or_before(bars, TARGET)
        if bar is None:
            print(f"{symbol}: no bar found")
            continue
        print(f"{symbol}: date={bar.date} close={bar.close}")

    ib.disconnect()


if __name__ == "__main__":
    main()
