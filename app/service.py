"""Logique métier : enregistrer, annuler, totaliser."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from . import config
from .db import engine, expenses, sms_log
from .parser import ALL_CATEGORIES, parse_sms

HELP = (
    "Envoyez : montant + description. Ex: '45 cafe', '320 courses marjane', "
    "'60 taxi hier', '150 #sante'. Commandes : TOTAL (votre mois), TOTAL FOYER, "
    "LISTE (5 dernieres), ANNULER (supprime la derniere), CATEGORIES."
)


def fmt(amount: float) -> str:
    s = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return (s[:-3] if s.endswith(",00") else s) + f" {config.CURRENCY}"


def month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    end = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return start, end


def add_expense(user: str, amount: float, description: str, category: str,
                spent_on: date, channel: str, raw_text: str = "") -> int:
    with engine.begin() as c:
        r = c.execute(insert(expenses).values(
            user=user, amount=round(amount, 2), description=description[:200],
            category=category, spent_on=spent_on, channel=channel,
            raw_text=raw_text[:500], created_at=datetime.now()))
        return r.inserted_primary_key[0]


def month_total(user: str | None, d: date) -> float:
    start, end = month_bounds(d)
    q = select(func.coalesce(func.sum(expenses.c.amount), 0)).where(
        expenses.c.spent_on >= start, expenses.c.spent_on < end)
    if user:
        q = q.where(expenses.c.user == user)
    with engine.connect() as c:
        return float(c.execute(q).scalar() or 0)


def last_expenses(user: str, n: int = 5):
    with engine.connect() as c:
        return c.execute(select(expenses).where(expenses.c.user == user)
                         .order_by(expenses.c.id.desc()).limit(n)).fetchall()


def undo_last(user: str):
    rows = last_expenses(user, 1)
    if not rows:
        return None
    with engine.begin() as c:
        c.execute(delete(expenses).where(expenses.c.id == rows[0].id))
    return rows[0]


def already_processed(message_id: str | None) -> bool:
    if not message_id:
        return False
    try:
        with engine.begin() as c:
            c.execute(insert(sms_log).values(message_id=message_id, received_at=datetime.now()))
        return False
    except IntegrityError:
        return True


def handle_sms(user: str, text: str, today: date | None = None) -> str:
    today = today or date.today()
    cmd = parse_sms(text, today)
    if cmd.kind == "expense":
        add_expense(user, cmd.amount, cmd.description, cmd.category, cmd.spent_on, "sms", text)
        when = "" if cmd.spent_on == today else f" le {cmd.spent_on:%d/%m}"
        return (f"OK {fmt(cmd.amount)} - {cmd.description} ({cmd.category}){when}. "
                f"Total du mois : {fmt(month_total(user, today))}. ANNULER pour supprimer.")
    if cmd.kind == "total":
        return f"{user}, total {today:%m/%Y} : {fmt(month_total(user, today))}."
    if cmd.kind == "total_all":
        parts = [f"{u.name} {fmt(month_total(u.name, today))}" for u in config.USERS]
        return f"Foyer {today:%m/%Y} : {fmt(month_total(None, today))} ({', '.join(parts)})."
    if cmd.kind == "list":
        rows = last_expenses(user)
        if not rows:
            return "Aucune depense enregistree."
        return "Dernieres : " + " | ".join(
            f"{r.spent_on:%d/%m} {fmt(r.amount)} {r.description}" for r in rows)
    if cmd.kind == "undo":
        r = undo_last(user)
        return (f"Supprime : {fmt(r.amount)} - {r.description}." if r
                else "Rien a annuler.")
    if cmd.kind == "categories":
        return "Categories : " + ", ".join(ALL_CATEGORIES) + ". Forcez-en une avec #nom."
    if cmd.kind == "help":
        return HELP
    return "Je n'ai pas trouve de montant. " + HELP
