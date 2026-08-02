"""Runtime configuration loaders — coordinates.input, anthropic.input, ibkr.input.

REQ-018 / REQ-020 / REQ-022: geographic coordinates, the Anthropic API key, and the
IBKR connection parameters are all read at runtime from key=value files at the repo
root, never hardcoded, so changing a file (or the configured port for a paper-to-live
migration) changes behavior with no source-code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Default coordinates: Bogota, Colombia — used only when coordinates.input omits a key.
DEFAULT_LATITUDE = 4.73104
DEFAULT_LONGITUDE = -74.0417

DEFAULT_IBKR_HOST = "127.0.0.1"
DEFAULT_IBKR_PORT = 4002
DEFAULT_IBKR_CLIENT_ID = 7


def _parse_key_value_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip()
    return values


@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float


def load_coordinates(path: Path) -> Coordinates:
    values = _parse_key_value_file(path)
    latitude = float(values.get("latitude", DEFAULT_LATITUDE))
    longitude = float(values.get("longitude", DEFAULT_LONGITUDE))
    return Coordinates(latitude=latitude, longitude=longitude)


@dataclass(frozen=True)
class AnthropicConfig:
    api_key: str


def load_anthropic_config(path: Path) -> AnthropicConfig:
    values = _parse_key_value_file(path)
    return AnthropicConfig(api_key=values.get("api_key", ""))


@dataclass(frozen=True)
class IbkrConnectionConfig:
    host: str
    port: int
    client_id: int


def load_ibkr_config(path: Path) -> IbkrConnectionConfig:
    values = _parse_key_value_file(path)
    host = values.get("host", DEFAULT_IBKR_HOST)
    port = int(values.get("port", DEFAULT_IBKR_PORT))
    client_id = int(values.get("client_id", DEFAULT_IBKR_CLIENT_ID))
    return IbkrConnectionConfig(host=host, port=port, client_id=client_id)
