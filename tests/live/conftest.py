"""Live tests call real APIs and cost money. They run only with `-m live` and need --max-usd."""

from pathlib import Path

import pytest

LIVE_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if LIVE_DIR in item.path.parents:
            item.add_marker(pytest.mark.live)
            item.add_marker(pytest.mark.enable_socket)
