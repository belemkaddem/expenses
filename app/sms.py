"""Envoi des réponses SMS via le téléphone Android relais (SMS Gateway for Android)."""
from __future__ import annotations

import logging

import httpx

from . import config
from .parser import strip_accents

log = logging.getLogger("sms")


def send_sms(phone: str, text: str) -> bool:
    if not (config.SMS_REPLY and config.SMSGATE_USER and config.SMSGATE_PASSWORD):
        log.info("[SMS non envoyé - passerelle non configurée] -> %s : %s", phone, text)
        return False
    try:
        r = httpx.post(
            f"{config.SMSGATE_URL.rstrip('/')}/messages",
            json={"message": strip_accents(text)[:480], "phoneNumbers": [phone]},
            auth=(config.SMSGATE_USER, config.SMSGATE_PASSWORD),
            timeout=15,
        )
        r.raise_for_status()
        return True
    except Exception as e:  # on ne bloque jamais l'enregistrement pour une réponse ratée
        log.warning("Échec envoi SMS à %s : %s", phone, e)
        return False
