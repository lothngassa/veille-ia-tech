"""Lecture de sources.json : la liste des flux surveillés."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import SOURCES_PATH, ConfigError
from .regions import GLOBAL, REGIONS

# Types de source :
#   media      : média d'actualité (tech ou IA)
#   primaire   : blog officiel d'un acteur (OpenAI, Google, NVIDIA...) : source primaire
#   agregateur : Google News : le nom du média est lu dans chaque article
#   communaute : Reddit, Hacker News : signal de « buzz », poids plus faible
#   video      : chaîne YouTube : listée à part, jamais dans le brief principal
#   generaliste: média généraliste : on ne garde que les articles qui parlent d'IA ou de tech
KINDS = {"media", "primaire", "agregateur", "communaute", "video", "generaliste"}


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    region: str
    country: str
    lang: str
    weight: float
    kind: str
    publisher: str
    targeted: bool = False  # recherche ciblée (watchlist) : exclue des statistiques pour ne pas les biaiser

    @property
    def is_primary(self) -> bool:
        return self.kind == "primaire"


def load_sources(path: Path = SOURCES_PATH, include_disabled: bool = False) -> list[Source]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as e:
        raise ConfigError(f"Fichier introuvable : {path}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path.name} est mal formé (ligne {e.lineno}) : {e.msg}") from e

    sources: list[Source] = []
    seen_urls: set[str] = set()
    for i, entry in enumerate(raw.get("sources", []), start=1):
        if not include_disabled and not entry.get("actif", True):
            continue
        try:
            name, url, region = entry["nom"], entry["url"], entry["region"]
        except KeyError as e:
            raise ConfigError(f"sources.json, source n°{i} : champ {e} manquant") from None
        if region not in REGIONS and region != GLOBAL:
            raise ConfigError(f"sources.json, « {name} » : région inconnue « {region} »")
        kind = entry.get("type", "media")
        if kind not in KINDS:
            raise ConfigError(f"sources.json, « {name} » : type inconnu « {kind} »")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append(Source(
            name=name,
            url=url,
            region=region,
            country=entry.get("pays", ""),
            lang=entry.get("langue", "en"),
            weight=float(entry.get("poids", 1.0)),
            kind=kind,
            publisher=entry.get("editeur", name),
        ))
    return sources
