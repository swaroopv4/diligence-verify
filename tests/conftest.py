"""All tests are offline, including tests accidentally trying to open a socket."""
import socket
from pathlib import Path
from uuid import uuid4

import pytest


def pytest_configure(config: pytest.Config) -> None:
    if config.option.basetemp is None:
        # Avoid an inaccessible system pytest temp directory on this Windows host.
        # A fresh path also prevents pytest from deleting another session's files.
        root = Path(__file__).resolve().parents[1]
        scratch = (root / ".pytest-work" / uuid4().hex).resolve()
        if not scratch.is_relative_to(root):
            raise ValueError("Test scratch path must remain in this project")
        scratch.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(scratch)


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("Tests must not use the network; use httpx.MockTransport")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden_connect)
