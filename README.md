# 💸 Dépenses — suivi par SMS + page web

Enregistrez vos dépenses (et celles d'une 2ᵉ personne) en envoyant un simple SMS,
puis consultez-les sur une page web : totaux du mois, par personne, par catégorie.

```
 Votre téléphone ──SMS « 45 café »──▶ Android relais (SMS Gateway)
                                          │ webhook HTTPS
                                          ▼
                                  App FastAPI (Render) ──▶ Postgres (Neon)
                                          │
              réponse SMS « OK 45 DH… » ◀─┘        page web de consultation
```

## Utilisation par SMS

| Vous envoyez | Résultat |
|---|---|
| `45 café` | 45 DH, catégorie Restaurant & Café |
| `320,50 courses marjane` | 320,50 DH, Alimentation |
| `60 taxi hier` / `200 loyer 01/11` | dépense datée d'hier / du 1er novembre |
| `150 cadeau #shopping` | force la catégorie |
| `TOTAL` | votre total du mois |
| `TOTAL FOYER` | total des deux personnes |
| `LISTE` | vos 5 dernières dépenses |
| `ANNULER` | supprime votre dernière dépense |
| `AIDE`, `CATEGORIES` | rappel des commandes |

La personne est reconnue par son numéro : seuls les numéros déclarés dans `USERS` sont acceptés.

## Page web

- **Tableau de bord** : mois par mois, onglets Foyer / chaque personne, comparaison au mois précédent, répartition par catégorie, détail avec suppression.
- **Ajout manuel** de dépenses (canal « web »).
- **Simulateur SMS** pour tester sans téléphone.
- **Export CSV** (ouvrable dans Excel).

## Tester en local

```bash
pip install -r requirements.txt
cp .env.example .env   # puis éditez
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload
# http://localhost:8000  → connexion, puis « Simulateur SMS »
pytest -q              # tests
```

## Mise en ligne (gratuite)

### 1. Base de données — Neon
1. Créez un compte sur neon.tech, puis un projet.
2. Copiez la *connection string* (`postgresql://…?sslmode=require`) → ce sera `DATABASE_URL`.


> La base Postgres gratuite de Render expire après 30 jours ; Neon reste gratuit et permanent.

### 2. Application — Render
1. Poussez ce dossier sur un dépôt GitHub.
2. Sur render.com : **New → Blueprint**, choisissez le dépôt (le fichier `render.yaml` est détecté).
3. Renseignez :
   - `DATABASE_URL` : la chaîne Neon ;
   - `USERS` : `Yassine|06XXXXXXXX|motdepasse;Sara|06XXXXXXXX|motdepasse` (mots de passe de **10 caractères minimum**, sans `|` ni `;`) ;
   - `WEBHOOK_TOKEN` : un jeton aléatoire d'au moins 24 caractères, lettres/chiffres/`-`/`_` uniquement, ex. généré par
     `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   `SECRET_KEY` est généré automatiquement par Render.
4. Une fois déployé, notez l'URL (`https://depenses-xxxx.onrender.com`).

> En ligne, l'app **refuse de démarrer** si un réglage est absent ou trop faible : le message d'erreur
> apparaît dans les *Logs* de Render.

> Le plan gratuit de Render met l'app en veille après ~15 min sans trafic. Le premier SMS la réveille
> (≈ 30–60 s) ; l'app Android réessaie automatiquement si le premier envoi échoue.

### 3. Téléphone relais — SMS Gateway for Android
Ce téléphone (avec sa carte SIM) reçoit les SMS ; c'est **son numéro** que vous et l'autre personne utilisez.

1. Installez **SMS Gateway for Android** (sms-gate.app, ou releases GitHub `capcom6/android-sms-gateway`).
2. Activez le **Cloud server** et notez l'identifiant / mot de passe affichés → `SMSGATE_USER` / `SMSGATE_PASSWORD` dans Render (pour les réponses SMS).
3. Enregistrez le webhook :

```bash
curl -X POST -u IDENTIFIANT:MOTDEPASSE \
  -H "Content-Type: application/json" \
  -d '{"url": "https://depenses-xxxx.onrender.com/webhook/sms?token=VOTRE_WEBHOOK_TOKEN", "event": "sms:received"}' \
  https://api.sms-gate.app/3rdparty/v1/webhooks
```

4. Désactivez l'optimisation de batterie pour l'app, laissez le téléphone branché et connecté (Wi-Fi ou data).
5. Envoyez `45 café` au numéro du téléphone relais → réponse « OK 45 DH… ».

**Coût** : chaque réponse est un SMS envoyé depuis la SIM du relais. Un forfait avec SMS illimités
est idéal ; sinon mettez `SMS_REPLY=0` pour enregistrer sans répondre.

## Sécurité

- Connexion par mot de passe, cookie de session signé, `HttpOnly`, `Secure` et `SameSite=Strict` en ligne.
- Blocage après 5 mots de passe erronés en 15 minutes (par adresse IP).
- Webhook SMS protégé par un jeton secret ; seuls les numéros déclarés sont acceptés ; doublons ignorés.
- En-têtes de sécurité (CSP, anti-iframe, HSTS), documentation API désactivée.
- Démarrage refusé en ligne si la configuration est faible ou incomplète.
- Base Neon chiffrée en transit (`sslmode=require`).

Limites connues : les deux personnes voient et peuvent modifier toutes les dépenses du foyer (c'est voulu) ;
un numéro d'expéditeur SMS peut en théorie être usurpé, l'impact se limite à ajouter ou annuler une dépense.

## Structure

```
app/
  main.py      routes : webhook SMS, connexion, tableau de bord, export, simulateur
  parser.py    lecture des SMS (montant, date, catégorie, commandes)
  service.py   enregistrement, totaux, annulation, réponses
  sms.py       envoi des réponses via la passerelle Android
  db.py        tables (SQLite en local, Postgres en ligne)
  config.py    variables d'environnement
  templates/   pages web
tests/         tests automatisés
```

## Pistes pour la suite
- Budgets mensuels par catégorie avec alerte SMS au dépassement.
- Dépenses partagées (« qui doit combien à qui »).
- Rappel mensuel automatique par SMS avec le bilan du mois.
- Autres canaux : WhatsApp, Telegram.
