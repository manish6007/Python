"""SQLite storage layer.

Design notes that matter for the business rules in the blueprint:

* Money is stored as integer paise. No floats anywhere in the money path.
* ``tx()`` opens ``BEGIN IMMEDIATE`` so that a quota deduction takes the
  database write lock before it reads the balance. That is what makes
  "available -> used" atomic across concurrent retailer requests.
* ``audit_logs`` is append-only, enforced by triggers rather than by
  convention, so a bug in application code cannot rewrite history.
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import time

BUSY_TIMEOUT_SEC = 10

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS counters (
    name    TEXT PRIMARY KEY,
    value   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    role        TEXT NOT NULL CHECK (role IN
                 ('SUPER_ADMIN','DISTRIBUTOR','RETAILER','STAFF','CUSTOMER')),
    name        TEXT NOT NULL,
    mobile      TEXT,
    parent_id   TEXT REFERENCES users(id),
    status      TEXT NOT NULL DEFAULT 'ACTIVE'
                 CHECK (status IN ('PENDING','ACTIVE','SUSPENDED')),
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_parent ON users(parent_id);
-- Login is by mobile number, so one number cannot address two accounts.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_mobile
    ON users(mobile) WHERE mobile IS NOT NULL;

CREATE TABLE IF NOT EXISTS audit_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id     TEXT,
    actor_role   TEXT,
    action       TEXT NOT NULL,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT,
    before_json  TEXT,
    after_json   TEXT,
    created_at   TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_logs_no_update
    BEFORE UPDATE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs is append-only');
END;
CREATE TRIGGER IF NOT EXISTS audit_logs_no_delete
    BEFORE DELETE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs is append-only');
END;

-- Replay/double-submit protection for any mutating operation.
CREATE TABLE IF NOT EXISTS idempotency_keys (
    scope         TEXT NOT NULL,
    key           TEXT NOT NULL,
    result_json   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);

/* ------------------------------ licensing ------------------------------ */

CREATE TABLE IF NOT EXISTS license_plans (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    quota          INTEGER NOT NULL CHECK (quota > 0),
    price_paise    INTEGER NOT NULL CHECK (price_paise >= 0),
    validity_days  INTEGER NOT NULL CHECK (validity_days > 0),
    active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS licenses (
    id          TEXT PRIMARY KEY,
    key_hash    TEXT NOT NULL UNIQUE,
    key_masked  TEXT NOT NULL,
    plan_id     TEXT NOT NULL REFERENCES license_plans(id),
    quota       INTEGER NOT NULL CHECK (quota > 0),
    owner_type  TEXT NOT NULL CHECK (owner_type IN ('DISTRIBUTOR','RETAILER','DIRECT')),
    owner_id    TEXT REFERENCES users(id),
    status      TEXT NOT NULL CHECK (status IN
                 ('AVAILABLE','ACTIVE','EXPIRED','SUSPENDED','REVOKED')),
    valid_from  TEXT NOT NULL,
    valid_to    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_licenses_owner ON licenses(owner_id, status);

CREATE TABLE IF NOT EXISTS license_wallets (
    owner_id        TEXT PRIMARY KEY REFERENCES users(id),
    total_quota     INTEGER NOT NULL DEFAULT 0 CHECK (total_quota >= 0),
    used_quota      INTEGER NOT NULL DEFAULT 0 CHECK (used_quota >= 0),
    reserved_quota  INTEGER NOT NULL DEFAULT 0 CHECK (reserved_quota >= 0),
    updated_at      TEXT NOT NULL,
    CHECK (used_quota + reserved_quota <= total_quota)
);

CREATE TABLE IF NOT EXISTS license_allocations (
    id          TEXT PRIMARY KEY,
    license_id  TEXT REFERENCES licenses(id),
    from_owner  TEXT NOT NULL REFERENCES users(id),
    to_owner    TEXT NOT NULL REFERENCES users(id),
    quota       INTEGER NOT NULL CHECK (quota > 0),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS license_activations (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES users(id),
    license_id  TEXT REFERENCES licenses(id),
    finance_id  TEXT,
    device_id   TEXT,
    status      TEXT NOT NULL CHECK (status IN ('CONSUMED','ROLLED_BACK')),
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_activation_finance
    ON license_activations(finance_id) WHERE status = 'CONSUMED';

CREATE TABLE IF NOT EXISTS license_orders (
    id           TEXT PRIMARY KEY,
    buyer_id     TEXT NOT NULL REFERENCES users(id),
    plan_id      TEXT NOT NULL REFERENCES license_plans(id),
    amount_paise INTEGER NOT NULL CHECK (amount_paise >= 0),
    status       TEXT NOT NULL CHECK (status IN ('INITIATED','PAID','FAILED')),
    license_id   TEXT REFERENCES licenses(id),
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS license_renewals (
    id          TEXT PRIMARY KEY,
    license_id  TEXT NOT NULL REFERENCES licenses(id),
    order_id    TEXT REFERENCES license_orders(id),
    old_expiry  TEXT NOT NULL,
    new_expiry  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

/* ------------------------- customers and finance ----------------------- */

CREATE TABLE IF NOT EXISTS customers (
    id           TEXT PRIMARY KEY,
    retailer_id  TEXT NOT NULL REFERENCES users(id),
    user_id      TEXT REFERENCES users(id),
    name         TEXT NOT NULL,
    mobile       TEXT NOT NULL,
    address      TEXT,
    kyc_status   TEXT NOT NULL DEFAULT 'PENDING'
                  CHECK (kyc_status IN ('PENDING','VERIFIED','REJECTED')),
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customers_retailer ON customers(retailer_id);

CREATE TABLE IF NOT EXISTS customer_consents (
    id           TEXT PRIMARY KEY,
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    consent_type TEXT NOT NULL,
    doc_version  TEXT NOT NULL,
    accepted_at  TEXT NOT NULL,
    channel      TEXT,
    meta_json    TEXT
);

CREATE TABLE IF NOT EXISTS devices (
    id           TEXT PRIMARY KEY,
    imei         TEXT NOT NULL,
    model        TEXT,
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    finance_id   TEXT,
    status       TEXT NOT NULL CHECK (status IN
                  ('PENDING_ENROLLMENT','ACTIVE','PAYMENT_DUE','GRACE_PERIOD',
                   'OVERDUE','RESTRICTED','RESTORED','COMPLETED','CANCELLED')),
    created_at   TEXT NOT NULL
);
-- One live finance per IMEI; closed/cancelled records stay for audit.
CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_live_imei
    ON devices(imei) WHERE status NOT IN ('COMPLETED','CANCELLED');

CREATE TABLE IF NOT EXISTS finance_accounts (
    id                 TEXT PRIMARY KEY,
    customer_id        TEXT NOT NULL REFERENCES customers(id),
    retailer_id        TEXT NOT NULL REFERENCES users(id),
    device_id          TEXT REFERENCES devices(id),
    product_price      INTEGER NOT NULL CHECK (product_price > 0),
    down_payment       INTEGER NOT NULL CHECK (down_payment >= 0),
    principal          INTEGER NOT NULL CHECK (principal > 0),
    tenure_months      INTEGER NOT NULL CHECK (tenure_months > 0),
    emi_amount         INTEGER NOT NULL CHECK (emi_amount > 0),
    late_fee_paise     INTEGER NOT NULL DEFAULT 0,
    grace_days         INTEGER NOT NULL DEFAULT 5,
    status             TEXT NOT NULL CHECK (status IN
                        ('DRAFT','ACTIVE','OVERDUE','COMPLETED','CANCELLED')),
    start_date         TEXT NOT NULL,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_finance_retailer ON finance_accounts(retailer_id);

CREATE TABLE IF NOT EXISTS finance_agreements (
    id            TEXT PRIMARY KEY,
    finance_id    TEXT NOT NULL REFERENCES finance_accounts(id),
    doc_version   TEXT NOT NULL,
    terms_json    TEXT NOT NULL,
    accepted_at   TEXT NOT NULL,
    accepted_by   TEXT NOT NULL,
    meta_json     TEXT
);

CREATE TABLE IF NOT EXISTS emi_schedules (
    id           TEXT PRIMARY KEY,
    finance_id   TEXT NOT NULL REFERENCES finance_accounts(id),
    seq          INTEGER NOT NULL,
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    due_date     TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN
                  ('UPCOMING','DUE','GRACE_PERIOD','OVERDUE','PAID','WAIVED')),
    paid_at      TEXT,
    UNIQUE (finance_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_emi_due ON emi_schedules(due_date, status);

/* ------------------------------- payments ------------------------------ */

CREATE TABLE IF NOT EXISTS payment_transactions (
    id             TEXT PRIMARY KEY,
    finance_id     TEXT NOT NULL REFERENCES finance_accounts(id),
    emi_id         TEXT REFERENCES emi_schedules(id),
    amount_paise   INTEGER NOT NULL CHECK (amount_paise > 0),
    method         TEXT NOT NULL CHECK (method IN ('ONLINE','CASH','OTHER')),
    gateway_txn_id TEXT,
    gateway_order  TEXT,
    status         TEXT NOT NULL CHECK (status IN
                    ('INITIATED','SUCCESS','FAILED','REFUNDED')),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_gateway_txn
    ON payment_transactions(gateway_txn_id) WHERE gateway_txn_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS receipts (
    id          TEXT PRIMARY KEY,
    payment_id  TEXT NOT NULL UNIQUE REFERENCES payment_transactions(id),
    number      TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collections (
    id           TEXT PRIMARY KEY,
    finance_id   TEXT NOT NULL REFERENCES finance_accounts(id),
    emi_id       TEXT REFERENCES emi_schedules(id),
    collected_by TEXT NOT NULL REFERENCES users(id),
    payment_id   TEXT NOT NULL REFERENCES payment_transactions(id),
    amount_paise INTEGER NOT NULL,
    mode         TEXT NOT NULL CHECK (mode IN ('CASH','OTHER')),
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_events (
    event_id    TEXT PRIMARY KEY,
    provider    TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    received_at TEXT NOT NULL
);

/* --------------------------- device management ------------------------- */

CREATE TABLE IF NOT EXISTS device_commands (
    id            TEXT PRIMARY KEY,
    device_id     TEXT NOT NULL REFERENCES devices(id),
    command       TEXT NOT NULL CHECK (command IN
                   ('ENROLL','REMIND','RESTRICT','RESTORE','RELEASE')),
    reason        TEXT NOT NULL,
    requested_by  TEXT NOT NULL REFERENCES users(id),
    approved_by   TEXT REFERENCES users(id),
    status        TEXT NOT NULL CHECK (status IN
                   ('PENDING_APPROVAL','APPROVED','SENT','ACKED','FAILED','REJECTED')),
    provider      TEXT,
    provider_ref  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_command_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id TEXT NOT NULL REFERENCES device_commands(id),
    event      TEXT NOT NULL,
    detail     TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_otps (
    mobile       TEXT PRIMARY KEY,
    code_hash    TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(path: str = ":memory:", same_thread: bool = True) -> sqlite3.Connection:
    """Open a connection configured the way the service layer expects.

    ``same_thread=False`` is only for the demo HTTP server, which serialises
    its requests behind a lock. Real deployments give each request its own
    connection from a pool.
    """
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SEC, isolation_level=None,
                           check_same_thread=same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=%d" % (BUSY_TIMEOUT_SEC * 1000))
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def open_db(path: str = ":memory:", same_thread: bool = True) -> sqlite3.Connection:
    conn = connect(path, same_thread=same_thread)
    init_schema(conn)
    return conn


@contextlib.contextmanager
def tx(conn: sqlite3.Connection):
    """Write transaction that takes the write lock up front.

    ``BEGIN IMMEDIATE`` is the important part: a deferred transaction would
    read the wallet balance under a shared lock and only fail at COMMIT time,
    which is exactly the race that oversells activation quota.
    """
    deadline = time.time() + BUSY_TIMEOUT_SEC
    while True:
        try:
            conn.execute("BEGIN IMMEDIATE")
            break
        except sqlite3.OperationalError as exc:  # pragma: no cover - timing
            if "locked" not in str(exc) and "busy" not in str(exc):
                raise
            if time.time() > deadline:
                raise
            time.sleep(0.01)
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def file_db(path: str, same_thread: bool = True) -> sqlite3.Connection:
    fresh = not os.path.exists(path)
    conn = connect(path, same_thread=same_thread)
    if fresh:
        init_schema(conn)
    return conn
