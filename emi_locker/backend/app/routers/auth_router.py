"""Login endpoints shared by both apps."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from emi_locker.core import Actor

from emi_locker.db import tx

from ..auth import end_all_sessions, profile_for, send_otp, verify_otp
from ..deps import current_actor, get_conn
from ..schemas import SendOtpIn, VerifyOtpIn

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/send-otp")
def post_send_otp(body: SendOtpIn, conn: sqlite3.Connection = Depends(get_conn)):
    return send_otp(conn, body.mobile)


@router.post("/verify-otp")
def post_verify_otp(body: VerifyOtpIn, conn: sqlite3.Connection = Depends(get_conn)):
    # Deliberately NOT wrapped in a transaction. A wrong code raises, and a
    # rollback would undo the attempt counter that the rejection just
    # incremented - which silently disables brute-force protection. The
    # connection is in autocommit mode, so each statement in verify_otp
    # stands on its own.
    return verify_otp(conn, body.mobile, body.code)


@router.post("/sign-out-everywhere")
def post_sign_out_everywhere(actor: Actor = Depends(current_actor),
                             conn: sqlite3.Connection = Depends(get_conn)):
    """End this account's sessions on every device, including this one.

    What a customer taps after losing a handset.
    """
    with tx(conn):
        epoch = end_all_sessions(conn, actor.user_id)
    return {"signed_out": True, "session_epoch": epoch}


@router.get("/me")
def get_me(actor: Actor = Depends(current_actor), conn: sqlite3.Connection = Depends(get_conn)):
    return profile_for(conn, actor.user_id)
