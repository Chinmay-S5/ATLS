"""
Database Connection & Transaction Management Layer.

This module provides ConnectionPool management for PostgreSQL using psycopg v3,
enforcing least-privilege role segregation between ATM operations (atm_service),
bank clerk administrative workflows (clerk_service), and DBA administrative tasks (atm_dba).
"""

import os
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple, Union
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("db")

# Load environment variables
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "atls_db")

# Credentials per role
DB_ADMIN_USER = os.getenv("DB_ADMIN_USER", "atm_dba")
DB_ADMIN_PASSWORD = os.getenv("DB_ADMIN_PASSWORD", "")

DB_ATM_USER = os.getenv("DB_ATM_USER", "atm_service")
DB_ATM_PASSWORD = os.getenv("DB_ATM_PASSWORD", "")

DB_CLERK_USER = os.getenv("DB_CLERK_USER", "clerk_service")
DB_CLERK_PASSWORD = os.getenv("DB_CLERK_PASSWORD", "")


def _build_conn_string(user: str, password: str) -> str:
    """Build a standard PostgreSQL libpq connection string."""
    return f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={user} password={password}"


# Initialize connection pools for role segregation
_pools: Dict[str, ConnectionPool] = {}


def init_pools() -> None:
    """
    Initialize persistent psycopg_pool.ConnectionPool instances for each service role.
    This ensures thread-safe, resilient database connections across Port 5001 and Port 5002.
    """
    global _pools
    try:
        # ATM Terminal Pool (Port 5001: Card auth, withdrawals, deposits, balance inquiries)
        _pools["atm"] = ConnectionPool(
            conninfo=_build_conn_string(DB_ATM_USER, DB_ATM_PASSWORD),
            min_size=2,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        logger.info("Initialized connection pool for role: atm_service")

        # Clerk / Audit Pool (Port 5002: Reports, account hub, transaction auditing)
        _pools["clerk"] = ConnectionPool(
            conninfo=_build_conn_string(DB_CLERK_USER, DB_CLERK_PASSWORD),
            min_size=2,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        logger.info("Initialized connection pool for role: clerk_service")

        # DBA Pool (Port 5002: Administrative pseudo-terminal, schema queries)
        _pools["admin"] = ConnectionPool(
            conninfo=_build_conn_string(DB_ADMIN_USER, DB_ADMIN_PASSWORD),
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        logger.info("Initialized connection pool for role: atm_dba")
    except Exception as exc:
        logger.error(f"Failed to initialize database connection pools: {exc}")
        raise


def get_pool(role: str = "atm") -> ConnectionPool:
    """
    Retrieve connection pool by role identifier ('atm', 'clerk', or 'admin').
    """
    if not _pools:
        init_pools()
    if role not in _pools:
        raise ValueError(f"Unknown database role: '{role}'. Expected 'atm', 'clerk', or 'admin'.")
    return _pools[role]


@contextmanager
def get_db_connection(role: str = "atm"):
    """
    Context manager yielding a pooled database connection with automatic check-in.

    :param role: Database service role ('atm', 'clerk', or 'admin').
    :yield: psycopg.Connection
    """
    pool = get_pool(role)
    with pool.connection() as conn:
        yield conn


def execute_query(
    sql: str,
    params: Optional[Union[Tuple, Dict[str, Any], List[Any]]] = None,
    role: str = "atm",
    fetch: str = "all",
) -> Any:
    """
    Execute a parameterized SQL query with automatic row conversion to dictionary objects.

    :param sql: SQL query string.
    :param params: Optional parameters tuple or dict.
    :param role: Database service role ('atm', 'clerk', or 'admin').
    :param fetch: Fetch mode ('all', 'one', or 'none').
    :return: Query result records (list of dicts, single dict, or None).
    """
    with get_db_connection(role) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if fetch == "all":
                return cur.fetchall()
            elif fetch == "one":
                return cur.fetchone()
            elif fetch == "none":
                conn.commit()
                return None
            else:
                raise ValueError(f"Invalid fetch argument: {fetch}")


def execute_procedure(
    proc_name: str,
    params: List[Any],
    types: Optional[List[str]] = None,
    role: str = "atm",
) -> None:
    """
    Execute a PostgreSQL stored procedure (e.g. sp_atm_withdraw_cash) with explicit casts and commit.

    :param proc_name: Procedure name, e.g. 'sp_atm_withdraw_cash'.
    :param params: Positional arguments to pass to the procedure.
    :param types: Optional PostgreSQL type names (e.g. ['BIGINT', 'VARCHAR', 'NUMERIC']) for exact resolution.
    :param role: Database service role ('atm', 'clerk', or 'admin').
    """
    if types and len(types) == len(params):
        placeholders = ", ".join([f"%s::{t}" for t in types])
    else:
        placeholders = ", ".join(["%s"] * len(params))
    call_sql = f"CALL {proc_name}({placeholders});"
    with get_db_connection(role) as conn:
        with conn.cursor() as cur:
            cur.execute(call_sql, params)
        conn.commit()

