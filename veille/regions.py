"""Les 7 régions du monde, les drapeaux, et la détection du pays/région évoqué dans un titre."""

from __future__ import annotations

import re

# Ordre d'affichage dans le « Tour du monde ».
REGIONS: dict[str, tuple[str, str]] = {
    "amerique_nord": ("Amérique du Nord", "🌎"),
    "amerique_latine": ("Amérique latine", "🌎"),
    "europe": ("Europe", "🌍"),
    "afrique": ("Afrique", "🌍"),
    "moyen_orient": ("Moyen-Orient", "🌍"),
    "asie": ("Asie", "🌏"),
    "oceanie": ("Océanie", "🌏"),
}
GLOBAL = "monde"  # médias internationaux : la région est déduite du contenu de l'article


def region_label(key: str) -> str:
    return REGIONS.get(key, ("Monde", "🌐"))[0]


def region_emoji(key: str) -> str:
    return REGIONS.get(key, ("Monde", "🌐"))[1]


def flag(country: str | None) -> str:
    """'FR' -> 🇫🇷 ; inconnu -> 🌐."""
    if not country or len(country) != 2 or not country.isalpha():
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country.upper())


# Termes qui rattachent un article à une région. Ce sont des motifs regex (déjà échappés si besoin).
# Première liste : insensible à la casse. Seconde : sensible à la casse (sigles ambigus en minuscules).
_GAZETTEER: dict[str, tuple[list[str], list[str]]] = {
    "afrique": (
        [
            "afrique", "africa", "african", "africaine?s?", "nig[eé]ria", "nig[eé]rian[e]?s?", "lagos", "abuja",
            "kenya", "kenyan", "k[eé]nyan[e]?s?", "nairobi", "south africa", "afrique du sud", "sud-africaine?s?",
            "johannesburg", "cape town", "ghana", "ghan[eé]en(?:ne)?s?", "ghanaian", "accra",
            "egypt", "[eé]gypte", "egyptian", "[eé]gyptien(?:ne)?s?", "cairo", "le caire",
            "morocco", "maroc", "marocaine?s?", "moroccan", "casablanca", "rabat",
            "alg[eé]rie", "algeria", "alg[eé]rien(?:ne)?s?", "tunisi[ae]", "tunisien(?:ne)?s?",
            "s[eé]n[eé]gal", "s[eé]n[eé]galaise?s?", "dakar", "c[oô]te d['’]ivoire", "ivory coast", "ivoirien(?:ne)?s?",
            "abidjan", "ethiopia", "[eé]thiopie", "ethiopian", "addis[- ]ab[ae]ba", "rwanda", "rwandaise?s?", "kigali",
            "uganda", "ouganda", "kampala", "tanzani[ae]", "cameroon", "cameroun", "camerounaise?s?", "douala",
            "yaound[eé]", "zambi[ae]", "zimbabwe", "mozambique", "angola", "namibi[ae]", "botswana", "burkina faso",
            "b[eé]nin", "togo", "gabon", "kinshasa", "rdc", "madagascar", "safaricom", "m-pesa", "flutterwave",
            "paystack", "jumia", "andela", "moniepoint", "vodacom", "airtel africa",
        ],
        ["MTN", "Mali", "Niger", "Congo"],
    ),
    "moyen_orient": (
        [
            "moyen-orient", "middle east", "saudi", "arabie saoudite", "saoudien(?:ne)?s?", "riyadh", "riyad", "neom",
            "united arab emirates", "[eé]mirats arabes unis", "[eé]mirati(?:e)?s?", "dubai", "duba[iï]", "abu dhabi",
            "abou dhabi", "qatar", "qatari", "doha", "kuwait", "kowe[iï]t", "bahrain", "bahre[iï]n",
            "isra[eë]l", "israeli", "isra[eé]lien(?:ne)?s?", "tel aviv", "iran", "iranian", "iranien(?:ne)?s?",
            "t[uü]rkiye", "turquie", "istanbul", "jordanie", "liban", "lebanon", "g42", "mubadala", "aramco",
        ],
        ["UAE", "EAU", "MENA", "MGX", "PIF", "Turkey", "Turkish", "Jordan", "Oman"],
    ),
    "asie": (
        [
            "asia", "asie", "asian", "asiatiques?", "china", "chine", "chinese", "chinoise?s?", "beijing", "p[eé]kin",
            "shanghai", "shenzhen", "hangzhou", "guangzhou", "hong kong", "japan", "japon", "japanese",
            "japonaise?s?", "tokyo", "osaka", "korea", "cor[eé]e", "korean", "cor[eé]en(?:ne)?s?", "seoul", "s[eé]oul",
            "india", "inde", "indian", "indien(?:ne)?s?", "bengaluru", "bangalore", "mumbai", "new delhi",
            "hyderabad", "ta[iï]wan", "taiwanese", "ta[iï]wanaise?s?", "taipei", "singapore", "singapour",
            "singaporean", "indonesia", "indon[eé]sie", "indonesian", "jakarta", "vietnam", "vi[eê]t nam",
            "vietnamese", "vietnamien(?:ne)?s?", "philippines", "filipino", "manila", "thailand", "tha[iï]lande",
            "bangkok", "malaysia", "malaisie", "malaysian", "kuala lumpur", "pakistan", "pakistani",
            "pakistanaise?s?", "bangladesh", "sri lanka", "n[eé]pal", "kazakhstan", "ouzb[eé]kistan", "uzbekistan",
            "huawei", "alibaba", "tencent", "baidu", "bytedance", "deepseek", "xiaomi", "samsung", "tsmc",
            "softbank", "sony", "nintendo", "toyota", "moonshot ai", "zhipu", "minimax", "byd", "infosys",
            "wipro", "reliance jio", "flipkart", "paytm", "sk hynix", "naver", "kakao", "rakuten", "foxconn",
            "mediatek", "lenovo",
        ],
        ["LG", "Tata", "Grab", "Qwen", "Kimi"],
    ),
    "europe": (
        [
            "europe", "european", "europ[eé]en(?:ne)?s?", "bruxelles", "brussels", "union europ[eé]enne",
            "european union", "commission europ[eé]enne", "european commission", "france", "fran[cç]aise?s?",
            "paris", "germany", "allemagne", "allemande?s?", "berlin", "munich", "united kingdom", "royaume-uni",
            "britain", "british", "britanniques?", "england", "angleterre", "london", "londres", "scotland",
            "[eé]cosse", "ireland", "irlande", "irish", "dublin", "spain", "espagne", "espagnole?s?", "madrid",
            "barcelone?a?", "italy", "italie", "italian", "italien(?:ne)?s?", "milan", "netherlands", "pays-bas",
            "dutch", "n[eé]erlandaise?s?", "amsterdam", "belgium", "belgique", "switzerland", "suisse", "swiss",
            "zurich", "gen[eè]ve", "geneva", "sweden", "su[eè]de", "swedish", "stockholm", "norway", "norv[eè]ge",
            "denmark", "danemark", "finland", "finlande", "helsinki", "poland", "pologne", "warsaw", "varsovie",
            "portugal", "lisbon", "lisbonne", "austria", "autriche", "ukraine", "ukrainian", "ukrainien(?:ne)?s?",
            "kyiv", "kiev", "russia", "russie", "russian", "russes?", "moscow", "moscou", "estoni[ae]", "greece",
            "gr[eè]ce", "roumanie", "romania", "hungary", "hongrie", "czech", "tch[eè]que", "mistral", "asml",
            "spotify", "deepl", "helsing", "aleph alpha", "revolut", "klarna", "nokia", "ericsson",
            "arm holdings", "ovhcloud", "stmicroelectronics", "infineon", "siemens", "adyen", "cnil", "arcep",
            "ofcom", "ai act", "rgpd", "gdpr",
        ],
        ["EU", "UE", "UK", "DMA", "DSA", "SAP", "Polish", "German", "French"],
    ),
    "amerique_latine": (
        [
            "am[eé]rique latine", "latin america", "latin american", "latino-am[eé]ricaine?s?", "latinoam[eé]rica",
            "am[eé]rica latina", "latam", "brazil", "br[eé]sil", "brasil", "brazilian", "br[eé]silien(?:ne)?s?",
            "brasileir[oa]s?", "s[aã]o paulo", "rio de janeiro", "mexico", "mexique", "m[eé]xico", "mexican",
            "mexicaine?s?", "mexicano", "argentin[ae]?s?", "buenos aires", "chile", "chilean", "chilien(?:ne)?s?",
            "colombi[ae]", "colombian", "colombien(?:ne)?s?", "bogot[aá]", "medell[ií]n", "peru", "p[eé]rou",
            "per[uú]", "peruvian", "p[eé]ruvien(?:ne)?s?", "uruguay", "montevideo", "ecuador", "[eé]quateur",
            "venezuela", "costa rica", "guatemala", "paraguay", "bolivi[ae]", "mercado ?libre", "nubank", "rappi",
            "kavak", "globant", "embraer",
        ],
        ["Chili", "Pix", "Lima"],
    ),
    "oceanie": (
        [
            "oceania", "oc[eé]anie", "australia", "australie", "australian", "australien(?:ne)?s?", "sydney",
            "melbourne", "brisbane", "canberra", "adelaide", "new zealand", "nouvelle-z[eé]lande", "auckland",
            "wellington", "christchurch", "fiji", "fidji", "papua new guinea", "papouasie", "nouvelle-cal[eé]donie",
            "new caledonia", "tahiti", "polyn[eé]sie", "atlassian", "canva", "afterpay", "telstra", "optus",
            "esafety",
        ],
        ["NZ", "ACCC"],
    ),
    "amerique_nord": (
        [
            "united states", "[eé]tats-unis", "(?<!latino-)am[eé]ricaine?s?", "(?<!latin )american",
            "washington", "white house", "maison[- ]blanche", "silicon valley", "california", "californie",
            "san francisco", "new york", "seattle", "texas", "canada", "canadian", "canadien(?:ne)?s?", "toronto",
            "montr[eé]al", "vancouver", "ottawa", "qu[eé]bec", "pentagon", "pentagone", "trump", "congr[eè]s am[eé]ricain",
        ],
        ["US", "U\\.S\\.", "USA", "FTC", "FCC", "DOJ", "Congress"],
    ),
}

_B = r"(?<![\w-])(?:{})(?![\w-])"
_PATTERNS: list[tuple[str, re.Pattern, re.Pattern]] = [
    (key, re.compile(_B.format("|".join(ci)), re.IGNORECASE), re.compile(_B.format("|".join(cs))))
    for key, (ci, cs) in _GAZETTEER.items()
]


def detect_regions(text: str) -> list[str]:
    """Régions évoquées dans le texte, dans l'ordre de leur première mention."""
    first: dict[str, int] = {}
    for key, ci, cs in _PATTERNS:
        positions = [m.start() for m in ci.finditer(text)] + [m.start() for m in cs.finditer(text)]
        if positions:
            first[key] = min(positions)
    return sorted(first, key=first.get)


def resolve_region(source_region: str, title: str, summary: str = "") -> str:
    """Région d'un article.

    - Média international : région déduite du titre (puis de l'extrait), sinon « monde ».
    - Média régional : on garde sa région, sauf si le titre parle clairement d'une autre région
      (ex. TechCrunch qui couvre une fintech nigériane -> Afrique).
    """
    in_title = detect_regions(title)
    if source_region == GLOBAL:
        found = in_title or detect_regions(summary)
        return found[0] if found else GLOBAL
    if not in_title or source_region in in_title:
        return source_region
    return in_title[0]
