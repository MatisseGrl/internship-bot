"""Repérage des exclusions explicites dans le texte d'une offre, sans IA.

Chaque motif renvoie la phrase qui le déclenche, pour vérification humaine. Les règles sont
volontairement étroites : une mention ambiguë ne déclenche rien. Profil visé : étudiant
ingénieur européen, diplôme en juin 2028, stage d'avril-mai à août 2027, pas de poste de
recherche (décision de Matisse), éligible au J-1 mais pas citoyen américain.
"""

from __future__ import annotations

import re

_FLAGS = re.IGNORECASE

REGLES: dict[str, list[re.Pattern[str]]] = {
    "phd": [
        re.compile(p, _FLAGS)
        for p in (
            r"\b(currently )?(enrolled|pursuing|candidates?) (in|for) (a |an )?Ph\.?\s?D\b",
            r"\bdesigned (specifically )?for (students )?(pursuing|enrolled in) "
            r"(a |their )?Ph\.?\s?D",
            r"\bPh\.?\s?D\.? (students?|candidates?) only\b",
            r"\bmust be (a )?Ph\.?\s?D\.? (student|candidate)",
            r"\b(currently )?enrolled in a doctoral program",
        )
    ],
    "nationalite": [
        re.compile(p, _FLAGS)
        for p in (
            r"\bmust be (a )?U\.?\s?S\.? (citizen|person|national)",
            r"\bU\.?\s?S\.? citizenship (is )?(required|mandatory)",
            r"\bonly U\.?\s?S\.? citizens\b",
            r"\brequires? (that the candidate .{0,40})?(be )?(a )?U\.?\s?S\.? (citizen|person)\b",
            r"\b(active|obtain|eligib\w+ for|ability to obtain)( and maintain)? (a |an )?"
            r"(U\.?\s?S\.? )?(government )?(security|secret|top secret) clearance",
            r"\bsecurity clearance (is )?required",
            r"\bcitoyen(neté)? américaine? (est )?(requise|exigée|obligatoire)",
        )
    ],
    "fin_etudes": [
        re.compile(p, _FLAGS)
        for p in (
            r"\bstage de fin d['’]études\b",
            r"\b(currently )?in (your|their|the) (final|last) year( of)?",
            r"\blast year of (a |your )?(master|bachelor|engineering)",
            r"\bfinal[- ]year (students?|undergraduates?|master)",
            r"\bdernière année\b",
        )
    ],
}
# Une phrase qui ouvre une alternative ou exprime une simple préférence n'exclut pas.
SAUF: dict[str, re.Pattern[str]] = {
    "phd": re.compile(r"\b(master|M\.?S\.?|graduate students|MS/PhD)\b", _FLAGS),
    "nationalite": re.compile(
        r"\b(eligibility|willingness|may require|some (of these )?positions|for USG|preferred)\b",
        _FLAGS,
    ),
    "fin_etudes": re.compile(
        r"\b(penultimate|preferred|not required|or in the final|or final|or last|ideally|"
        r"plus|a plus|césure|gap year|or (recent )?graduates?|pas prioritairement)\b",
        _FLAGS,
    ),
}
_DIPLOME_OUVERT = re.compile(
    r"\b(or later|or after|and later|no earlier|not before|onwards?|at the earliest|or beyond|"
    r"not graduate (prior|before)|recently graduated)\b",
    _FLAGS,
)
# Diplôme exigé au plus tard en 2027 : exclut Matisse (juin 2028), sauf si 2028 est cité.
_DIPLOME = re.compile(
    r"[^.\n]*\b(graduat\w+|expected graduation|grad date)\b[^.\n]{0,80}\b(2025|2026|2027)\b[^.\n]*",
    _FLAGS,
)
# Décision de Matisse : aucun poste de recherche ; Research Engineer reste dans la cible.
_RECHERCHE = re.compile(
    r"\b(research (intern|internship|scientist)|researcher|student researcher|thèse|phd intern)\b",
    _FLAGS,
)
_PAS_RECHERCHE = re.compile(r"\bresearch engineer", _FLAGS)


def _phrase(texte: str, debut: int, fin: int) -> str:
    gauche = max(texte.rfind(".", 0, debut), texte.rfind("\n", 0, debut)) + 1
    droite = min(
        (i for i in (texte.find(".", fin), texte.find("\n", fin)) if i != -1), default=len(texte)
    )
    return re.sub(r"\s+", " ", texte[gauche : droite + 1]).strip()[:300]


def verifier(titre: str, texte: str, actif: bool | None = None) -> list[tuple[str, str]]:
    """Liste de (motif, preuve). Vide si aucune exclusion explicite n'est trouvée."""
    motifs: list[tuple[str, str]] = []
    if actif is False:
        motifs.append(("fermee", "Annonce marquée inactive par la source"))
    if _RECHERCHE.search(titre or "") and not _PAS_RECHERCHE.search(titre or ""):
        motifs.append(("recherche", titre))
    texte = texte or ""
    for motif, regles in REGLES.items():
        preuve = next(
            (
                phrase
                for regle in regles
                for trouve in regle.finditer(texte)
                if not SAUF[motif].search(phrase := _phrase(texte, trouve.start(), trouve.end()))
            ),
            None,
        )
        if preuve:
            motifs.append((motif, preuve))
    for trouve in _DIPLOME.finditer(texte):
        phrase = trouve.group(0)
        if not re.search(r"20(2[89]|3\d)", phrase) and not _DIPLOME_OUVERT.search(phrase):
            motifs.append(("diplome_trop_tot", re.sub(r"\s+", " ", phrase).strip()[:300]))
            break
    return motifs
