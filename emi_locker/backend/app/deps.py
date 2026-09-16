"""Request-scoped database connections and the authenticated actor."""
from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import Depends, Header, Request

from emi_locker.core import Actor
from emi_locker.db import file_db
from emi_locker.errors import PermissionDenied

from .auth import actor_from_token


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """One SQLite connection per request.

    Opening a connection is cheap; sharing one across threads is not. This is
    the SQLite equivalent of taking a connection from a pool, and swapping in
    PostgreSQL later means changing this function and nothing else.
    """
    # same_thread=False because FastAPI may run a sync dependency and its
    # endpoint on different threadpool workers, and an async endpoint on the
    # event loop. The connection still belongs to exactly one request, so it
    # is never used concurrently.
    conn = file_db(request.app.state.db_path, same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def current_actor(
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: str = Header(default=""),
) -> Actor:
    if not authorization.lower().startswith("bearer "):
        raise PermissionDenied("sign in to continue")
    return actor_from_token(conn, authorization[7:].strip())


def require_roles(*roles: str):
    def dependency(actor: Actor = Depends(current_actor)) -> Actor:
        actor.require_role(*roles)
        return actor

    return dependency


def retailer_scope_of(actor: Actor) -> str:
    """The retailer id an app user acts as."""
    if actor.role == "RETAILER":
        return actor.user_id
    if actor.role == "STAFF" and actor.parent_id:
        return actor.parent_id
    raise PermissionDenied("this action is only available to a retailer account")
