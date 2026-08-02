"""Covers the live IBKR scanner boundary: scan() must translate a scan code into a
real ib_async reqScannerData() call and extract symbols; stock_type() must resolve a
symbol's type via reqContractDetails(). Mirrors tests/test_ibkr_account.py's "wrap a
mocked ib_async IB connection" pattern.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from natural_trading.ib_scanner_client import IBScannerClient


def _scan_result(symbol: str) -> MagicMock:
    result = MagicMock()
    result.contractDetails.contract.symbol = symbol
    return result


def test_scan_calls_req_scanner_data_and_extracts_symbols() -> None:
    mock_ib = MagicMock()
    mock_ib.reqScannerData.return_value = [_scan_result("AAA"), _scan_result("BBB")]
    client = IBScannerClient(ib=mock_ib)

    result = client.scan("MOST_ACTIVE", location_code="STK.US.MAJOR", currency="USD")

    assert result == ["AAA", "BBB"]
    mock_ib.reqScannerData.assert_called_once()


def test_scan_subscription_uses_given_scan_code_and_location() -> None:
    mock_ib = MagicMock()
    mock_ib.reqScannerData.return_value = []
    client = IBScannerClient(ib=mock_ib)

    client.scan("TOP_PERC_GAIN", location_code="STK.US.MAJOR", currency="USD")

    (subscription,), _ = mock_ib.reqScannerData.call_args
    assert subscription.scanCode == "TOP_PERC_GAIN"
    assert subscription.locationCode == "STK.US.MAJOR"
    assert subscription.instrument == "STK"


def test_scan_returns_empty_list_when_no_results() -> None:
    mock_ib = MagicMock()
    mock_ib.reqScannerData.return_value = []
    client = IBScannerClient(ib=mock_ib)

    assert client.scan("MOST_ACTIVE", location_code="STK.US.MAJOR", currency="USD") == []


def test_stock_type_returns_type_from_contract_details() -> None:
    mock_ib = MagicMock()
    details = MagicMock()
    details.stockType = "COMMON"
    mock_ib.reqContractDetails.return_value = [details]
    client = IBScannerClient(ib=mock_ib)

    assert client.stock_type("AAPL") == "COMMON"
    mock_ib.reqContractDetails.assert_called_once()


def test_stock_type_raises_clear_error_when_symbol_unresolvable() -> None:
    mock_ib = MagicMock()
    mock_ib.reqContractDetails.return_value = []
    client = IBScannerClient(ib=mock_ib)

    with pytest.raises(ValueError, match="AAPL"):
        client.stock_type("AAPL")
