"""Veille IA & Tech : point d'entrée. Lance « python veille.py » pour la liste des commandes."""

import sys

if sys.version_info < (3, 10):
    sys.exit("Veille IA & Tech nécessite Python 3.10 ou plus récent.")

from veille.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
