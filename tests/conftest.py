"""All tests are offline; accidental live connections fail immediately."""
import socket

import pytest


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Live network access is forbidden in tests')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)


@pytest.fixture(autouse=True)
def isolate_error_log(monkeypatch, tmp_path):
    monkeypatch.setattr('thebundl.observability.ERROR_LOG', tmp_path / 'pipeline-errors.txt')
    monkeypatch.setattr('thebundl.__main__.ERROR_LOG', tmp_path / 'pipeline-errors.txt')
