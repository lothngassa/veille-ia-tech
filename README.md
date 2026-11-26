<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lothngassa/veille-ia-tech/main/assets/banner-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/lothngassa/veille-ia-tech/main/assets/banner-light.svg">
  <img alt="AI News Watch. Every evening at 8 pm, the 5 to 10 stories that matter. By Loth Ngassa." src="https://raw.githubusercontent.com/lothngassa/veille-ia-tech/main/assets/banner-dark.svg" width="100%">
</picture>

<br>

**In English.** Every evening at 8 pm it reads more than 2,500 articles from over 140 sources across 7 world regions, merges duplicates, ranks stories by how many independent outlets cover them and sends the 5 to 10 that matter as one Telegram message. The core needs no dependency and no API key (an optional Claude analysis exists). It runs for about a minute a day. A real run on 20 October 2026: 2,607 articles, 141 sources, 7 stories.

The rest of this page is the user guide, in French.

---

# Veille IA & Tech

**Chaque soir à 20h, les 5 à 10 actus IA & tech qui comptent vraiment dans le monde, sur Telegram.**
Pas une liste interminable : le programme lit plus de 2 500 articles par jour et ne garde que l'essentiel.

- **Court** : 5 sujets minimum, 7 d'habitude, 10 seulement les jours très chargés.
- **Le monde entier** : plus de 140 sources sur les 7 régions (Amérique du Nord, Amérique latine, Europe, Afrique,
  Moyen-Orient, Asie, Océanie) : médias tech, blogs officiels (OpenAI, Google, NVIDIA, Microsoft…), Google News par
  pays, Reddit, Hacker News et YouTube.
- **Gratuit et léger** : un script Python sans aucune dépendance et sans clé API. Il tourne environ une minute par
  jour, puis s'arrête.
- **Rattrapage** : PC éteint à 20h ? Le brief part dès que tu ouvres ta session, avec le meilleur de tout ce que
  tu as manqué depuis le dernier envoi (jusqu'à 7 jours).

---

## Ce que tu reçois

Un seul message, une seule notification :

```text
━━━━━━━━━━━━━━━━━━
AI · TECH BRIEF
MARDI 20 OCTOBRE 2026 · 20:00
━━━━━━━━━━━━━━━━━━
2 607 articles · 141 sources · 7 régions · dernières 24 h
→ les 7 sujets qui comptent

1. 🧠 US orders federal agencies to remove China's DeepSeek AI from their systems
The US has ordered federal civilian agencies to remove DeepSeek products…
🇺🇸 TechCrunch · The Guardian · CNBC Tech +7 médias

2. 💾 ByteDance, Alibaba et Tencent commandent à nouveau pour 35 milliards de dollars de puces NVIDIA
Malgré les difficultés d'accès aux produits NVIDIA, les géants chinois…
🇫🇷 Clubic · TechCrunch · CNBC Tech +23 médias

3. …

⚙️ COULISSES (repliées) : articles collectés, doublons fusionnés, sources indisponibles
```

### Comment les sujets sont choisis

- **Importance = nombre de vrais médias indépendants** qui racontent l'histoire, avec un bonus pour les annonces
  officielles, l'IA et la fraîcheur.
- **Une dépêche reprise mot pour mot** par 25 journaux ne compte qu'une fois, et les sites de communiqués de presse
  ne comptent presque pas.
- **Une même actu en plusieurs langues** n'occupe qu'une place, et son **titre s'affiche en français** dès qu'un média
  francophone la couvre.
- **Un sujet déjà envoyé la veille est relégué**, sauf s'il a vraiment évolué.
- **Le nombre de sujets s'adapte** : les 6ᵉ et 7ᵉ doivent être repris par au moins 3 médias indépendants, et les 8ᵉ à
  10ᵉ par au moins 5.

Les titres non francophones restent dans leur langue d'origine (surtout l'anglais).

> Tu veux plus de détail ? `"format": "complet"` dans `config.json` ajoute le tour du monde par région, la watchlist,
> les vidéos du jour et le pouls des secteurs. L'analyse par Claude (clé API payante) est aussi disponible en option.

---

## Installation (5 minutes)

**Prérequis** : Windows et Python 3.10 ou plus récent (déjà installé sur ce PC). Aucune clé API nécessaire.

### 1. Crée ton bot Telegram

1. Dans Telegram, cherche **BotFather** et ouvre **@BotFather** (badge bleu certifié). Appuie sur **Démarrer**.
2. Envoie `/newbot`.
3. Donne un **nom** au bot, par exemple `Ma Veille IA`.
4. Donne un **identifiant** qui finit par `bot`, sans espace, par exemple `maveille_ia_bot`. S'il est pris, essaie
   une variante.
5. BotFather te donne un **token** (`123456789:AAH…`). Copie-le et ne le partage avec personne (s'il fuite :
   `/revoke` dans BotFather).

### 2. Lance l'assistant

Double-clique sur **`INSTALLER.bat`** (ou `python veille.py configurer`), puis :

1. colle le token (clic droit dans la fenêtre) et appuie sur Entrée ;
2. dans Telegram, ouvre ton bot, appuie sur **Démarrer** et envoie `bonjour` : l'assistant **détecte ton chat_id
   tout seul** et t'envoie un message de test ;
3. heure d'envoi : Entrée pour garder 20:00 ;
4. analyse par Claude : Entrée (non) ;
5. tâche planifiée : Entrée (oui) ;
6. « Envoyer un premier brief maintenant ? » : `o`.

C'est tout. Le brief arrive désormais chaque soir. Le PC doit simplement être allumé avec ta session ouverte ; tu le
reçois sur ton téléphone même si Telegram est fermé sur le PC.

---

## Comment fonctionne l'envoi automatique

La tâche planifiée « Veille IA Tech » se déclenche :

| Quand | Ce qui se passe |
| --- | --- |
| Chaque jour à 20:00 (PC allumé) | Le brief du jour part. |
| À l'ouverture de ta session (+2 min) | Si le brief d'hier n'a pas pu partir (PC éteint), il part maintenant avec **tout depuis le dernier envoi**. Sinon, rien. |
| Le PC était en veille à 20:00 | Windows lance la tâche dès le réveil. |

Garanties :

- **Jamais deux fois la même édition**, même si plusieurs déclencheurs tombent en même temps (verrou et mémoire
  des éditions envoyées).
- **Jamais deux fois le même article** d'un jour sur l'autre ; un sujet déjà traité la veille est relégué, sauf
  développement réel.
- **Au démarrage, attente du réseau** : le programme patiente jusqu'à 10 minutes que le Wi-Fi se connecte.
- **Nouvel essai en cas de coupure**, puis message d'alerte sur Telegram si l'envoi échoue vraiment.
- **Aucun envoi de brief vide** si internet est tombé pendant la collecte.

---

## Commandes

| Commande | Rôle |
| --- | --- |
| `python veille.py configurer` | Assistant d'installation (relançable à tout moment) |
| `python veille.py apercu` | Génère le brief **sans l'envoyer** et l'ouvre dans ton navigateur (`apercu.html`) |
| `python veille.py apercu --sans-ia` | Idem, sans appeler Claude (gratuit) |
| `python veille.py envoyer` | Envoie le brief maintenant |
| `python veille.py statut` | Configuration, dernier envoi, prochaine exécution de la tâche |
| `python veille.py sources` | Vérifie que chaque flux répond |
| `python veille.py tester` | Envoie un message de test sur Telegram |
| `python veille.py installer` / `desinstaller` | Crée ou supprime la tâche planifiée |

Raccourcis : `INSTALLER.bat`, `APERCU.bat`, `ENVOYER_MAINTENANT.bat`.

---

## Personnaliser

Tout se règle dans `config.json` (créé par l'assistant ; modèle dans `config.example.json`).

| Réglage | Par défaut | Effet |
| --- | --- | --- |
| `heure_envoi` | `"20:00"` | Heure du brief. Après modification : `python veille.py installer` |
| `rattrapage` | `true` | Envoyer le brief manqué au prochain démarrage |
| `fenetre_heures` | `24` à `168` | Période couverte : depuis le dernier envoi, bornée (168 h = 7 jours) |
| `format` | `"court"` | `"court"` : seulement les sujets qui comptent. `"complet"` : + tour du monde, watchlist, vidéos, pouls |
| `selection.min` / `habituel` / `max` | `5` / `7` / `10` | Nombre de sujets : minimum, habituel, jours très chargés |
| `selection.max_par_source` | `2` | Sujets maximum venant d'un même média |
| `selection.par_region` | `5` | Sujets par région dans le tour du monde (format complet) |
| `ia.active` | `false` | Analyse par Claude (nécessite une clé API payante) |
| `ia.modele` | `claude-opus-5-5` | Modèle Claude. `claude-sonnet-5-5` coûte environ deux fois moins cher |
| `ia.effort` | `medium` | `low` (moins cher), `medium` ou `high` (analyse plus poussée) |
| `ia.api_key` | `""` | Vide : la variable d'environnement `ANTHROPIC_API_KEY` est utilisée |
| `watchlist` | Claude Code, Anthropic, OpenAI, Google, NVIDIA, Microsoft, Agents IA, MCP, Open source | Sujets suivis : léger coup de pouce dans le classement (listés en format complet) |
| `watchlist_google_news` | `true` | Ajoute une recherche Google News par sujet suivi |

**Watchlist** : une entrée peut être un simple mot (`"Mistral"`) ou un objet
`{"nom": "...", "requete": "requête Google News", "motif": "expression régulière"}`.

**Sources** : `sources.json` contient les 137 flux (le champ `_aide` en tête de fichier explique chaque réglage).
Pour en ajouter un, copie une ligne, adapte-la, puis lance `python veille.py sources` pour vérifier qu'il répond.
Pour une chaîne YouTube : `https://www.youtube.com/feeds/videos.xml?channel_id=UC…`.

---

## Et X, Instagram, Facebook, TikTok ?

Ces plateformes ne sont pas intégrées, volontairement :

- **X (Twitter)** : l'accès en lecture à l'API coûte au moins 200 $ par mois, et aspirer le site enfreint ses
  conditions d'utilisation.
- **Instagram, Facebook, TikTok** : aucun moyen public et autorisé de lire leurs fils. L'aspiration est interdite
  et casse régulièrement.
- En pratique, toute annonce importante faite sur ces réseaux est reprise dans l'heure par les médias et les blogs
  officiels, qui sont tous dans les sources.

Ce qui est couvert : médias du monde entier, sources primaires (blogs officiels), Google News (15 éditions
nationales, des recherches par pays et une recherche par sujet de ta watchlist), Reddit, Hacker News et YouTube.

---

## Comment le tri est fait

1. **Collecte** des 140+ flux en parallèle, en 75 secondes maximum : une source en panne ou trop lente ne bloque
   jamais les autres.
2. **Nettoyage** : liens de suivi retirés, promos, bons plans et contenus sponsorisés écartés.
3. **Regroupement** : les articles qui racontent la même histoire forment un seul sujet. La comparaison des titres
   donne plus de poids aux mots rares, et un garde-fou empêche les fusions en chaîne.
4. **Région** : vote entre le pays cité dans le titre et l'origine des médias (une fintech nigériane couverte par
   TechCrunch va en Afrique).
5. **Importance** : couverture *indépendante* (une dépêche reprise mot pour mot par 25 journaux compte une fois,
   les sites obscurs et les communiqués presque pas), source primaire, sujet IA, fraîcheur ; un sujet déjà envoyé
   la veille est relégué.
6. **Sélection** : 5 sujets d'office, puis jusqu'à 7 ou 10 selon l'importance (voir plus haut). Une même actu en
   plusieurs langues n'occupe qu'une place.
7. **Optionnel, analyse Claude** : jusqu'à 120 sujets candidats sont confiés à Claude, qui rédige le brief.
   Claude n'écrit jamais de lien : les liens affichés viennent toujours des flux d'origine. S'il est indisponible,
   le brief automatique part quand même.

---

## Dépannage

| Problème | Solution |
| --- | --- |
| Rien reçu à 20h | `python veille.py statut` : la tâche est-elle installée ? Quel est le dernier résultat ? |
| Erreur dans le statut | Consulte `logs/veille.log` |
| Une source est en échec | `python veille.py sources`. Les sites changent parfois d'adresse : désactive-la (`"actif": false`) ou corrige l'URL |
| « Analyse IA indisponible » dans les coulisses | Clé, quota ou réseau : le message précise la cause |
| Changer de bot ou de conversation | Relance `python veille.py configurer` |
| Tout arrêter | `python veille.py desinstaller` |

---

## Organisation du code

```text
veille.py              point d'entrée
veille/
  cli.py               commandes, mode automatique
  pipeline.py          collecte → analyse → brief → envoi ; calendrier et rattrapage
  fetch.py             téléchargement parallèle, lecture RSS/Atom tolérante
  analyze.py           secteurs, bruit, regroupement, régions, score, pouls, watchlist
  brief_ai.py          prompt et appel à Claude, validation de la réponse
  render.py            mise en page Telegram, découpage des messages, aperçu HTML
  telegram.py          client Telegram minimal
  state.py             mémoire (éditions, articles vus, historique), verrou
  scheduler.py         tâche planifiée Windows
  setup_wizard.py      assistant de configuration
sources.json           les flux surveillés
tests/                 python -m unittest discover -s tests -t .
```

Données locales (non versionnées) : `config.json` (contient tes secrets), `data/` (mémoire et historique des
briefs, 60 jours) et `logs/` (journal, 4 Mo maximum).
