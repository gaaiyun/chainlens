from __future__ import annotations

import pytest

from chainlens.warehouse.mysql import (
    MySQLSettings,
    configure_mysql_source,
    materialize_analysis_views,
    sql_string,
)


class RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str):
        self.statements.append(statement)
        return self


def test_mysql_settings_are_disabled_without_host(monkeypatch) -> None:
    for key in (
        "DB_HOST_SCENARIO_1_3",
        "DB_PORT_SCENARIO_1_3",
        "DB_NAME_SCENARIO_1_3",
        "DB_USER_SCENARIO_1_3",
        "DB_PASSWORD_SCENARIO_1_3",
    ):
        monkeypatch.delenv(key, raising=False)

    assert MySQLSettings.from_environment() is None


def test_mysql_settings_require_complete_credentials(monkeypatch) -> None:
    monkeypatch.setenv("DB_HOST_SCENARIO_1_3", "db.example.com")
    monkeypatch.delenv("DB_PASSWORD_SCENARIO_1_3", raising=False)

    with pytest.raises(ValueError, match="DB_PASSWORD_SCENARIO_1_3"):
        MySQLSettings.from_environment()


def test_mysql_settings_read_scenario_variables(monkeypatch) -> None:
    monkeypatch.setenv("DB_HOST_SCENARIO_1_3", "db.example.com")
    monkeypatch.setenv("DB_PORT_SCENARIO_1_3", "3307")
    monkeypatch.setenv("DB_NAME_SCENARIO_1_3", "industry")
    monkeypatch.setenv("DB_USER_SCENARIO_1_3", "reader")
    monkeypatch.setenv("DB_PASSWORD_SCENARIO_1_3", "secret")

    settings = MySQLSettings.from_environment()

    assert settings is not None
    assert settings.host == "db.example.com"
    assert settings.port == 3307
    assert settings.database == "industry"
    assert settings.user == "reader"


def test_sql_string_escapes_single_quotes() -> None:
    assert sql_string("pa'ss") == "'pa''ss'"


def test_configure_mysql_source_creates_analysis_views() -> None:
    connection = RecordingConnection()
    settings = MySQLSettings(
        host="db.example.com",
        port=3306,
        database="industry",
        user="reader",
        password="test-password",
    )

    configure_mysql_source(connection, settings)

    sql = "\n".join(connection.statements)
    assert "CREATE SECRET chainlens_mysql" in sql
    assert "ATTACH '' AS source_mysql" in sql
    assert "CREATE OR REPLACE TEMP VIEW v_enterprise" in sql
    assert "CREATE OR REPLACE TEMP VIEW v_bidding" in sql
    assert "CREATE OR REPLACE TEMP VIEW v_financing" in sql
    assert "CREATE OR REPLACE TEMP VIEW v_equity" in sql
    assert "CREATE OR REPLACE TEMP VIEW v_qualification" in sql
    assert '"招投标信息"' in sql
    assert '"商标资质信息"' in sql


def test_materialize_analysis_views_replaces_remote_views_with_local_cache() -> None:
    connection = RecordingConnection()

    materialize_analysis_views(connection)

    sql = "\n".join(connection.statements)
    assert "CREATE OR REPLACE TEMP TABLE chainlens_cache_v_enterprise" in sql
    assert "DROP VIEW IF EXISTS v_enterprise" in sql
    assert "CREATE OR REPLACE TEMP VIEW v_qualification AS SELECT * FROM chainlens_cache_v_qualification" in sql
