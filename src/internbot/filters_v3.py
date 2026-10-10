"""
Filtre v3 pour le bot de stages.

Chaque offre tombe dans un seau :
  - NOTIFY : stage SWE / data / IA / FDE dans une zone voulue -> alerte immédiate
  - REVIEW : ambigu -> résumé quotidien « à vérifier » (jamais perdu en silence)
  - DROP   : hardware pur, non-tech, PhD uniquement, hors zone
Et une priorité : les offres IA sont marquées ⭐.

Principes :
  1. Un signal software/data/IA explicite gagne toujours contre le hardware.
  2. Hardware + IA/ML sans software explicite -> REVIEW (pas jeté).
  3. PhD exclu SEULEMENT si l'offre est réservée aux PhD (« BS/MS/PhD » passe).
  4. Toute correspondance se fait par mot entier : « cisco » ne matche jamais
     « San Francisco », « intern » ne matche pas « internal ».
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

NOTIFY, REVIEW, DROP = "notify", "review", "drop"


# ------------------------------------------------------------- outils ----

def norm(s: str) -> str:
    """minuscules, sans accents, ponctuation -> espaces, entouré d'espaces."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " " + re.sub(r"[^a-z0-9+#]+", " ", s.lower()).strip() + " "


def has(text: str, terms: list[str]) -> list[str]:
    """Termes présents en mot/expression entière dans un texte déjà normalisé."""
    return [t for t in terms if f" {norm(t).strip()} " in text]


# -------------------------------------------------------------- titre ----

INTERN = ["intern", "interns", "internship", "internships", "stage", "stagiaire",
          "co op", "coop", "working student", "werkstudent", "praktikum",
          "summer analyst", "placement", "industrial placement", "apprenti",
          "alternance", "alternant"]

# IA : priorité n°1 (alerte + ⭐), gagne contre le hardware si software présent
AI = ["ai", "artificial intelligence", "machine learning", "ml", "deep learning",
      "genai", "generative", "llm", "llms", "nlp", "computer vision",
      "reinforcement learning", "applied scientist", "applied ai", "ai engineer",
      "ml engineer", "mlops", "agent", "agents", "agentic", "inference",
      "foundation model", "foundation models", "multimodal", "perception"]

# Software explicite : garde l'offre même si un mot hardware apparaît
SOFTWARE = ["software", "swe", "developer", "developpeur", "development engineer",
            "programmer", "programming", "coding", "c++", "python", "java",
            "rust", "golang", "go", "typescript", "backend", "back end",
            "frontend", "front end", "fullstack", "full stack", "web", "mobile",
            "android", "ios", "devops", "sre", "site reliability", "compiler",
            "compilers", "kernel", "driver", "drivers", "sdk", "api",
            "test automation", "sdet", "library", "libraries", "frameworks",
            "tooling", "systems software", "system software", "cloud engineer",
            "platform engineer", "infrastructure engineer", "security engineer",
            "distributed systems", "product engineer", "application engineer"]

# Forward Deployed Engineer & co
FDE = ["forward deployed", "fde", "deployment strategist", "solutions engineer",
       "solution engineer", "customer engineer"]

# Data : réactivé
DATA = ["data", "data science", "data scientist", "data engineer",
        "data engineering", "data analyst", "analytics", "analytics engineer",
        "business intelligence", "bi", "operations research", "statistics",
        "quantitative analyst"]

# Tech générique : utile seulement s'il n'y a ni hardware ni non-tech
GENERIC_TECH = ["engineer", "engineering", "systems engineer", "infrastructure",
                "platform", "cloud", "security", "cybersecurity", "research engineer",
                "algorithms", "robotics software", "technology", "it"]

# Hardware et tout ce qui va avec (perf hardware, validation, physique...)
HARDWARE = ["hardware", "asic", "fpga", "rtl", "verilog", "vhdl", "physical design",
            "dft", "design verification", "verification engineer", "silicon",
            "soc", "chip", "module engineering", "module engineer",
            "module development", "process integration", "process engineer",
            "yield", "etch", "epi", "transistor", "lithography", "packaging",
            "thermal", "mechanical", "facilities", "equipment", "analog", "rf",
            "pcb", "circuit", "circuits", "power delivery", "power", "layout",
            "industrialization", "field quality", "quality engineer",
            "manufacturing", "electrical", "electronics", "teg",
            "hardware validation", "platform validation", "validation engineer",
            "performance engineer", "performance engineering",
            "performance modeling", "performance modelling", "post silicon",
            "pre silicon", "materials", "design for test", "lab validation",
            "architecture validation", "ams",
            "optical", "photonics", "mems", "metrology", "test engineer",
            "reliability engineer", "supply chain", "assembly", "mechatronics"]

NON_TECH = ["ux research", "user research", "ux", "designer", "product design",
            "business systems", "audit", "finance", "accounting", "marketing",
            "sales", "recruiting", "recruiter", "talent", "human resources", "hr",
            "legal", "communications", "operations", "procurement",
            "customer success", "business development", "business analyst",
            "solution architect", "solutions architect", "consultant",
            "program manager", "project manager", "product manager", "strategy",
            "program management", "project management", "product management",
            "policy", "content", "community", "partnerships", "investment"]

# Quant research pur (garde les « quant ... engineer/developer » en REVIEW)
QUANT = ["quantitative research", "quant research", "quantitative trader",
         "trader", "trading", "algorithm development"]

PHD = ["phd", "ph d", "postdoc", "doctoral", "doctorate"]
NON_PHD_LEVEL = ["bs", "ba", "ms", "msc", "bsc", "meng", "bachelor", "bachelors",
                 "master", "masters", "undergrad", "undergraduate", "graduate"]

# -------------------------------------------------------------- lieux ----

LOCATIONS = {
    "us": ["united states", "usa", "us", "u s", "new york", "nyc", "ny",
           "san francisco", "sf", "bay area", "mountain view", "santa clara",
           "palo alto", "menlo park", "sunnyvale", "cupertino", "redwood city",
           "san mateo", "san jose ca", "seattle", "bellevue", "redmond",
           "kirkland", "austin", "dallas", "houston", "chicago", "boston",
           "cambridge ma", "los angeles", "santa monica", "irvine", "san diego",
           "denver", "boulder", "pittsburgh", "atlanta", "miami", "raleigh",
           "durham", "hillsboro", "portland", "folsom", "phoenix", "cary",
           "salt lake city", "washington dc", "arlington", "new jersey",
           "california", "ca", "oregon", "texas", "tx", "illinois",
           "massachusetts", "washington", "wa", "arizona", "north carolina",
           "colorado", "pennsylvania", "virginia", "georgia", "florida", "utah"],
    "canada": ["canada", "toronto", "montreal", "vancouver", "waterloo",
               "ottawa", "longueuil", "quebec", "calgary"],
    "uk": ["united kingdom", "uk", "england", "scotland", "london", "bristol",
           "cambridge", "oxford", "manchester", "edinburgh", "belfast"],
    "europe": ["europe", "emea", "france", "paris", "courbevoie", "la defense",
               "le plessis robinson", "bourges",
               "lyon", "grenoble", "sophia antipolis", "toulouse", "nice",
               "rennes", "nantes", "lille", "bordeaux", "marseille", "germany",
               "berlin", "munich", "wuerselen", "hamburg", "frankfurt",
               "stuttgart", "switzerland", "zurich", "geneva", "lausanne",
               "netherlands", "amsterdam", "eindhoven", "veldhoven", "delft",
               "spain", "madrid", "barcelona", "italy", "milan", "milano", "rome",
               "poland", "warsaw", "gdansk", "krakow", "wroclaw", "ireland",
               "dublin", "leixlip", "cork", "denmark", "aarhus", "copenhagen",
               "sweden", "stockholm", "norway", "oslo", "finland", "helsinki",
               "belgium", "brussels", "portugal", "lisbon", "porto", "austria",
               "vienna", "czech", "prague", "serbia", "belgrade", "novi sad",
               "romania", "bucharest", "greece", "athens", "estonia", "tallinn",
               "lithuania", "vilnius", "luxembourg", "hungary", "budapest"],
    "asia": ["singapore", "hong kong"],
    "australia": ["australia", "sydney", "melbourne", "brisbane", "perth"],
    # Disponibles mais désactivées par défaut
    "israel": ["israel", "tel aviv", "haifa", "herzliya", "jerusalem"],
    "japan": ["japan", "tokyo"],
    "uae": ["dubai", "abu dhabi", "united arab emirates", "uae"],
}

# France : seule l'Île-de-France est gardée (règle de Matisse). Une offre dont le lieu cite une
# ville française hors Île-de-France et aucune ville d'Île-de-France est écartée ; « France »
# seul ou un lieu mixte (« Paris ; Toulouse ») est gardé.
FRANCE_HORS_IDF = [
    "lyon", "grenoble", "sophia antipolis", "valbonne", "toulouse", "blagnac", "labege", "nice",
    "rennes", "cesson sevigne", "bretagne", "nantes", "saint herblain", "lille", "bordeaux",
    "marseille", "aix en provence", "provence alpes cote d azur", "montpellier", "strasbourg",
    "bourges", "crolles", "meylan", "montbonnot", "rousset", "villeneuve loubet", "nancy",
    "dijon", "toulon", "cannes", "antibes", "clermont ferrand",
    "rouen", "caen", "le havre", "angers", "metz", "reims", "perpignan",
    # Sites vus dans les offres (Orange, Thales, Airbus, MBDA…) et régions administratives.
    "lannion", "brest", "colomiers", "saint nazaire", "merignac", "le haillan", "pessac",
    "saint medard en jalles", "villeneuve d ascq", "la ciotat", "marignane", "biot",
    "villeurbanne", "orleans", "limoges", "poitiers", "brive", "tarbes", "bayonne", "nimes",
    "avignon", "saint etienne", "annecy", "chambery", "besancon", "mulhouse", "amiens",
    "le mans", "vannes", "lorient", "quimper", "la rochelle", "niort", "cherbourg", "cholet",
    "occitanie", "nouvelle aquitaine", "auvergne rhone alpes", "hauts de france", "grand est",
    "normandie", "pays de la loire", "centre val de loire", "bourgogne franche comte",
]
ILE_DE_FRANCE = [
    "ile de france", "idf", "grand paris", "region parisienne", "paris",
    # 92 Hauts-de-Seine
    "courbevoie", "la defense", "puteaux", "nanterre", "rueil malmaison", "le plessis robinson",
    "boulogne billancourt", "issy les moulineaux", "levallois perret", "clichy", "montrouge",
    "malakoff", "gennevilliers", "suresnes", "meudon", "bagneux", "saint cloud", "sevres",
    "chatillon", "clamart", "antony", "asnieres sur seine", "colombes", "bois colombes",
    "la garenne colombes", "neuilly sur seine", "vanves", "fontenay aux roses",
    "chatenay malabry", "sceaux", "bourg la reine", "garches", "villeneuve la garenne",
    "chaville", "ville d avray", "vaucresson",
    # 78 Yvelines
    "versailles", "velizy villacoublay", "velizy", "guyancourt", "montigny le bretonneux",
    "saint quentin en yvelines", "saint germain en laye", "poissy", "les mureaux", "rambouillet",
    "trappes", "elancourt", "le chesnay", "maurepas", "buc", "voisins le bretonneux",
    "magny les hameaux", "saint cyr l ecole", "conflans sainte honorine", "mantes la jolie",
    "houilles", "sartrouville", "chatou", "le vesinet", "la verriere", "bois d arcy",
    # 91 Essonne
    "massy", "palaiseau", "saclay", "gif sur yvette", "orsay", "evry", "evry courcouronnes",
    "les ulis", "nozay", "marcoussis", "villebon sur yvette", "bures sur yvette", "longjumeau",
    "corbeil essonnes", "athis mons", "savigny sur orge", "bretigny sur orge", "arpajon",
    "ris orangis", "courtaboeuf", "wissous", "chilly mazarin", "verrieres le buisson",
    # 93 Seine-Saint-Denis
    "saint denis", "saint ouen", "montreuil", "bobigny", "noisy le grand", "aubervilliers",
    "pantin", "bagnolet", "bondy", "le bourget", "rosny sous bois", "la courneuve",
    "epinay sur seine", "drancy", "aulnay sous bois", "villepinte", "sevran", "noisy le sec",
    "les lilas", "romainville", "stains", "tremblay en france", "le blanc mesnil",
    # 94 Val-de-Marne
    "creteil", "ivry sur seine", "vitry sur seine", "vincennes", "saint mande",
    "charenton le pont", "maisons alfort", "alfortville", "fontenay sous bois",
    "nogent sur marne", "joinville le pont", "villejuif", "arcueil", "cachan", "gentilly",
    "le kremlin bicetre", "choisy le roi", "thiais", "rungis", "orly", "fresnes",
    "l hay les roses", "champigny sur marne", "saint maur des fosses", "boissy saint leger",
    "villeneuve saint georges", "bry sur marne", "chevilly larue", "valenton",
    # 95 Val-d'Oise
    "cergy", "cergy pontoise", "pontoise", "roissy en france", "roissy", "argenteuil",
    "sarcelles", "enghien les bains", "montmorency", "eragny", "osny", "gonesse",
    "goussainville", "villiers le bel", "ermont", "franconville", "saint ouen l aumone",
    "taverny", "deuil la barre", "bezons",
    # 77 Seine-et-Marne
    "marne la vallee", "fontainebleau", "melun", "meaux", "torcy", "champs sur marne",
    "noisiel", "lognes", "serris", "chessy", "bussy saint georges", "lieusaint",
    "savigny le temple", "pontault combault", "provins", "chelles", "roissy en brie",
    "ozoir la ferriere", "dammarie les lys", "moissy cramayel", "combs la ville",
]
# « (92) », « 78 », « (75017) » : code de département ou code postal d'Île-de-France.
_IDF_CODE = re.compile(r"\((?:75|77|78|91|92|93|94|95)\d{0,3}\)")

UNKNOWN_LOC = ["multiple locations", "various", "blank", "global",
               "worldwide", "anywhere", "flexible", "tbd"]
REMOTE = ["remote", "virtual", "telework", "teletravail", "hybrid"]


@dataclass
class FilterConfig:
    enabled_regions: set[str] = field(default_factory=lambda: {
        "us", "canada", "uk", "europe", "asia", "australia"})
    include_data: bool = True
    include_fde: bool = True
    include_quant_research: bool = False   # quant research pur (trader, QR)


@dataclass
class Verdict:
    status: str           # notify / review / drop
    reason: str
    priority: bool = False  # True = offre IA (⭐)


# ---------------------------------------------------------- classement ----

def is_phd_only(t: str) -> bool:
    return bool(has(t, PHD)) and not has(t, NON_PHD_LEVEL)


def classify_title(title: str, cfg: FilterConfig) -> Verdict:
    t = norm(title)
    if not has(t, INTERN):
        return Verdict(DROP, "pas un stage")
    if is_phd_only(t):
        return Verdict(DROP, "PhD uniquement")

    ai, sw, fde = has(t, AI), has(t, SOFTWARE), has(t, FDE)
    data, hw, nt = has(t, DATA), has(t, HARDWARE), has(t, NON_TECH)
    quant, generic = has(t, QUANT), has(t, GENERIC_TECH)
    prio = bool(ai)

    # 1. Software / FDE explicite : on garde, même avec du hardware autour
    if sw:
        return Verdict(NOTIFY, f"software ({sw[0]})", prio)
    if fde and cfg.include_fde:
        return Verdict(NOTIFY, f"FDE ({fde[0]})", prio)

    # 2. Hardware sans software explicite
    if hw:
        if ai:  # ex: « Hardware ML Research » -> à vérifier, pas jeté
            return Verdict(REVIEW, f"hardware + IA ({hw[0]}, {ai[0]})", prio)
        return Verdict(DROP, f"hardware ({hw[0]})")

    # 3. IA : priorité
    if ai:
        if nt:  # ex: « AI Solution Architect », « AI Audit »
            return Verdict(REVIEW, f"IA + non-tech ({nt[0]})", prio)
        return Verdict(NOTIFY, f"IA ({ai[0]})", prio)

    # 4. Data
    if data and cfg.include_data:
        if nt and not has(t, ["data", "analytics"]):
            return Verdict(DROP, f"non-tech ({nt[0]})")
        return Verdict(NOTIFY, f"data ({data[0]})")

    # 5. Quant research pur
    if quant:
        if cfg.include_quant_research:
            return Verdict(NOTIFY, "quant")
        if has(t, ["engineer", "developer"]):
            return Verdict(REVIEW, "quant + engineer")
        return Verdict(DROP, "quant research (désactivé)")

    # 6. Non-tech
    if nt:
        return Verdict(DROP, f"non-tech ({nt[0]})")

    # 7. Tech générique (engineer, platform, systems...) : à vérifier si seul
    if has(t, ["engineer", "engineering"]):
        return Verdict(NOTIFY, "engineer (générique)")
    if generic:
        return Verdict(REVIEW, f"signal faible ({generic[0]})")
    return Verdict(REVIEW, "titre ambigu")


def classify_location(location: str, cfg: FilterConfig) -> Verdict:
    loc = norm(location)
    if not loc.strip():
        return Verdict(REVIEW, "lieu vide")
    idf = bool(has(loc, ILE_DE_FRANCE) or _IDF_CODE.search(location))
    if has(loc, FRANCE_HORS_IDF) and not idf:
        return Verdict(DROP, "France hors Île-de-France")
    if idf and "europe" in cfg.enabled_regions:
        return Verdict(NOTIFY, "zone europe (Île-de-France)")
    zones = [r for r in sorted(cfg.enabled_regions) if has(loc, LOCATIONS[r])]
    if zones:
        return Verdict(NOTIFY, f"zone {zones[0]}")
    if has(loc, REMOTE):
        return Verdict(NOTIFY, "remote")
    if has(loc, UNKNOWN_LOC):
        return Verdict(REVIEW, "lieu non précisé")
    return Verdict(DROP, "hors zone")


def classify(title: str, location: str, cfg: FilterConfig | None = None) -> Verdict:
    cfg = cfg or FilterConfig()
    t = classify_title(title, cfg)
    if t.status == DROP:
        return t
    loc = classify_location(location, cfg)
    if loc.status == DROP:
        return Verdict(DROP, loc.reason)
    status = NOTIFY if (t.status == NOTIFY and loc.status == NOTIFY) else REVIEW
    return Verdict(status, f"{t.reason} / {loc.reason}", t.priority)


# ------------------------------------------- recherche pour /offres ----

def matches_query(query: str, company: str, title: str, location: str,
                  known_companies: set[str]) -> bool:
    """
    Recherche de la commande /offres.
    - Si la requête est un nom d'entreprise connu -> on ne regarde QUE le champ
      entreprise (« /offres cisco » ne renvoie plus les offres à San Francisco).
    - Sinon -> mot entier dans titre, lieu ou entreprise.
    """
    q = norm(query).strip()
    if not q:
        return True
    if q in {norm(c).strip() for c in known_companies}:
        return norm(company).strip() == q
    return any(f" {q} " in norm(f) for f in (company, title, location))
