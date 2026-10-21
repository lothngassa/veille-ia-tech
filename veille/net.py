"""Connexions réseau plus robustes.

Par défaut, Python essaie les adresses d'un site (IPv6, IPv4…) l'une après l'autre avec un délai d'attente long :
une seule adresse injoignable coûte environ 21 secondes sous Windows avant de passer à la suivante. Ici, chaque
adresse dispose de quelques secondes pour répondre, et on alterne IPv6 / IPv4 : un réseau capricieux ne ralentit
plus la collecte.
"""

from __future__ import annotations

import socket
from itertools import chain, zip_longest

CONNECT_TIMEOUT = 5.0
_original_create_connection = socket.create_connection


def _interleave(infos: list) -> list:
    """Alterne les familles d'adresses en gardant celle que le système préfère en premier."""
    if not infos:
        return infos
    first = infos[0][0]
    preferred = [i for i in infos if i[0] == first]
    others = [i for i in infos if i[0] != first]
    return [i for i in chain.from_iterable(zip_longest(preferred, others)) if i is not None]


def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *args, **kwargs):
    host, port = address[0], address[1]
    infos = _interleave(socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM))
    has_timeout = timeout is not socket._GLOBAL_DEFAULT_TIMEOUT and timeout is not None
    last_error: OSError | None = None
    for family, type_, proto, _, sockaddr in infos:
        sock = socket.socket(family, type_, proto)
        try:
            sock.settimeout(min(CONNECT_TIMEOUT, timeout) if has_timeout else CONNECT_TIMEOUT)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            sock.settimeout(timeout if has_timeout else None)
            return sock
        except OSError as e:
            last_error = e
            sock.close()
    raise last_error or OSError(f"aucune adresse joignable pour {host}")


def install() -> None:
    """À appeler une fois au démarrage : s'applique à toutes les connexions du programme (flux, Telegram, Claude)."""
    socket.create_connection = create_connection
