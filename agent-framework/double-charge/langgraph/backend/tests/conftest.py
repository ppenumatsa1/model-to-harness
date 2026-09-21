import ipaddress
import os
import socket

import pytest
from model_to_harness_langgraph.config import Settings, get_settings
from psycopg.conninfo import conninfo_to_dict


def pytest_sessionstart(session):
    database = os.getenv("TEST_DATABASE_URL")
    if database:
        parameters = conninfo_to_dict(database)
        if (
            parameters.get("host") not in {"localhost", "127.0.0.1", "::1"}
            or parameters.get("hostaddr", "127.0.0.1") not in {"127.0.0.1", "::1"}
            or parameters.get("service")
            or not parameters.get("dbname")
        ):
            raise pytest.UsageError("TEST_DATABASE_URL must select a dedicated loopback database")


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    for variable in ("PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("TELEMETRY_ENABLED", "false")
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    connect = socket.socket.connect

    def local_only(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            host = address[0]
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = host == "localhost"
            if not loopback:
                raise AssertionError("Tests must not connect to external services")
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
    yield
    get_settings.cache_clear()
