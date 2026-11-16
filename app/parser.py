"""Analyse des SMS : dépenses (« 45 café ») et commandes (« total », « annuler »...)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

# Mots-clés -> catégorie (sans accents, minuscules)
CATEGORIES: dict[str, list[str]] = {
    "Alimentation": ["courses", "marjane", "carrefour", "bim", "aswak", "acima", "epicerie", "hanout",
                     "pain", "legumes", "fruits", "viande", "poulet", "poisson", "lait", "souk", "marche"],
    "Restaurant & Café": ["cafe", "resto", "restaurant", "dejeuner", "diner", "pizza", "tacos", "snack",
                          "the", "glovo", "mcdo", "burger", "sandwich", "jus"],
    "Transport": ["taxi", "essence", "gasoil", "carburant", "bus", "tram", "train", "oncf", "careem",
                  "indrive", "uber", "parking", "peage", "autoroute", "vidange"],
    "Logement": ["loyer", "electricite", "eau", "lydec", "redal", "amendis", "onee", "syndic", "gaz", "butane"],
    "Télécom": ["recharge", "internet", "inwi", "orange", "iam", "maroc telecom", "forfait", "wifi", "fibre"],
    "Santé": ["pharmacie", "medecin", "docteur", "medicament", "dentiste", "analyse", "clinique", "mutuelle"],
    "Shopping": ["vetements", "habits", "chaussures", "zara", "decathlon", "amazon", "jumia", "cadeau"],
    "Loisirs": ["cinema", "sortie", "voyage", "hotel", "sport", "salle", "netflix", "spotify", "jeu"],
    "Éducation": ["ecole", "livre", "livres", "cours", "formation", "frais scolaires"],
    "Maison": ["menage", "bricolage", "meuble", "electromenager", "produits"],
}
DEFAULT_CATEGORY = "Autre"
ALL_CATEGORIES = list(CATEGORIES) + [DEFAULT_CATEGORY]


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    return strip_accents(s).lower().strip()


def guess_category(text: str) -> str:
    t = " " + re.sub(r"[^a-z0-9 ]", " ", norm(text)) + " "
    for cat, words in CATEGORIES.items():
        for w in words:
            if f" {w} " in t:
                return cat
    return DEFAULT_CATEGORY


def match_category_tag(tag: str) -> Optional[str]:
    """#transport -> 'Transport' ; accepte un début de nom (#resto, #sante)."""
    t = norm(tag)
    for cat in ALL_CATEGORIES:
        if norm(cat).startswith(t) or t in norm(cat):
            return cat
    return guess_category(tag) if guess_category(tag) != DEFAULT_CATEGORY else None


@dataclass
class Command:
    kind: str  # expense | total | total_all | list | undo | help | categories | unknown
    amount: Optional[float] = None
    description: str = ""
    category: Optional[str] = None
    spent_on: Optional[date] = None
    extra: dict = field(default_factory=dict)


AMOUNT_RE = re.compile(r"(?<![\w.,])(\d{1,7}(?:[.,]\d{1,2})?)\s*(?:dh|dhs|mad|drh|dirhams?)?(?![\w])", re.I)


def parse_sms(text: str, today: Optional[date] = None) -> Command:
    today = today or date.today()
    raw = (text or "").strip()
    t = norm(raw)

    if not t:
        return Command("help")
    if t in {"aide", "help", "?", "menu"}:
        return Command("help")
    if t in {"categories", "categorie", "cat"}:
        return Command("categories")
    if t in {"annuler", "annule", "suppr", "supprimer", "undo", "efface"}:
        return Command("undo")
    if t in {"liste", "dernier", "derniers", "historique"}:
        return Command("list")
    m = re.fullmatch(r"(total|bilan|solde|mois)(\s+(foyer|tous|tout|nous|commun))?", t)
    if m:
        return Command("total_all" if m.group(3) else "total")

    # --- Dépense ---
    work = raw
    category = None
    tag = re.search(r"#(\S+)", work)
    if tag:
        category = match_category_tag(tag.group(1))
        work = work.replace(tag.group(0), " ")

    spent_on = today
    nw = norm(work)
    if re.search(r"\bavant[- ]hier\b", nw):
        spent_on = today - timedelta(days=2)
        work = re.sub(r"(?i)\bavant[- ]hier\b", " ", strip_accents(work))
    elif re.search(r"\bhier\b", nw):
        spent_on = today - timedelta(days=1)
        work = re.sub(r"(?i)\bhier\b", " ", work)
    d = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", work)
    if d:
        day, month = int(d.group(1)), int(d.group(2))
        year = int(d.group(3)) if d.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            spent_on = date(year, month, day)
            work = work.replace(d.group(0), " ")
        except ValueError:
            pass

    am = AMOUNT_RE.search(work)
    if not am:
        return Command("unknown")
    amount = float(am.group(1).replace(",", "."))
    if amount <= 0:
        return Command("unknown")
    desc = (work[: am.start()] + " " + work[am.end():])
    desc = re.sub(r"\s+", " ", desc).strip(" -:,.")
    if not category:
        category = guess_category(desc)
    return Command("expense", amount=amount, description=desc or "Sans description",
                   category=category, spent_on=spent_on)


def normalize_phone(phone: str) -> str:
    """Normalise un numéro marocain : 0612345678 / 00212... / 212... -> +212612345678."""
    p = re.sub(r"[^\d+]", "", phone or "")
    if p.startswith("00"):
        p = "+" + p[2:]
    if p.startswith("0") and len(p) == 10:
        p = "+212" + p[1:]
    if p.startswith("212") and not p.startswith("+"):
        p = "+" + p
    return p
