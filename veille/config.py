"""Configuration : chemins du projet, valeurs par défaut, lecture et écriture de config.json."""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
SOURCES_PATH = ROOT / "sources.json"
DATA_DIR = ROOT / "data"
STATE_PATH = DATA_DIR / "etat.json"
LOCK_PATH = DATA_DIR / "veille.lock"
LOG_DIR = ROOT / "logs"
LOG_PATH = LOG_DIR / "veille.log"
PREVIEW_PATH = ROOT / "apercu.html"

TASK_NAME = "Veille IA Tech"

DEFAULTS: dict = {
    "telegram": {"token": "", "chat_id": ""},
    "heure_envoi": "20:00",
    # Si le PC était éteint à l'heure d'envoi, envoyer l'édition manquée au prochain démarrage.
    "rattrapage": True,
    # Période couverte : tout depuis le dernier envoi, bornée entre min et max heures (168 h = 7 jours).
    "fenetre_heures": {"min": 24, "max": 168},
    # « court » : seulement les sujets qui comptent. « complet » : ajoute tour du monde, watchlist, vidéos, pouls.
    "format": "court",
    # 5 sujets minimum, 7 d'habitude, 10 maximum les jours très chargés.
    # par_region : nombre de sujets par région dans le « Tour du monde » (format complet).
    "selection": {"min": 5, "habituel": 7, "max": 10, "max_par_source": 2, "par_region": 5},
    "ia": {
        "active": False,
        "api_key": "",  # vide = variable d'environnement ANTHROPIC_API_KEY
        "modele": "claude-opus-5-5",
        "effort": "medium",  # low | medium | high
    },
    # Sujets suivis de près. Chaîne simple ("Mistral") ou objet : nom affiché, requête Google News, motif regex.
    "watchlist": [
        {"nom": "Claude Code", "requete": "\"Claude Code\""},
        {"nom": "Anthropic"},
        {"nom": "OpenAI"},
        {"nom": "Google", "requete": "Google Gemini OR DeepMind", "motif": "google|gemini|deepmind"},
        {"nom": "NVIDIA", "requete": "Nvidia"},
        {"nom": "Microsoft", "requete": "Microsoft AI OR Copilot", "motif": "microsoft|copilot"},
        {"nom": "Agents IA", "requete": "\"AI agents\" OR \"agentic AI\"",
         "motif": "agents? (?:ia|d['’]ia|intelligents?|autonomes?)|ai agents?|agentic|agentique"},
        {"nom": "MCP", "requete": "\"Model Context Protocol\"", "motif": "\\bMCP\\b|model context protocol"},
        {"nom": "Open source", "requete": "\"open-source AI\" OR \"open-weight\"",
         "motif": "open[- ]source|open[- ]weights?"},
    ],
    # Ajoute automatiquement une recherche Google News par sujet de la watchlist.
    "watchlist_google_news": True,
}


class ConfigError(Exception):
    pass


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Path = CONFIG_PATH) -> dict:
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            raise ConfigError(
                f"{path.name} est mal formé (ligne {e.lineno}, colonne {e.colno}) : {e.msg}"
            ) from e
    cfg = _merge(DEFAULTS, data)

    # Les variables d'environnement l'emportent sur le fichier (utile pour ne pas y stocker de secret).
    if os.environ.get("VEILLE_TELEGRAM_TOKEN"):
        cfg["telegram"]["token"] = os.environ["VEILLE_TELEGRAM_TOKEN"]
    if os.environ.get("VEILLE_TELEGRAM_CHAT_ID"):
        cfg["telegram"]["chat_id"] = os.environ["VEILLE_TELEGRAM_CHAT_ID"]

    parse_send_time(cfg["heure_envoi"])
    return cfg


def save_config(cfg: dict, path: Path = CONFIG_PATH) -> None:
    write_json_atomic(path, cfg)


def parse_send_time(value: str) -> tuple[int, int]:
    """'20:00' ou '20h00' -> (20, 0)."""
    m = re.fullmatch(r"\s*(\d{1,2})[:hH](\d{2})\s*", str(value))
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise ConfigError(f"heure_envoi invalide : {value!r} (format attendu HH:MM, ex. 20:00)")
    return int(m[1]), int(m[2])


def telegram_ready(cfg: dict) -> bool:
    return bool(cfg["telegram"]["token"] and str(cfg["telegram"]["chat_id"]).strip())


def write_json_atomic(path: Path, data) -> None:
    """Écrit d'abord dans un fichier temporaire : un arrêt brutal ne laisse jamais un JSON à moitié écrit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
