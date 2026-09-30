"""The default suite must never reach the network."""

import socket

import pytest
from pytest_socket import SocketBlockedError


def test_sockets_are_blocked() -> None:
    with (
        pytest.warns(UserWarning, match="socket"),
        pytest.raises(SocketBlockedError),
    ):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
