from __future__ import annotations

import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass
class PostgresUrls:
    sqlalchemy_url: str
    psycopg_url: str


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_postgres(url: str, timeout_seconds: int = 30) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with psycopg.connect(url):
                return
        except psycopg.OperationalError:
            time.sleep(0.5)
    raise RuntimeError("Postgres container did not become ready in time")


@pytest.fixture(scope="session")
def postgres_urls() -> PostgresUrls:
    port = _find_free_port()
    container_name = f"vigilens-test-pg-{uuid.uuid4().hex[:8]}"

    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            container_name,
            "-e",
            "POSTGRES_USER=vigilens",
            "-e",
            "POSTGRES_PASSWORD=vigilens",
            "-e",
            "POSTGRES_DB=vigilens",
            "-p",
            f"{port}:5432",
            "postgres:16",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    psycopg_url = f"postgresql://vigilens:vigilens@127.0.0.1:{port}/vigilens"
    sqlalchemy_url = f"postgresql+psycopg://vigilens:vigilens@127.0.0.1:{port}/vigilens"

    try:
        _wait_for_postgres(psycopg_url)
        yield PostgresUrls(sqlalchemy_url=sqlalchemy_url, psycopg_url=psycopg_url)
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], check=False)


@pytest.fixture
def reset_database(postgres_urls: PostgresUrls) -> None:
    init_sql_path = Path(__file__).resolve().parents[1] / "sql" / "init.sql"
    init_sql = init_sql_path.read_text(encoding="utf-8")

    with psycopg.connect(postgres_urls.psycopg_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            cur.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER;")
            cur.execute(init_sql)

    return None
