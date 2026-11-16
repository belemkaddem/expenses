"""Base de données : SQLite en local, Postgres en production (variable DATABASE_URL)."""
from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import (Column, Date, DateTime, Float, Integer, MetaData, String, Table,
                        create_engine)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./depenses.db")
if DATABASE_URL.startswith("postgres://"):  # format Heroku/Neon ancien
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
metadata = MetaData()

expenses = Table(
    "expenses", metadata,
    Column("id", Integer, primary_key=True),
    Column("user", String(50), nullable=False, index=True),
    Column("amount", Float, nullable=False),
    Column("description", String(200), nullable=False),
    Column("category", String(50), nullable=False),
    Column("spent_on", Date, nullable=False, index=True),
    Column("channel", String(10), nullable=False, default="sms"),  # sms | web
    Column("raw_text", String(500)),
    Column("created_at", DateTime, nullable=False, default=datetime.now),
)

sms_log = Table(  # évite les doublons si la passerelle renvoie un webhook
    "sms_log", metadata,
    Column("message_id", String(120), primary_key=True),
    Column("received_at", DateTime, default=datetime.now),
)


def init_db() -> None:
    metadata.create_all(engine)
