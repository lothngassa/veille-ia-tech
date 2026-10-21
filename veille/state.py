"""Mémoire du programme : dernière édition envoyée, articles déjà vus, historique des briefs, verrou."""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import DATA_DIR, LOCK_PATH, STATE_PATH, write_json_atomic

log = logging.getLogger(__name__)

HISTORY_DIR = DATA_DIR / "historique"


class State:
    """data/etat.json"""

    def __init__(self, path: Path = STATE_PATH):
        self.path = path
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                log.warning("etat.json illisible : on repart d'un état vide")
        self.last_edition: date | None = _parse_date(data.get("derniere_edition"))
        self.last_sent_at: datetime | None = _parse_datetime(data.get("dernier_envoi"))
        self.seen: dict[str, str] = data.get("vus", {})          # clé d'URL -> date
        self.recent: list[dict] = data.get("sujets_recents", [])  # {"t": [tokens], "d": date}

    def seen_keys(self) -> set[str]:
        return set(self.seen)

    def recent_tokens(self) -> list[frozenset]:
        return [frozenset(r["t"]) for r in self.recent]

    def record_edition(self, edition: date, sent_at: datetime, keys: list[str], story_tokens: list[frozenset]) -> None:
        today = sent_at.date().isoformat()
        self.last_edition = max(edition, self.last_edition) if self.last_edition else edition
        self.last_sent_at = sent_at
        for key in keys:
            self.seen[key] = today
        self.recent.extend({"t": sorted(t), "d": today} for t in story_tokens if t)
        self._prune(sent_at.date())

    def _prune(self, today: date) -> None:
        seen_limit = (today - timedelta(days=14)).isoformat()
        recent_limit = (today - timedelta(days=3)).isoformat()
        self.seen = {k: d for k, d in self.seen.items() if d >= seen_limit}
        self.recent = [r for r in self.recent if r["d"] >= recent_limit]

    def save(self) -> None:
        write_json_atomic(self.path, {
            "derniere_edition": self.last_edition.isoformat() if self.last_edition else None,
            "dernier_envoi": self.last_sent_at.isoformat() if self.last_sent_at else None,
            "vus": self.seen,
            "sujets_recents": self.recent,
        })


def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_datetime(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- Historique des briefs

def save_history(edition: date, record: dict) -> None:
    write_json_atomic(HISTORY_DIR / f"{edition.isoformat()}.json", record)


def load_history(before: date, days: int = 7) -> list[dict]:
    """Les briefs des `days` jours précédant `before`, du plus récent au plus ancien."""
    out = []
    for i in range(1, days + 1):
        path = HISTORY_DIR / f"{(before - timedelta(days=i)).isoformat()}.json"
        if path.exists():
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
    return out


def prune_history(today: date, keep_days: int = 60) -> None:
    limit = (today - timedelta(days=keep_days)).isoformat()
    for path in HISTORY_DIR.glob("*.json"):
        if path.stem < limit:
            path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- Verrou

class AlreadyRunning(Exception):
    pass


@contextmanager
def single_instance(path: Path = LOCK_PATH, stale_after: float = 3600):
    """Empêche deux exécutions simultanées (tâche planifiée + lancement manuel)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        age = time.time() - path.stat().st_mtime
        if age < stale_after:
            raise AlreadyRunning(f"une autre exécution est en cours (verrou de {int(age)} s)") from None
        path.unlink(missing_ok=True)  # verrou abandonné (plantage, extinction brutale)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)
