"""Assistant de configuration interactif : python veille.py configurer"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import time

from . import scheduler, telegram
from .config import CONFIG_PATH, ConfigError, load_config, parse_send_time, save_config


def ask(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix} : ").strip()
    return answer or default


def yes(question: str, default: bool = True) -> bool:
    hint = "O/n" if default else "o/N"
    answer = input(f"{question} ({hint}) : ").strip().lower()
    return default if not answer else answer in ("o", "oui", "y", "yes")


def title(text: str) -> None:
    print(f"\n━━━ {text} ━━━\n")


# --------------------------------------------------------------------------- Étapes

def step_token(cfg: dict) -> str:
    title("1/5 · Ton bot Telegram")
    current = cfg["telegram"]["token"]
    if current:
        try:
            me = telegram.get_me(current)
            if yes(f"Bot déjà configuré : @{me['username']}. Le garder ?"):
                return current
        except telegram.TelegramError:
            print("Le token actuel ne fonctionne plus, on en configure un nouveau.")
    print("Si tu n'as pas encore de bot :")
    print("  1. Dans Telegram, ouvre une conversation avec @BotFather")
    print("  2. Envoie /newbot, choisis un nom puis un identifiant finissant par « bot »")
    print("  3. BotFather te donne un token du genre 123456789:AAH…  Copie-le ici.\n")
    while True:
        token = ask("Token du bot").replace(" ", "")
        if not re.fullmatch(r"\d+:[\w-]{30,}", token):
            print("Ce n'est pas un token valide (format attendu : 123456789:AAH…).")
            continue
        try:
            me = telegram.get_me(token)
        except telegram.TelegramError as e:
            print(f"Telegram refuse ce token : {e}")
            continue
        print(f"✔ Bot reconnu : @{me['username']}")
        cfg["_bot_username"] = me["username"]
        return token


def _pending_offset(token: str) -> int | None:
    """Ignore les anciens messages : on n'attend que celui que l'utilisateur va envoyer maintenant."""
    try:
        pending = telegram.get_updates(token)
    except telegram.TelegramError as e:
        if "webhook" not in str(e).lower():
            raise
        telegram.call(token, "deleteWebhook")  # getUpdates est incompatible avec un webhook actif
        return None
    return pending[-1]["update_id"] + 1 if pending else None


def _wait_for_chat(token: str, seconds: int = 120) -> dict | None:
    offset = _pending_offset(token)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for update in telegram.get_updates(token, offset, timeout=20):
            offset = update["update_id"] + 1
            chat = (update.get("message") or {}).get("chat")
            if chat:
                return chat
    return None


def step_chat_id(cfg: dict, token: str) -> str:
    title("2/5 · Ta conversation")
    current = str(cfg["telegram"]["chat_id"] or "")
    if current and token == cfg["telegram"]["token"] and yes(f"Conversation déjà configurée ({current}). La garder ?"):
        return current
    username = cfg.get("_bot_username") or telegram.get_me(token)["username"]
    print(f"Ouvre Telegram, cherche @{username}, appuie sur « Démarrer » (ou envoie-lui « bonjour »).")
    print("J'attends ton message (2 minutes maximum)…")
    chat = _wait_for_chat(token)
    if chat:
        who = chat.get("first_name") or chat.get("title") or chat.get("username") or "?"
        print(f"✔ Message reçu de {who} (chat_id {chat['id']})")
        return str(chat["id"])
    print("Aucun message reçu. Tu peux aussi saisir le chat_id à la main (ou relancer l'assistant).")
    while True:
        manual = ask("chat_id")
        if re.fullmatch(r"-?\d+", manual):
            return manual


def step_schedule(cfg: dict) -> str:
    title("3/5 · Heure d'envoi")
    print("Chaque jour à cette heure (si le PC est allumé), tu reçois le brief.")
    print("PC éteint à cette heure-là ? Le brief part dès que tu ouvres ta session, avec tout ce que tu as manqué.")
    while True:
        value = ask("Heure d'envoi (HH:MM)", cfg["heure_envoi"])
        try:
            h, m = parse_send_time(value)
            return f"{h:02d}:{m:02d}"
        except ConfigError as e:
            print(e)


def _install_anthropic() -> bool:
    if importlib.util.find_spec("anthropic"):
        return True
    if not yes("Le paquet « anthropic » (SDK officiel de Claude) n'est pas installé. L'installer maintenant ?"):
        return False
    proc = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "anthropic"])
    importlib.invalidate_caches()
    return proc.returncode == 0 and importlib.util.find_spec("anthropic") is not None


def _check_api_key(key: str, model: str) -> str | None:
    import anthropic
    try:
        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        client.models.retrieve(model)  # gratuit : vérifie la clé et l'accès au modèle
        return None
    except anthropic.AuthenticationError:
        return "clé refusée"
    except anthropic.NotFoundError:
        return f"modèle {model} inaccessible avec cette clé"
    except anthropic.APIConnectionError:
        return "API injoignable (réseau)"
    except anthropic.APIStatusError as e:
        return f"erreur {e.status_code}"


def step_ai(cfg: dict) -> None:
    title("4/5 · Analyse par Claude (facultative)")
    print("Sans IA (gratuit) : le brief part quand même, avec les 5 à 10 sujets qui comptent.")
    print("Avec Claude (clé API payante) : titres traduits, « pourquoi c'est important », note d'importance,")
    print("signal du jour, analyse approfondie… Coût indicatif : 0,15 à 0,30 $ par brief (Opus 5.5).")
    print("Pas de clé ? Réponds simplement « n » (ou appuie sur Entrée).\n")
    if not yes("Activer l'analyse par Claude ?", default=cfg["ia"]["active"]):
        cfg["ia"]["active"] = False
        return
    if not _install_anthropic():
        print("Analyse IA désactivée (SDK non installé). Tu pourras relancer l'assistant plus tard.")
        cfg["ia"]["active"] = False
        return
    env_key = os.environ.get("ANTHROPIC_API_KEY", "")
    key = cfg["ia"]["api_key"]
    if env_key and not key and yes("Clé trouvée dans ANTHROPIC_API_KEY. L'utiliser ?"):
        key = ""
    elif not key or not yes("Une clé est déjà enregistrée. La garder ?"):
        key = ask("Clé API Anthropic (sk-ant-…)").strip()
    error = _check_api_key(key, cfg["ia"]["modele"])
    if error:
        print(f"✘ Vérification impossible : {error}. Analyse IA désactivée pour l'instant.")
        cfg["ia"]["active"] = False
        return
    print("✔ Clé valide.")
    cfg["ia"].update({"active": True, "api_key": key})


def step_task(cfg: dict) -> None:
    title("5/5 · Envoi automatique")
    if sys.platform != "win32":
        print("Planification automatique disponible sous Windows uniquement.")
        print(f"Ailleurs, planifie : {sys.executable} {scheduler.SCRIPT} auto  (cron, toutes les heures)")
        return
    if not yes(f"Créer la tâche planifiée Windows (tous les jours à {cfg['heure_envoi']} + rattrapage au démarrage) ?"):
        return
    try:
        scheduler.install(cfg["heure_envoi"])
        info = scheduler.status() or {}
        print(f"✔ Tâche « {scheduler.TASK_NAME} » créée. Prochain envoi : {info.get('next_run') or cfg['heure_envoi']}")
    except scheduler.SchedulerError as e:
        print(f"✘ Impossible de créer la tâche : {e}")
        print("  Relance plus tard avec : python veille.py installer")


# --------------------------------------------------------------------------- Assistant

def run() -> int:
    print("\n🌍  VEILLE IA & TECH · configuration\n")
    print("Cet assistant prépare ton brief quotidien sur Telegram. Ctrl+C pour quitter à tout moment.")
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"config.json illisible ({e}) : on repart des réglages par défaut.")
        from .config import DEFAULTS
        import copy
        cfg = copy.deepcopy(DEFAULTS)
    try:
        token = step_token(cfg)
        chat_id = step_chat_id(cfg, token)
        cfg["telegram"] = {"token": token, "chat_id": chat_id}
        cfg.pop("_bot_username", None)
        telegram.send_message(token, chat_id, "✅ <b>Veille IA &amp; Tech</b> est connectée. "
                                              "Ton premier brief arrive bientôt.")
        print("✔ Message de test envoyé : regarde ton Telegram.")
        cfg["heure_envoi"] = step_schedule(cfg)
        step_ai(cfg)
        save_config(cfg)
        print(f"\n✔ Configuration enregistrée dans {CONFIG_PATH.name}")
        step_task(cfg)
    except KeyboardInterrupt:
        print("\nConfiguration interrompue.")
        return 1
    except telegram.TelegramError as e:
        print(f"\n✘ Erreur Telegram : {e}")
        return 1

    print("\n━━━ Terminé ━━━\n")
    if yes("Envoyer un premier brief maintenant ?"):
        from .cli import cmd_send
        return cmd_send(None)
    print("Commandes utiles : python veille.py apercu | envoyer | statut")
    return 0
