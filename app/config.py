"""Configuration par variables d'environnement."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .parser import normalize_phone


@dataclass
class User:
    name: str
    phone: str
    password: str


def load_users() -> list[User]:
    """USERS="Yassine|0612345678|motdepasse1;Sara|0698765432|motdepasse2" """
    raw = os.getenv("USERS", "Moi|0600000001|demo;Autre|0600000002|demo")
    users = []
    for chunk in raw.split(";"):
        parts = [p.strip() for p in chunk.split("|")]
        if len(parts) == 3 and all(parts):
            users.append(User(parts[0], normalize_phone(parts[1]), parts[2]))
    return users


USERS = load_users()
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "change-moi")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-a-changer")

# Production = hébergé (Render définit RENDER) ou PRODUCTION=1
PRODUCTION = bool(os.getenv("RENDER")) or os.getenv("PRODUCTION") == "1"


def check_production_config() -> None:
    """Refuse de démarrer en ligne avec des réglages par défaut ou faibles."""
    if not PRODUCTION:
        return
    problems = []
    if not os.getenv("USERS"):
        problems.append("USERS n'est pas défini")
    for u in USERS:
        if len(u.password) < 10:
            problems.append(f"mot de passe de {u.name} trop court (10 caractères minimum)")
    if len(WEBHOOK_TOKEN) < 24 or WEBHOOK_TOKEN == "change-moi":
        problems.append("WEBHOOK_TOKEN absent ou trop court (24 caractères minimum)")
    if len(SECRET_KEY) < 32 or SECRET_KEY == "dev-secret-a-changer":
        problems.append("SECRET_KEY absent ou trop court (32 caractères minimum)")
    if not os.getenv("DATABASE_URL"):
        problems.append("DATABASE_URL n'est pas défini (les données seraient perdues)")
    if problems:
        raise RuntimeError("Configuration non sécurisée : " + " ; ".join(problems))
CURRENCY = os.getenv("CURRENCY", "DH")

# Réponses SMS via SMS Gateway for Android (mode Cloud : https://api.sms-gate.app/3rdparty/v1)
SMSGATE_URL = os.getenv("SMSGATE_URL", "https://api.sms-gate.app/3rdparty/v1")
SMSGATE_USER = os.getenv("SMSGATE_USER", "")
SMSGATE_PASSWORD = os.getenv("SMSGATE_PASSWORD", "")
SMS_REPLY = os.getenv("SMS_REPLY", "1") == "1"


def user_by_phone(phone: str) -> User | None:
    p = normalize_phone(phone)
    return next((u for u in USERS if u.phone == p), None)


def user_by_name(name: str) -> User | None:
    return next((u for u in USERS if u.name.lower() == (name or "").lower()), None)
