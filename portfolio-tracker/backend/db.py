"""SQLAlchemy models and session for the portfolio tracker.

The database is a single local SQLite file (portfolio.db) next to this module,
so the data never leaves the machine. Delete the file to start fresh.
"""
import json
import os
from datetime import date

from sqlalchemy import (
    Column, Date, Float, ForeignKey, Integer, String, Text, create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio.db")

Base = declarative_base()

ASSET_CLASSES = [
    "mutual_fund", "stock", "gold_physical", "sgb", "gold_etf", "reit",
    "fd", "savings", "epf", "ppf", "nps", "other",
]

ASSET_CLASS_LABELS = {
    "mutual_fund": "Mutual Fund",
    "stock": "Direct Stock",
    "gold_physical": "Gold (Physical)",
    "sgb": "Sovereign Gold Bond",
    "gold_etf": "Gold ETF/MF",
    "reit": "REIT / InvIT",
    "fd": "Fixed Deposit",
    "savings": "Savings Account",
    "epf": "EPF",
    "ppf": "PPF",
    "nps": "NPS",
    "other": "Other Investment",
}


class Owner(Base):
    __tablename__ = "owners"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    holdings = relationship("Holding", back_populates="owner")


class Holding(Base):
    """One investment position.

    Valuation depends on asset_class (see analytics.holding_value):
    - unit-priced (MF, stock, ETF, REIT, SGB, NPS): units * last_price
    - gold_physical: units = grams, last_price = rate/gram
    - fd: principal (avg_cost) compounded from start_date at rate
    - balance-based (savings, epf, ppf, other): manual_value as of value_date
    meta is a JSON blob for class-specific fields (category, bank, bucket
    override, sip_amount, maturity_date, ...).
    """
    __tablename__ = "holdings"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    asset_class = Column(String, nullable=False)
    name = Column(String, nullable=False)
    identifier = Column(String, default="")  # folio no / ticker / scheme code / acct no
    units = Column(Float, default=0.0)
    avg_cost = Column(Float, default=0.0)    # per-unit cost, or FD principal
    manual_value = Column(Float, default=0.0)
    value_date = Column(Date, default=date.today)
    last_price = Column(Float, default=0.0)
    price_date = Column(Date, nullable=True)
    rate = Column(Float, default=0.0)        # annual % for FD/PPF/savings
    start_date = Column(Date, nullable=True)
    meta = Column(Text, default="{}")
    notes = Column(Text, default="")
    owner = relationship("Owner", back_populates="holdings")
    transactions = relationship("Transaction", back_populates="holding",
                                cascade="all, delete-orphan")

    def meta_dict(self):
        try:
            return json.loads(self.meta or "{}")
        except ValueError:
            return {}


class Transaction(Base):
    """Optional cashflow record per holding; powers XIRR when present.

    amount is the money that moved: positive for money you put in
    (buy/contribution), positive for money you took out too — the type
    field decides the XIRR sign.
    """
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    holding_id = Column(Integer, ForeignKey("holdings.id"), nullable=False)
    date = Column(Date, nullable=False)
    type = Column(String, nullable=False)  # buy/sell/dividend/contribution/withdrawal
    amount = Column(Float, nullable=False)
    units = Column(Float, default=0.0)
    holding = relationship("Holding", back_populates="transactions")


class IncomeEntry(Base):
    __tablename__ = "income_entries"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    date = Column(Date, nullable=False)
    category = Column(String, default="Salary")
    amount = Column(Float, nullable=False)
    notes = Column(Text, default="")


class ExpenseEntry(Base):
    __tablename__ = "expense_entries"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    date = Column(Date, nullable=False)
    category = Column(String, default="Household")
    amount = Column(Float, nullable=False)
    fixed = Column(Integer, default=0)  # 1 = fixed/committed, 0 = discretionary
    notes = Column(Text, default="")


class RecurringOutflow(Base):
    """Committed monthly outflows: EMIs, SIPs, insurance premiums."""
    __tablename__ = "recurring_outflows"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    kind = Column(String, default="sip")  # emi/sip/premium/other
    amount_monthly = Column(Float, nullable=False)
    counts_as_investment = Column(Integer, default=0)  # SIPs are savings, not spend


class Loan(Base):
    __tablename__ = "loans"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    name = Column(String, nullable=False)
    kind = Column(String, default="home")  # home/car/personal/credit_card/other
    principal_outstanding = Column(Float, nullable=False)
    annual_rate = Column(Float, nullable=False)
    emi = Column(Float, default=0.0)
    tenure_months_remaining = Column(Integer, default=0)
    notes = Column(Text, default="")


class Snapshot(Base):
    """Monthly freeze of net worth; powers the trend chart."""
    __tablename__ = "snapshots"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    total_assets = Column(Float, nullable=False)
    total_liabilities = Column(Float, nullable=False)
    net_worth = Column(Float, nullable=False)
    by_class_json = Column(Text, default="{}")
    by_owner_json = Column(Text, default="{}")


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text, default="")


_engine = None
_SessionFactory = None


def get_session():
    global _engine, _SessionFactory
    if _engine is None:
        _engine = create_engine(f"sqlite:///{DB_PATH}")
        Base.metadata.create_all(_engine)
        _SessionFactory = sessionmaker(bind=_engine)
    return _SessionFactory()


def get_setting(session, key, default=""):
    row = session.get(Setting, key)
    return row.value if row else default


def set_setting(session, key, value):
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    session.commit()


DEFAULT_TARGETS = {"equity": 60.0, "debt": 25.0, "gold": 10.0,
                   "real_estate": 0.0, "cash": 5.0}


def get_targets(session):
    raw = get_setting(session, "targets", "")
    if not raw:
        return dict(DEFAULT_TARGETS)
    try:
        return json.loads(raw)
    except ValueError:
        return dict(DEFAULT_TARGETS)
