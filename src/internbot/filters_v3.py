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
            "performance modeling", "post silicon", "pre silicon", "materials",
            "optical", "photonics", "mems", "metrology", "test engineer",
            "reliability engineer", "supply chain", "assembly", "mechatronics"]

NON_TECH = ["ux research", "user research", "ux", "designer", "product design",
            "business systems", "audit", "finance", "accounting", "marketing",
            "sales", "recruiting", "recruiter", "talent", "human resources", "hr",
            "legal", "communications", "operations", "procurement",
            "customer success", "business development", "business analyst",
            "solution architect", "solutions architect", "consultant",
            "program manager", "project manager", "product manager", "strategy",
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
