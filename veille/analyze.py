"""Analyse : nettoyage, filtrage du bruit, regroupement par sujet, secteurs, régions, score et sélection."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cached_property
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .fetch import FeedResult
from .regions import GLOBAL, REGIONS, detect_regions, resolve_region

# --------------------------------------------------------------------------- Secteurs

# clé -> (libellé court, emoji, motif insensible à la casse, motif sensible à la casse)
SECTORS: dict[str, tuple[str, str, str, str]] = {
    "agents": (
        "Agents IA", "🤖",
        r"agents? (?:ia|d['’]ia|intelligents?|autonomes?|de codage)|ai agents?|agentic|agentique|model context protocol"
        r"|computer use|claude code|codex|devin|manus|operator agent|multi-agents?|agent builder",
        r"\bMCP\b|\bA2A\b",
    ),
    "modeles": (
        "Modèles", "🧠",
        r"chatgpt|gpt-?\d[\w.]*|claude (?:opus|sonnet|haiku|fable|\d)|\bclaude\b(?= ai| model| app)|gemini|llama ?\d|grok ?\d?"
        r"|qwen|deepseek|mistral (?:large|medium|small)|large language models?|grands? mod[eè]les? de langage|\bllms?\b"
        r"|foundation models?|frontier models?|reasoning models?|mod[eè]les? (?:d['’]ia|de raisonnement|fondation)"
        r"|multimodal|benchmark|text-to-(?:video|image)|sora|veo ?\d|midjourney|image generat\w+",
        r"\bLLMs?\b|\bAGI\b",
    ),
    "opensource": (
        "Open source", "🔓",
        r"open[- ]source|open[- ]weights?|poids ouverts|code ouvert|hugging ?face|apache 2\.0|mit license|ollama|llama\.cpp",
        "",
    ),
    "devtools": (
        "Devtools", "🛠️",
        r"developers?|d[ée]veloppeurs?|coding|codage|programming|programmation|github|copilot|cursor|windsurf|\bide\b"
        r"|\bsdk\b|\bapi\b|vibe coding|software engineer\w*|ing[ée]nieurs? logiciels?|devops|kubernetes|python|rust\b",
        "",
    ),
    "puces": (
        "Puces", "💾",
        r"semiconduct\w+|semi-conducteurs?|\bchips?\b|chipmakers?|\bpuces?\b|\bgpus?\b|nvidia|tsmc|asml|qualcomm|broadcom"
        r"|sk hynix|micron|foundry|fonderie|wafers?|data ?cent(?:er|re)s?|centres? de donn[ée]es|supercalculat\w+"
        r"|supercomputer|\bhbm\d?\b|blackwell|rubin|tpus?\b|compute capacity|capacit[ée] de calcul",
        r"\bAMD\b|\bIntel\b|\bArm\b",
    ),
    "robotique": (
        "Robotique", "🦾",
        r"robots?\b|robotique|robotics|humano[iï]des?|drones?\b|robotaxis?|waymo|self-driving|autonomous (?:driving|vehicles?)"
        r"|v[ée]hicules? autonomes?|conduite autonome|\bfsd\b|optimus|figure ai|boston dynamics|unitree",
        "",
    ),
    "cyber": (
        "Cyber", "🔐",
        r"cyber\w*|hack(?:er|ers|ed|ing)?\b|piratage|pirat[ée]s?|ransomware|ran[cç]ongiciels?|malware|logiciels? malveillants?"
        r"|phishing|hame[cç]onnage|data breach|fuites? de donn[ée]es|vuln[ée]rabilit\w+|vulnerabilit\w+|failles?\b"
        r"|zero-day|ddos|spyware|logiciels? espions?|\bcve-\d",
        "",
    ),
    "regulation": (
        "Régulation", "⚖️",
        r"regulat\w+|r[ée]glementation|r[ée]gulation|r[ée]gulateurs?|ai act|lawsuits?|proc[eè]s|poursuites?|antitrust"
        r"|autorit[ée] de la concurrence|competition (?:authority|watchdog)|\bfined\b|amendes?|\bbans?\b|interdi\w+|sanctions?"
        r"|tariffs?|droits de douane|export controls?|contr[oô]les? (?:à|a) l['’]exportation|senate|s[ée]nat|parlement"
        r"|parliament|commission europ[ée]enne|european commission|cnil|rgpd|gdpr|copyright|droits? d['’]auteur"
        r"|souverainet[ée]|sovereign\w*|executive order|d[ée]cret",
        r"\bFTC\b|\bFCC\b|\bDOJ\b|\bDMA\b|\bDSA\b|\bCongress\b",
    ),
    "financement": (
        "Financement", "💰",
        r"\braises?\b|\braised\b|funding|lev[ée]e de fonds|l[eè]ve \d|s[ée]ries? [a-e]\b|series [a-e]\b|seed round"
        r"|valuation|valoris[ée]e?|valorisation|unicorns?|licornes?|\bipo\b|introduction en bourse|acquires?\b|acquisition"
        r"|rach[eè]te|rachat|merger|fusion|venture capital|capital-risque|investit|invests?\b|investment round|tour de table",
        "",
    ),
    "mobile": (
        "Mobile", "📱",
        r"smartphones?|iphone|android|galaxy [sazf]\d*|pixel \d+|\b[56]g\b|t[ée]l[ée]coms?|telecom\w*|op[ée]rateurs?"
        r"|carriers?|fibre optique|fiber|mobile money|m-pesa|safaricom|airtel|vodacom|xiaomi",
        r"\bMTN\b|\bOrange\b",
    ),
    "espace": (
        "Espace", "🚀",
        r"spacex|starship|starlink|nasa\b|\besa\b|fus[ée]es?|rockets?|blue origin|orbit\w*|orbite|spatiale?s?|satellites?",
        "",
    ),
    "fintech": (
        "Fintech", "💳",
        r"fintech|bitcoin|crypto\w*|blockchain|stablecoins?|paiements?|payments?|n[ée]obanques?|neobank|wallets?",
        "",
    ),
    "quantique": (
        "Quantique", "⚛️",
        r"quantum|quantique|qubits?",
        "",
    ),
}

# Vocabulaire général de l'IA : un article « parle d'IA » s'il touche à ces termes ou aux secteurs IA.
_AI_CI = re.compile(
    r"intelligence artificielle|artificial intelligence|inteligencia artificial|intelig[eê]ncia artificial"
    r"|k[üu]nstliche intelligenz|generative ai|ia g[ée]n[ée]rative|machine learning|apprentissage automatique"
    r"|deep learning|neural net\w*|r[ée]seaux? de neurones|openai|anthropic|deepmind|mistral ai|chatbots?|xai\b"
    r"|perplexity|superintelligen\w+|hugging ?face",
    re.IGNORECASE,
)
_AI_CS = re.compile(r"\b(?:AI|IA|A\.I\.|KI|GenAI)\b")
AI_SECTORS = {"agents", "modeles", "opensource"}

_SECTOR_PATTERNS = {
    key: (re.compile(ci, re.IGNORECASE) if ci else None, re.compile(cs) if cs else None)
    for key, (_, _, ci, cs) in SECTORS.items()
}
# Ordre de priorité pour l'emoji principal d'un sujet.
_PRIMARY_ORDER = ["agents", "modeles", "opensource", "cyber", "puces", "financement", "regulation", "robotique",
                  "devtools", "espace", "quantique", "fintech", "mobile"]


def sectors_of(text: str) -> list[str]:
    found = []
    for key, (ci, cs) in _SECTOR_PATTERNS.items():
        if (ci and ci.search(text)) or (cs and cs.search(text)):
            found.append(key)
    return found


def is_ai_text(text: str, sectors: list[str]) -> bool:
    return bool(_AI_CI.search(text) or _AI_CS.search(text) or AI_SECTORS.intersection(sectors))


def primary_emoji(sectors: list[str], is_ai: bool) -> str:
    for key in _PRIMARY_ORDER:
        if key in sectors:
            return SECTORS[key][1]
    return "🧠" if is_ai else "💻"


# --------------------------------------------------------------------------- Bruit

# Contenus commerciaux et jeux. Attention aux faux positifs : « deal » seul veut dire « accord » dans l'actu
# (« Microsoft signs AI deal »), on ne vise donc que les tournures de bons plans.
_NOISE = re.compile(
    r"\b(?:bons? plans?|code promo|promos?\b|soldes|black friday|cyber monday|prime day|coupons?|% off|on sale"
    r"|deal alert|deals? of the (?:day|week)|(?:best|daily|top|early|holiday|today['’]s)\s+(?:\w+\s+){0,3}deals"
    r"|meilleures? offres?|sponsored|sponsoris[ée]e?|partenariat commercial|publi-?r[ée]dactionnel|horoscope"
    r"|wordle|quordle|nyt strands|strands hints?|connections hints?|hints?,? (?:and )?answers?|quiz du jour"
    r"|best .{0,40} to buy|mejores ofertas|ofertas del d[ií]a|descuentos?|descont\w*|promo[cç][aã]o|sem juros"
    r"|cupom|cupones?|specs? (?:&|and) prices?"
    r"|price in (?:kenya|nigeria|ghana|south africa|uganda|india|pakistan)"
    r"|prix (?:au|en) (?:maroc|s[ée]n[ée]gal|c[oô]te d['’]ivoire|cameroun|alg[ée]rie|tunisie))\b",
    re.IGNORECASE,
)
_TECH_HINT = re.compile(
    r"tech|num[ée]rique|digital|internet|logiciel|software|startup|start-up|app\b|application|données|data|cloud"
    r"|ordinateur|computer|smartphone|r[ée]seau social|social media|t[ée]l[ée]com|innovation|algorithm",
    re.IGNORECASE,
)
_SNIPPET_JUNK = re.compile(
    r"(The post .*? appeared first on .*?\.?$)|(L['’]article .*? est apparu en premier sur .*?\.?$)"
    r"|(Continue reading.*$)|(Read more.*$)|(Lire la suite.*$)|(\[…\]|\[\.\.\.\]|…$)|(Comments$)",
    re.IGNORECASE,
)


def clean_snippet(text: str, title: str, limit: int = 220) -> str:
    text = _SNIPPET_JUNK.sub("", text).strip()
    if not text or text.lower().startswith(title.lower()[:40]) and len(text) < len(title) + 20:
        return ""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.-–— ")
    return cut + "…"


# --------------------------------------------------------------------------- URL & tokens

_TRACKING = re.compile(
    r"^(?:utm_\w+|fbclid|gclid|mc_\w+|ref|ref_src|cmpid|ocid|xtor|at_\w+|guccounter|guce_\w+|smid|taid"
    r"|wt\.mc_id|cid|ito|itm_\w+|sr_share|share|mbid|rss|rss_id|from)$",
    re.IGNORECASE,
)


def clean_url(url: str) -> str:
    """Retire les paramètres de suivi (utm_..., fbclid...)."""
    p = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), ""))


def url_key(url: str) -> str:
    p = urlsplit(clean_url(url))
    host = (p.hostname or "").removeprefix("www.").removeprefix("m.")
    raw = f"{host}{p.path.rstrip('/')}?{p.query}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


_STOPWORDS = set("""
the and for with from that this these those into about after over than says said will can could would may might
more most how why what who when where which their they them his her its our your are was were been being has have
had not but just now new via amid against under report reports update latest first year years day week today
launch launches launched unveil unveils unveiled announce announces announced reveals introduces releases release
les des une pour par sur dans avec sans sous cet cette ces qui que quoi dont est sont ete etre ont plus moins son
ses leur leurs nous vous ils elles mais comme apres avant entre selon vers chez fait faire nouveau nouvelle
nouveaux nouvelles annonce lance devoile veut peut tout tous toute toutes deja encore aussi tres bien voici
los las una unos del con sin que sus por para como mas sobre esta este nos nas dos das com sem mais uma
der die das und oder ein eine mit fur von den dem des ist sind auf aus bei nach
""".split())


def title_tokens(title: str) -> frozenset[str]:
    text = unicodedata.normalize("NFKD", title.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    out = set()
    for word in re.findall(r"[a-z0-9]+", text):
        if word in _STOPWORDS or (len(word) < 3 and not word.isdigit()):
            continue
        if len(word) > 4 and word.endswith("s"):
            word = word[:-1]
        out.add(word)
    return frozenset(out)


def similar(a: frozenset, b: frozenset) -> bool:
    """Similarité simple entre deux titres (utilisée pour reconnaître un sujet déjà envoyé les jours précédents)."""
    inter = len(a & b)
    if inter < 2:
        return False
    union = len(a) + len(b) - inter
    jaccard = inter / union
    overlap = inter / min(len(a), len(b))
    return (inter >= 3 and (jaccard >= 0.4 or overlap >= 0.65)) or jaccard >= 0.6


SIMILARITY_THRESHOLD = 0.25
# Garde-fou contre les fusions en chaîne : un article « à cheval » sur deux histoires (« Anthropic crée un fonds,
# Musk offre des actions SpaceX ») ne doit pas souder les deux. On exige donc aussi un minimum de ressemblance
# avec le représentant du sujet.
LEAD_SIMILARITY_FLOOR = 0.12


def idf_weights(articles: list) -> dict[str, float]:
    """Poids d'un mot = sa rareté dans les titres du jour : « saoudien » pèse plus que « OpenAI »."""
    n = len(articles)
    df = Counter(t for a in articles for t in a.tokens)
    return {t: math.log(n / c) for t, c in df.items()}


def weighted_similarity(a: frozenset, b: frozenset, idf: dict[str, float]) -> float:
    """Jaccard pondéré par la rareté des mots, entre 0 et 1."""
    inter = a & b
    if len(inter) < 2:
        return 0.0
    denom = sum(idf.get(t, 0.0) for t in a | b)
    return sum(idf.get(t, 0.0) for t in inter) / denom if denom else 0.0


# --------------------------------------------------------------------------- Modèle

@dataclass
class Article:
    title: str
    url: str
    key: str
    summary: str
    published: datetime | None
    source: str
    publisher: str
    country: str
    region: str
    region_explicit: bool  # la région vient du contenu (titre) et pas seulement du média
    weight: float
    kind: str
    sectors: list[str]
    is_ai: bool
    tokens: frozenset
    targeted: bool = False  # issu d'une recherche ciblée (watchlist) : exclu des statistiques
    lang: str = "en"

    @property
    def direct(self) -> bool:
        return "news.google.com" not in self.url


def _region_vote(a: Article) -> int:
    if a.region_explicit:
        return 3
    return 1 if a.kind == "agregateur" else 2


@dataclass
class Story:
    """Un sujet : un ou plusieurs articles qui parlent de la même chose."""
    articles: list[Article]
    score: float = 0.0
    repeat: bool = False   # sujet proche d'un sujet déjà envoyé les jours précédents
    watched: bool = False  # concerne un sujet de la watchlist

    @property
    def lead(self) -> Article:
        return self.articles[0]

    @property
    def publishers(self) -> list[str]:
        return list(dict.fromkeys(a.publisher for a in self.articles))

    @property
    def coverage(self) -> int:
        return len(self.publishers)

    @cached_property
    def independent_coverage(self) -> float:
        """Couverture indépendante : combien de vrais médias distincts racontent cette histoire.

        - Une dépêche (AP, Reuters...) reprise mot pour mot par 25 journaux ne compte qu'une fois.
        - Un média reconnu compte 1 ; les sites obscurs comptent 0,25 chacun, 2 au total au maximum (sinon vingt
          sites de communiqués feraient passer une annonce mineure pour un événement).
        - Les recherches de la watchlist servent à trouver des articles, pas à mesurer l'importance : seuls les
          médias reconnus y comptent, et pour moitié.
        """
        seen_titles: set[frozenset] = set()
        reputable: dict[str, float] = {}
        obscure: set[str] = set()
        for a in self.articles:
            if a.tokens in seen_titles:
                continue
            seen_titles.add(a.tokens)
            if a.weight >= REPUTABLE_WEIGHT:
                value = min(a.weight, 1.0) * (0.5 if a.targeted else 1.0)
                reputable[a.publisher] = max(reputable.get(a.publisher, 0.0), value)
            elif not a.targeted:
                obscure.add(a.publisher)
        obscure -= reputable.keys()
        return sum(reputable.values()) + min(2.0, 0.25 * len(obscure))

    @cached_property
    def region(self) -> str:
        """Vote pondéré : pays cité dans un titre (3) > média de la région (2) > reprise Google News (1)."""
        votes: Counter = Counter()
        for a in self.articles:
            if a.region != GLOBAL:
                votes[a.region] += _region_vote(a)
        return votes.most_common(1)[0][0] if votes else GLOBAL

    @property
    def region_explicit(self) -> bool:
        """Le sujet concerne vraiment sa région (pays cité, ou couvert par un média local)."""
        return any(a.region_explicit or a.kind != "agregateur" for a in self.articles if a.region == self.region)

    @property
    def sectors(self) -> list[str]:
        return self.lead.sectors

    @property
    def is_ai(self) -> bool:
        return self.lead.is_ai or sum(a.is_ai for a in self.articles) * 2 > len(self.articles)

    @property
    def emoji(self) -> str:
        return primary_emoji(self.sectors, self.is_ai)

    @property
    def primary_source(self) -> Article | None:
        return next((a for a in self.articles if a.kind == "primaire"), None)

    @property
    def newest(self) -> datetime | None:
        dates = [a.published for a in self.articles if a.published]
        return max(dates) if dates else None


@dataclass
class Funnel:
    collected: int = 0      # articles reçus dans la période
    duplicates: int = 0     # articles fusionnés dans un sujet existant
    off_topic: int = 0      # promos, hors sujet
    already_sent: int = 0   # déjà envoyés lors d'une édition précédente
    stories: int = 0        # sujets uniques


@dataclass
class Analysis:
    stories: list[Story]
    videos: list[Article]
    funnel: Funnel
    sources_ok: int
    sources_failed: list[str]
    sector_counts: Counter       # articles par secteur
    region_counts: Counter       # articles par région
    ai_share: float              # part des articles qui parlent d'IA
    window_hours: float
    all_articles: list[Article] = field(default_factory=list)


# --------------------------------------------------------------------------- Pipeline

_HOT = re.compile(
    r"launch|lance|unveil|d[ée]voile|announc|annonce|billion|milliard|record|acqui|rachat|rach[eè]te|\bbans?\b"
    r"|interdi|lawsuit|proc[eè]s|layoffs?|licenci|\bipo\b|breakthrough|perc[ée]e|outage|panne|breach|fuite"
    r"|antitrust|\bfined?\b|amende|open-?sourc|releases?\b|partnership|partenariat",
    re.IGNORECASE,
)
_BIG = re.compile(
    r"openai|anthropic|google|alphabet|deepmind|microsoft|apple|\bmeta\b|amazon|nvidia|tesla|\bxai\b|spacex"
    r"|samsung|tsmc|huawei|alibaba|tencent|bytedance|baidu|deepseek|mistral|broadcom|oracle|softbank",
    re.IGNORECASE,
)


# Réputation des médias qui reviennent souvent dans Google News (les médias de sources.json gardent leur poids).
# Un média absent de la liste reçoit UNKNOWN_WEIGHT : fermes de contenu et sites obscurs pèsent peu.
REPUTATION = {
    "reuters": 1.3, "bloomberg": 1.3, "bloomberg.com": 1.3, "ap news": 1.3, "associated press": 1.3,
    "financial times": 1.3, "the wall street journal": 1.3, "wsj": 1.3, "the new york times": 1.3,
    "the economist": 1.3, "the washington post": 1.2, "cnbc": 1.2, "bbc": 1.3, "the guardian": 1.3,
    "le monde": 1.3, "le monde.fr": 1.3, "les echos": 1.2, "le figaro": 1.1, "france 24": 1.1, "rfi": 1.1,
    "jeune afrique": 1.1, "nikkei asia": 1.2, "south china morning post": 1.2, "the information": 1.2,
    "axios": 1.1, "semafor": 1.1, "fortune": 1.1, "politico": 1.1, "al jazeera": 1.1, "the verge": 1.3,
    "techcrunch": 1.3, "wired": 1.2, "ars technica": 1.3, "mit technology review": 1.3, "venturebeat": 1.1,
    "engadget": 1.0, "zdnet": 1.0, "cnet": 1.0, "business insider": 1.0, "forbes": 1.0, "the register": 1.1,
    "siliconangle": 1.0, "the decoder": 1.1, "euronews": 1.0, "the hindu": 1.1, "the economic times": 1.0,
    "mint": 1.0, "livemint": 1.0, "times of india": 1.0, "the times of india": 1.0, "moneycontrol": 1.0,
    "gulf news": 1.0, "khaleej times": 1.0, "the national": 1.0, "arab news": 1.0, "daily maverick": 1.0,
    "news24": 1.0, "techcabal": 1.2, "techcentral": 1.0, "the east african": 1.0, "nation": 1.0,
    "business daily": 1.0, "the straits times": 1.1, "channel newsasia": 1.1, "cna": 1.1, "the japan times": 1.1,
    "the korea herald": 1.0, "the korea times": 1.0, "yonhap news agency": 1.1, "abc news": 1.1,
    "the sydney morning herald": 1.1, "australian financial review": 1.2, "afr": 1.2, "rnz": 1.0,
    "nz herald": 1.0, "folha de s.paulo": 1.1, "el país": 1.2, "el pais": 1.2, "infobae": 1.0, "clarín": 1.0,
    "el financiero": 1.0, "expansión": 1.0, "valor econômico": 1.1, "exame": 1.0, "bloomberg línea": 1.1,
    "yahoo finance": 0.8, "investing.com": 0.7, "marketscreener.com": 0.5, "marketscreener": 0.5,
    # Fils de communiqués de presse : de la communication d'entreprise, pas du journalisme.
    "pr newswire": 0.3, "prnewswire": 0.3, "business wire": 0.3, "globenewswire": 0.3, "accesswire": 0.3,
    "ein presswire": 0.3, "prweb": 0.3, "newswire": 0.3, "openpr": 0.3,
}
UNKNOWN_WEIGHT = 0.6
REPUTABLE_WEIGHT = 0.8  # à partir de ce poids, un média compte pleinement dans la couverture


def publisher_profile(name: str, known: dict[str, tuple[float, str]]) -> tuple[float, str]:
    """(poids, pays) d'un média cité par Google News. Pays inconnu -> "" (drapeau 🌐)."""
    key = name.lower().strip()
    if key in known:
        return known[key]
    weight = REPUTATION.get(key) or REPUTATION.get(key.removeprefix("the ")) or UNKNOWN_WEIGHT
    return weight, ""


def _aggregated_publisher(item) -> tuple[str, str]:
    """Google News : titre « Titre - Média » et nom du média dans <source> (parfois une simple URL)."""
    name = item.source_name
    if name.startswith("http"):
        name = urlsplit(name).hostname or name
    name = name.removeprefix("www.")
    title = item.title
    for suffix in (f" - {item.source_name}", f" - {name}"):
        if item.source_name and title.endswith(suffix):
            title = title[: -len(suffix)].strip()
            break
    return title, name


def _to_article(item, source, known: dict[str, tuple[float, str]] | None = None) -> Article:
    title, summary = item.title, item.summary
    publisher, source_name, weight, country = source.publisher, source.name, source.weight, source.country
    if source.kind == "agregateur" and item.source_name:
        title, source_name = _aggregated_publisher(item)
        publisher = source_name
        weight, country = publisher_profile(source_name, known or {})
        summary = ""  # la description Google News ne fait que répéter le titre et le nom du média
    text = f"{title} {summary[:300]}"
    sectors = sectors_of(text)
    url = clean_url(item.link) if "news.google.com" not in item.link else item.link
    return Article(
        title=title,
        url=url,
        key=url_key(url),
        summary=clean_snippet(summary, title),
        published=item.published,
        source=source_name,
        publisher=publisher,
        country=country,
        region=resolve_region(source.region, title, summary[:300]),
        region_explicit=bool(detect_regions(title)),
        weight=weight,
        kind=source.kind,
        sectors=sectors,
        is_ai=is_ai_text(text, sectors),
        tokens=title_tokens(title),
        targeted=source.targeted,
        lang=source.lang,
    )


def _lead_rank(a: Article):
    """Le meilleur représentant d'un sujet : source primaire > lien direct > média de poids > avec extrait."""
    return (a.kind == "primaire", a.direct, a.weight, bool(a.summary), a.published.timestamp() if a.published else 0)


def _in_window(results: list[FeedResult], since: datetime, now: datetime):
    """(item, source) publiés dans la période. Flux sans dates : seulement les 10 premiers (les plus récents)."""
    future_limit = now + timedelta(hours=2)
    for result in results:
        if not result.ok:
            continue
        undated = 0
        for item in result.items:
            if item.published is None:
                undated += 1
                if undated <= 10:
                    yield item, result.source
            elif since <= item.published <= future_limit:
                yield item, result.source


def _is_noise(art: Article) -> bool:
    if len(art.title) < 15 or _NOISE.search(art.title):
        return True
    if art.kind == "generaliste":
        return not (art.is_ai or art.sectors or _TECH_HINT.search(f"{art.title} {art.summary}"))
    return False


def analyze(
    results: list[FeedResult],
    since: datetime,
    now: datetime,
    seen_keys: set[str],
    recent_tokens: list[frozenset],
) -> Analysis:
    funnel = Funnel()
    articles: list[Article] = []
    videos: list[Article] = []
    keys: set[str] = set()
    # Poids et pays des médias de sources.json, réutilisés quand Google News les cite.
    known = {r.source.publisher.lower(): (r.source.weight, r.source.country)
             for r in results if r.source.kind != "agregateur"}

    for item, source in _in_window(results, since, now):
        funnel.collected += 1
        art = _to_article(item, source, known)
        if art.key in seen_keys:
            funnel.already_sent += 1
        elif art.key in keys:
            funnel.duplicates += 1
        elif source.kind == "video":
            keys.add(art.key)
            videos.append(art)
        elif _is_noise(art):
            keys.add(art.key)
            funnel.off_topic += 1
        else:
            keys.add(art.key)
            articles.append(art)

    stories = _cluster(articles)
    funnel.duplicates += len(articles) - len(stories)
    funnel.stories = len(stories)

    for story in stories:
        story.repeat = any(similar(story.lead.tokens, t) for t in recent_tokens if t)
        story.score = _score(story, now)
    stories.sort(key=lambda s: s.score, reverse=True)

    # Statistiques sur la veille générale uniquement : les recherches ciblées (watchlist) les biaiseraient.
    general = [a for a in articles if not a.targeted]
    sector_counts = Counter(s for a in general for s in a.sectors)
    region_counts = Counter(a.region for a in general)
    ai_share = sum(a.is_ai for a in general) / len(general) if general else 0.0
    videos.sort(key=lambda v: (v.weight, v.published or now), reverse=True)

    return Analysis(
        stories=stories,
        videos=videos,
        funnel=funnel,
        sources_ok=sum(1 for r in results if r.ok),
        sources_failed=[r.source.name for r in results if not r.ok],
        sector_counts=sector_counts,
        region_counts=region_counts,
        ai_share=ai_share,
        window_hours=(now - since).total_seconds() / 3600,
        all_articles=articles,
    )


def _matching_story(art: Article, stories: list[Story], index: dict[str, set[int]], idf: dict) -> int | None:
    if len(art.tokens) < 2:
        return None
    counts = Counter(sid for tok in art.tokens for sid in index.get(tok, ()))
    best, best_sim = None, SIMILARITY_THRESHOLD
    for sid, inter in counts.most_common(25):
        if inter < 2:
            break
        members = stories[sid].articles
        # On compare aux premiers membres du sujet, pas seulement au représentant : les titres d'une même
        # histoire varient beaucoup (« accusé d'espionnage », « micro caché », « soutien saoudien »...).
        sim = max(weighted_similarity(art.tokens, m.tokens, idf) for m in members[:8])
        if sim < best_sim:
            continue
        if len(members) > 2 and weighted_similarity(art.tokens, members[0].tokens, idf) < LEAD_SIMILARITY_FLOOR:
            continue
        best, best_sim = sid, sim
    return best


def _cluster(articles: list[Article]) -> list[Story]:
    """Regroupe les articles qui racontent la même histoire (titres proches).

    Les articles sont parcourus du plus fiable au moins fiable : le premier de chaque sujet en devient le
    représentant. Un index mot -> sujets évite de comparer chaque article à tous les autres.
    """
    idf = idf_weights(articles)
    stories: list[Story] = []
    index: dict[str, set[int]] = {}
    for art in sorted(articles, key=_lead_rank, reverse=True):
        sid = _matching_story(art, stories, index, idf)
        if sid is None:
            sid = len(stories)
            stories.append(Story([art]))
        else:
            stories[sid].articles.append(art)
        if len(stories[sid].articles) <= 8:
            for tok in art.tokens:
                index.setdefault(tok, set()).add(sid)
    return _merge_related(stories, idf)


def _story_similarity(a: Story, b: Story, idf: dict) -> float:
    return max(weighted_similarity(x.tokens, y.tokens, idf) for x in a.articles[:12] for y in b.articles[:12])


def _related_pairs(stories: list[Story], idf: dict) -> list[tuple[float, int, int]]:
    """Paires de sujets (similarité, i, j) qui partagent au moins 2 mots et se ressemblent assez."""
    vocab = [frozenset(t for a in s.articles for t in a.tokens) for s in stories]
    index: dict[str, list[int]] = {}
    for i, words in enumerate(vocab):
        for tok in words:
            index.setdefault(tok, []).append(i)
    pairs = []
    for i, words in enumerate(vocab):
        shared = Counter(j for tok in words for j in index[tok] if j > i)
        for j in (j for j, count in shared.items() if count >= 2):
            sim = _story_similarity(stories[i], stories[j], idf)
            leads = weighted_similarity(stories[i].lead.tokens, stories[j].lead.tokens, idf)
            if sim >= SIMILARITY_THRESHOLD and leads >= LEAD_SIMILARITY_FLOOR:
                pairs.append((sim, i, j))
    return pairs


def _merge_related(stories: list[Story], idf: dict, max_size: int = 40) -> list[Story]:
    """Seconde passe : fusionne deux sujets dès qu'un article de l'un ressemble à un article de l'autre.

    Rattrape les grosses histoires dont les titres divergent (les articles arrivés tard dans un groupe peuvent
    faire le pont avec un autre groupe). La taille est plafonnée pour éviter les fusions en chaîne.
    """
    pairs = _related_pairs(stories, idf)
    parent = list(range(len(stories)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for _, i, j in sorted(pairs, reverse=True):
        ri, rj = root(i), root(j)
        if ri != rj and len(stories[ri].articles) + len(stories[rj].articles) <= max_size:
            keep, absorbed = min(ri, rj), max(ri, rj)
            stories[keep].articles.extend(stories[absorbed].articles)
            stories[absorbed].articles = []
            parent[absorbed] = keep

    merged = [s for s in stories if s.articles]
    for story in merged:
        story.articles.sort(key=_lead_rank, reverse=True)
    return merged


def _score(story: Story, now: datetime) -> float:
    lead = story.lead
    score = max(a.weight for a in story.articles)
    score += 1.6 * math.log2(max(story.independent_coverage, 1.0))  # plusieurs médias indépendants = sujet important
    if story.primary_source:
        score += 0.8
    if story.is_ai:
        score += 1.2
    if _HOT.search(lead.title):
        score += 0.6
    if _BIG.search(lead.title):
        score += 0.5
    newest = story.newest
    if newest:
        age_hours = max((now - newest).total_seconds() / 3600, 0)
        score += 0.8 * math.exp(-age_hours / 18)
    if all(a.kind == "communaute" for a in story.articles):
        score -= 0.8
    if story.repeat:
        score -= 2.5
    return round(score, 3)


# --------------------------------------------------------------------------- Sélection courte (5 à 10 sujets)

IMPORTANT_COVERAGE = 3.0  # au-delà du minimum : repris par au moins 3 médias indépendants
MAJOR_COVERAGE = 5.0      # au-delà du nombre habituel : au moins 5 médias indépendants
_YEAR = re.compile(r"(?:19|20)\d\d")
_GENERIC_TOKENS = {"app", "apps", "tech", "online", "internet", "digital", "data", "video", "startup", "startups",
                   "smartphone", "news"}


def _vocabulary(story: Story) -> frozenset[str]:
    return frozenset(t for a in story.articles[:8] for t in a.tokens)


def same_story_across_languages(a: Story, b: Story) -> bool:
    """Même histoire racontée dans deux langues (« Musk will give a SpaceX share… » / « Musk regalará una acción
    de SpaceX… »). D'une langue à l'autre, les mots communs sont presque toujours des noms propres ou des
    chiffres : deux en commun suffisent."""
    if a.lead.lang == b.lead.lang:
        return False  # même langue : le regroupement s'en est déjà chargé
    shared = {t for t in _vocabulary(a) & _vocabulary(b) if not _YEAR.fullmatch(t) and t not in _GENERIC_TOKENS}
    return len(shared) >= 2


def is_important(story: Story, threshold: float) -> bool:
    if story.independent_coverage >= threshold:
        return True
    return story.primary_source is not None and story.independent_coverage >= 2 and threshold <= IMPORTANT_COVERAGE


def pick_essentials(stories: list[Story], minimum: int = 5, usual: int = 7, maximum: int = 10,
                    max_per_source: int = 2, scan: int = 60) -> list[Story]:
    """Les sujets qui comptent : `minimum` d'office, puis jusqu'à `usual` s'ils sont vraiment repris
    (3 médias indépendants), et jusqu'à `maximum` seulement les jours très chargés (5 médias).

    Une même histoire déjà retenue dans une autre langue n'occupe pas de seconde place : ses articles rejoignent
    le sujet retenu (ce qui permet aussi d'afficher le titre en français quand il existe).
    """
    picked: list[Story] = []
    per_source: Counter = Counter()
    for story in stories[:scan]:
        if len(picked) >= maximum:
            break
        twin = next((p for p in picked if same_story_across_languages(story, p)), None)
        if twin:
            twin.articles.extend(story.articles)
            continue
        if per_source[story.lead.publisher] >= max_per_source:
            continue
        rank = len(picked) + 1
        if rank > minimum and not is_important(story, IMPORTANT_COVERAGE if rank <= usual else MAJOR_COVERAGE):
            continue
        picked.append(story)
        per_source[story.lead.publisher] += 1
    return picked


def display_article(story: Story) -> Article:
    """L'article à mettre en avant : en français si un média francophone fiable couvre le sujet."""
    return next((a for a in story.articles if a.lang == "fr" and a.weight >= 0.8), story.lead)


def mark_watched(stories: list[Story], items: list[WatchItem], bonus: float = 0.3) -> None:
    """Petit coup de pouce aux sujets de la watchlist (titre principal), puis nouveau tri."""
    for story in stories:
        if any(item.pattern.search(story.lead.title) for item in items):
            story.watched = True
            story.score = round(story.score + bonus, 3)
    stories.sort(key=lambda s: s.score, reverse=True)


# --------------------------------------------------------------------------- Sélection complète (format « complet »)

@dataclass
class Selection:
    top: list[Story]
    regions: dict[str, list[Story]]


def select(stories: list[Story], top_n: int, per_region: int, max_per_source: int) -> Selection:
    used: set[int] = set()

    def pick(candidates, n):
        out, per_source = [], Counter()
        for story in candidates:
            if id(story) in used or per_source[story.lead.publisher] >= max_per_source:
                continue
            out.append(story)
            used.add(id(story))
            per_source[story.lead.publisher] += 1
            if len(out) >= n:
                break
        return out

    top = pick(stories, top_n)
    regions = {}
    for key in REGIONS:
        in_region = [s for s in stories if s.region == key]
        # D'abord les sujets vraiment liés à la région (titre ou média local), puis le reste.
        in_region.sort(key=lambda s: (s.region_explicit, s.score), reverse=True)
        regions[key] = pick(in_region, per_region)
    return Selection(top=top, regions=regions)


# --------------------------------------------------------------------------- Watchlist

@dataclass
class WatchItem:
    name: str
    query: str
    pattern: re.Pattern


def watchlist_items(entries: list) -> list[WatchItem]:
    """Entrées de config : "Mistral" ou {"nom": ..., "requete": ..., "motif": ...}."""
    items = []
    for entry in entries:
        if isinstance(entry, str):
            entry = {"nom": entry}
        name = entry.get("nom", "").strip()
        if not name:
            continue
        motif = entry.get("motif") or rf"(?<![\w-]){re.escape(name)}(?![\w-])"
        items.append(WatchItem(
            name=name,
            query=entry.get("requete") or f'"{name}"',
            pattern=re.compile(motif, re.IGNORECASE),
        ))
    return items


def watch_matches(stories: list[Story], items: list[WatchItem], per_item: int = 3) -> dict[str, tuple[int, list[Story]]]:
    """Pour chaque terme suivi : nombre d'articles qui en parlent + meilleurs sujets."""
    out = {}
    for item in items:
        hits = []
        for story in stories:
            n = sum(1 for a in story.articles if item.pattern.search(f"{a.title} {a.summary}"))
            if n:
                hits.append((story, n))
        best = _title_matches_first([s for s, _ in hits], item.pattern)
        out[item.name] = (sum(n for _, n in hits), best[:per_item])
    return out


def _title_matches_first(stories: list[Story], pattern: re.Pattern) -> list[Story]:
    """D'abord les sujets dont le titre principal parle du terme suivi, puis par importance."""
    return sorted(stories, key=lambda s: (bool(pattern.search(s.lead.title)), s.score), reverse=True)


# --------------------------------------------------------------------------- Pouls des secteurs

@dataclass
class Pulse:
    key: str
    label: str
    emoji: str
    count: int
    per_day: float
    trend: str  # ↑↑ ↑ → ↓ ↓↓ ou · (pas encore d'historique)


_TRENDS = [(1.5, "↑↑"), (1.15, "↑"), (0.85, "→"), (0.6, "↓")]


def trend_arrow(per_day: float, past: list[float]) -> str:
    """Flèche de tendance : volume du jour comparé à la moyenne des jours précédents."""
    if not past:
        return "·"
    avg = sum(past) / len(past)
    ratio = per_day / avg if avg else 2.0
    for threshold, arrow in _TRENDS:
        if ratio >= threshold:
            return arrow
    return "↓↓"


def sector_pulse(analysis: Analysis, history: list[dict], limit: int = 7) -> list[Pulse]:
    """Volume par secteur ramené à 24 h, comparé à la moyenne des éditions précédentes."""
    hours = max(analysis.window_hours, 1)
    pulses = []
    for key, count in analysis.sector_counts.most_common(limit):
        label, emoji, _, _ = SECTORS[key]
        per_day = count * 24 / hours
        past = [h["secteurs"].get(key, 0) for h in history if "secteurs" in h]
        pulses.append(Pulse(key, label, emoji, count, per_day, trend_arrow(per_day, past)))
    return pulses


def sectors_per_day(analysis: Analysis) -> dict[str, float]:
    hours = max(analysis.window_hours, 1)
    return {k: round(v * 24 / hours, 1) for k, v in analysis.sector_counts.items()}
