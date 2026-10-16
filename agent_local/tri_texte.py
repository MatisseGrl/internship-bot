"""Classement des offres sur leur texte complet, sans IA générative ni API.

Modèle `texte-ensemble-v1` : somme à poids égaux des log-odds de trois régressions
logistiques, sur le titre (modèle `titre-ensemble-v3`), sur les mots du texte (TF-IDF
mots et paires de mots) et sur des embeddings locaux du texte (moyenne de morceaux de
1 200 caractères, BAAI/bge-base-en-v1.5). Deux cibles apprises sur les offres notées par
la grille : `fit` (Fit rôle 3-5 contre 1) et `retenue` (score de grille >= 65).

`classer` applique le modèle figé et les règles d'éligibilité aux offres du bot sans note
et aux annonces SWElist, puis écrit la table `classement` et un CSV trié. Aucune offre
n'est supprimée et rien n'est envoyé. Mesures : docs/TRI_ML_RAPPORT.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from eligibilite import verifier
from import_swelist import normaliser
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold
from tri_ml import (
    Embedder,
    TitleModel,
    cached,
    fastembed_embedder,
    load_examples,
    metrics,
    split_company,
    thresholds,
)

VERSION = "texte-ensemble-v1"
TEXTE_MINIMUM = 300
CHUNK = 1200
MAX_CHUNKS = 6
C_WORDS = 4.0
C_BODY_EMBEDDING = 16.0
_HEADER = re.compile(r"^(Intitulé|Lieu|Type de contrat|Publiée le|Valable jusqu'au)\s*:.*$", re.M)


def nettoyer(texte: str | None) -> str:
    """Retire l'en-tête ajouté par l'export du bot, pour ressembler au texte SWElist."""
    return _HEADER.sub("", texte or "").strip()


def morceaux(texte: str) -> list[str]:
    parts = [texte[i : i + CHUNK] for i in range(0, len(texte), CHUNK)]
    return parts[:MAX_CHUNKS] or [""]


class BodyEmbedder:
    """Embedding d'un texte = moyenne de ses morceaux ; cache SQLite optionnel par morceau."""

    def __init__(self, embed: Embedder, cache: Path | None = None) -> None:
        self.embed = embed
        self.db = sqlite3.connect(cache) if cache else None
        if self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS emb(h TEXT PRIMARY KEY, v BLOB)")
        self.memory: dict[str, np.ndarray] = {}

    def _vectors(self, pieces: list[str]) -> dict[str, np.ndarray]:
        keys = {p: hashlib.sha1(p.encode()).hexdigest() for p in pieces}
        missing = [p for p, h in keys.items() if h not in self.memory]
        if self.db and missing:
            for i in range(0, len(missing), 500):
                part = [keys[p] for p in missing[i : i + 500]]
                rows = self.db.execute(
                    f"SELECT h,v FROM emb WHERE h IN ({','.join('?' * len(part))})", part
                )
                for h, v in rows:
                    self.memory[h] = np.frombuffer(v, dtype=np.float32)
            missing = [p for p in missing if keys[p] not in self.memory]
        for i in range(0, len(missing), 256):
            batch = missing[i : i + 256]
            for piece, vec in zip(batch, self.embed(batch), strict=True):
                self.memory[keys[piece]] = np.asarray(vec, dtype=np.float32)
                if self.db:
                    self.db.execute(
                        "INSERT OR REPLACE INTO emb VALUES(?,?)",
                        (keys[piece], self.memory[keys[piece]].tobytes()),
                    )
            if self.db:
                self.db.commit()
        return {p: self.memory[h] for p, h in keys.items()}

    def close(self) -> None:
        if self.db:
            self.db.close()

    def __call__(self, texts: Sequence[str]) -> np.ndarray:
        split = [morceaux(t) for t in texts]
        vectors = self._vectors(sorted({p for parts in split for p in parts}))
        return np.vstack([np.mean([vectors[p] for p in parts], axis=0) for parts in split])


class TextModel:
    def __init__(self) -> None:
        self.title = TitleModel()
        self.vocabulary: dict[str, int] = {}
        self.idf = np.zeros(0)
        self.coef_words = np.zeros(0)
        self.bias_words = 0.0
        self.coef_body = np.zeros(0)
        self.bias_body = 0.0

    def fit(self, titles, bodies, labels, embed_title: Embedder, embed_body: Embedder):
        self.title.fit(titles, labels, embed_title)
        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), sublinear_tf=True, min_df=2, max_df=0.6, stop_words="english"
        ).fit(bodies)
        self.vocabulary = {k: int(v) for k, v in vectorizer.vocabulary_.items()}
        self.idf = vectorizer.idf_
        words = LogisticRegression(C=C_WORDS, class_weight="balanced", max_iter=5000)
        words.fit(self._words(bodies), labels)
        self.coef_words, self.bias_words = words.coef_[0], float(words.intercept_[0])
        body = LogisticRegression(C=C_BODY_EMBEDDING, class_weight="balanced", max_iter=5000)
        body.fit(embed_body(bodies), labels)
        self.coef_body, self.bias_body = body.coef_[0], float(body.intercept_[0])
        return self

    def _words(self, bodies):
        counts = (
            CountVectorizer(ngram_range=(1, 2), stop_words="english", vocabulary=self.vocabulary)
            .transform(bodies)
            .astype(float)
        )
        counts.data = 1 + np.log(counts.data)
        weighted = counts.multiply(self.idf).tocsr()
        norms = np.sqrt(np.asarray(weighted.multiply(weighted).sum(axis=1))).ravel()
        norms[norms == 0] = 1.0
        return weighted.multiply(1 / norms[:, None]).tocsr()

    def logits(self, titles, bodies, embed_title: Embedder, embed_body: Embedder) -> np.ndarray:
        p = np.clip(self.title.score(titles, embed_title), 1e-9, 1 - 1e-9)
        z_title = np.log(p / (1 - p))
        z_words = self._words(bodies) @ self.coef_words + self.bias_words
        z_body = embed_body(bodies) @ self.coef_body + self.bias_body
        return z_title + z_words + z_body

    def score(self, titles, bodies, embed_title: Embedder, embed_body: Embedder) -> np.ndarray:
        return 1 / (1 + np.exp(-self.logits(titles, bodies, embed_title, embed_body)))

    def to_artifact(self) -> dict:
        return {
            "titre": self.title.to_artifact(),
            "vocabulaire": self.vocabulary,
            "idf": self.idf.tolist(),
            "coef_mots": self.coef_words.tolist(),
            "biais_mots": self.bias_words,
            "coef_embedding_texte": self.coef_body.tolist(),
            "biais_embedding_texte": self.bias_body,
        }

    @classmethod
    def from_artifact(cls, artifact: dict) -> TextModel:
        model = cls()
        model.title = TitleModel.from_artifact(artifact["titre"])
        model.vocabulary = artifact["vocabulaire"]
        model.idf = np.array(artifact["idf"])
        model.coef_words = np.array(artifact["coef_mots"])
        model.bias_words = artifact["biais_mots"]
        model.coef_body = np.array(artifact["coef_embedding_texte"])
        model.bias_body = artifact["biais_embedding_texte"]
        return model


def _examples(db: sqlite3.Connection, target: str) -> list[tuple[str, str, str, str, int]]:
    """(clé, entreprise, titre, texte, étiquette) des offres notées ayant un texte."""
    texts = {k: nettoyer(t) for k, t in db.execute("SELECT cle,texte FROM offres")}
    if target == "fit":
        rows = [
            (x.key, x.company, x.title, texts.get(x.key, ""), x.label) for x in load_examples(db)[0]
        ]
    else:
        rows = []
        for key, company, title, raw in db.execute(
            "SELECT cle,entreprise,titre,note_json FROM offres WHERE note_json IS NOT NULL"
        ):
            note = json.loads(raw)
            if isinstance(note.get("notes"), list) and title and note.get("score") is not None:
                label = int(note["score"] >= 65)
                rows.append((key, normaliser(company), title, texts.get(key, ""), label))
    return sorted(r for r in rows if len(r[3]) >= TEXTE_MINIMUM)


def _oof(rows, embed_title, embed_body, seed=11) -> np.ndarray:
    labels = np.array([r[4] for r in rows])
    scores = np.zeros(len(rows))
    folds = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    for train, held in folds.split(rows, labels, [r[1] for r in rows]):
        model = TextModel().fit(
            [rows[i][2] for i in train],
            [rows[i][3] for i in train],
            labels[train],
            embed_title,
            embed_body,
        )
        scores[held] = model.score(
            [rows[i][2] for i in held], [rows[i][3] for i in held], embed_title, embed_body
        )
    return scores


def train(
    db_path: Path,
    model_path: Path,
    report_path: Path,
    embed: Embedder = fastembed_embedder,
    cache: Path | None = None,
) -> dict:
    embed_title = cached(embed)
    embed_body = BodyEmbedder(embed, cache)
    db = sqlite3.connect(db_path, timeout=60)
    try:
        artifact: dict = {
            "version": VERSION,
            "cree_le": datetime.now(UTC).isoformat(),
            "cibles": {},
        }
        report: dict = {"version": VERSION}
        for target in ("fit", "retenue"):
            rows = _examples(db, target)
            labels = np.array([r[4] for r in rows])
            oof = _oof(rows, embed_title, embed_body)
            low, high = thresholds(labels, oof)
            report[target] = {"hors_pli_toutes_donnees": metrics(labels, oof, low, high)}
            if target == "fit":
                # Contrôle sur le test historique, modèle appris sur le développement seul.
                split = split_company([_as_example(r) for r in rows])
                dev_keys = {x.key for x in split["train"] + split["validation"]}
                dev = [r for r in rows if r[0] in dev_keys]
                test = [r for r in rows if r[0] not in dev_keys]
                dev_labels = np.array([r[4] for r in dev])
                d_low, d_high = thresholds(dev_labels, _oof(dev, embed_title, embed_body))
                model = TextModel().fit(
                    [r[2] for r in dev], [r[3] for r in dev], dev_labels, embed_title, embed_body
                )
                test_scores = model.score(
                    [r[2] for r in test], [r[3] for r in test], embed_title, embed_body
                )
                report[target]["test_deja_consulte_en_v1"] = metrics(
                    np.array([r[4] for r in test]), test_scores, d_low, d_high
                )
            final = TextModel().fit(
                [r[2] for r in rows], [r[3] for r in rows], labels, embed_title, embed_body
            )
            artifact["cibles"][target] = {
                "seuil_basse_priorite": low,
                "seuil_prioriser": high,
                "n_apprentissage": len(rows),
                "empreinte": hashlib.sha256(
                    "\n".join(f"{r[0]}\x1f{r[4]}" for r in rows).encode()
                ).hexdigest(),
                **final.to_artifact(),
            }
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_text(json.dumps(artifact), encoding="utf-8")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        db.close()
        embed_body.close()


def _as_example(row):
    from tri_ml import Example

    return Example(row[0], row[1], row[2], row[4])


CLASSEMENT = """
CREATE TABLE IF NOT EXISTS classement (
    source TEXT NOT NULL,
    identifiant TEXT NOT NULL,
    entreprise TEXT NOT NULL,
    titre TEXT NOT NULL,
    lieu TEXT,
    url TEXT,
    base TEXT NOT NULL,
    score_fit REAL,
    verdict_fit TEXT,
    score_retenue REAL,
    eligible INTEGER NOT NULL,
    motifs TEXT NOT NULL,
    deja_candidature INTEGER NOT NULL,
    version TEXT NOT NULL,
    classe_le TEXT NOT NULL,
    PRIMARY KEY(source, identifiant)
);
"""


def _verdict(score: float, cible: dict) -> str:
    if score <= cible["seuil_basse_priorite"]:
        return "basse_priorite_a_relire"
    return "prioriser" if score >= cible["seuil_prioriser"] else "a_lire"


def _candidates(db: sqlite3.Connection) -> list[dict]:
    rows = []
    for key, company, title, place, url, text in db.execute(
        """SELECT cle,entreprise,titre,lieu,url,texte FROM offres
           WHERE note_json IS NULL AND dans_snapshot=1 AND titre IS NOT NULL"""
    ):
        rows.append(
            dict(
                source="bot",
                identifiant=key,
                entreprise=company,
                titre=title,
                lieu=place,
                url=url,
                texte=nettoyer(text),
                actif=None,
                score_titre=None,
            )
        )
    has_desc = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='swelist_descriptions'"
    ).fetchone()
    join = "LEFT JOIN swelist_descriptions d USING(simplify_id)" if has_desc else ""
    columns = "d.description_texte,d.actif,d.lieux" if has_desc else "NULL,NULL,NULL"
    for sid, company, title, url, score, text, active, places in db.execute(
        f"""SELECT a.simplify_id,a.entreprise,a.intitule,a.lien_simplify,a.score_fit,{columns}
            FROM swelist_annonces a {join}"""
    ):
        rows.append(
            dict(
                source="swelist",
                identifiant=sid,
                entreprise=company,
                titre=title,
                lieu=", ".join(json.loads(places)) if places else None,
                url=url,
                texte=text or "",
                actif=None if active is None else bool(active),
                score_titre=score,
            )
        )
    return rows


def classer(
    db_path: Path,
    model_path: Path,
    title_model_path: Path,
    sortie: Path,
    embed: Embedder = fastembed_embedder,
    cache: Path | None = None,
) -> dict:
    artifact = json.loads(model_path.read_text(encoding="utf-8"))
    title_artifact = json.loads(title_model_path.read_text(encoding="utf-8"))
    embed_title = cached(embed)
    embed_body = BodyEmbedder(embed, cache)
    db = sqlite3.connect(db_path, timeout=60)
    try:
        db.executescript(CLASSEMENT)
        rows = _candidates(db)
        applied = {
            (normaliser(e), normaliser(t))
            for e, t in db.execute(
                "SELECT o.entreprise,o.titre FROM candidatures c JOIN offres o ON o.cle=c.cle_offre"
            )
            if t
        }
        for r in rows:
            r["base"] = "texte" if len(r["texte"]) >= TEXTE_MINIMUM else "titre"
        with_text = [r for r in rows if r["base"] == "texte"]
        without = [r for r in rows if r["base"] == "titre"]
        for target in ("fit", "retenue"):
            cible = artifact["cibles"][target]
            if with_text:
                scores = TextModel.from_artifact(cible).score(
                    [r["titre"] for r in with_text],
                    [r["texte"] for r in with_text],
                    embed_title,
                    embed_body,
                )
                for r, s in zip(with_text, scores, strict=True):
                    r[f"score_{target}"] = float(s)
        if without:
            title_scores = TitleModel.from_artifact(title_artifact).score(
                [r["titre"] for r in without], embed_title
            )
            for r, s in zip(without, title_scores, strict=True):
                r["score_fit"], r["score_retenue"] = float(s), None
        now = datetime.now(UTC).isoformat()
        with db:
            db.execute("DELETE FROM classement")
            for r in rows:
                base = r["base"]
                cible = artifact["cibles"]["fit"] if base == "texte" else title_artifact
                found = verifier(r["titre"], r["texte"], r["actif"])
                r.update(
                    verdict_fit=_verdict(r["score_fit"], cible),
                    eligible=int(not found),
                    motifs=json.dumps(found, ensure_ascii=False),
                    deja=int((normaliser(r["entreprise"]), normaliser(r["titre"])) in applied),
                )
                db.execute(
                    "INSERT INTO classement VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        r["source"],
                        r["identifiant"],
                        r["entreprise"],
                        r["titre"],
                        r["lieu"],
                        r["url"],
                        base,
                        r["score_fit"],
                        r["verdict_fit"],
                        r["score_retenue"],
                        r["eligible"],
                        r["motifs"],
                        r["deja"],
                        VERSION,
                        now,
                    ),
                )
        rows.sort(
            key=lambda r: (-r["eligible"], r["deja"], -(r["score_retenue"] or -1), -r["score_fit"])
        )
        sortie.parent.mkdir(parents=True, exist_ok=True)
        with sortie.open("w", encoding="utf-8-sig", newline="") as fichier:
            writer = csv.writer(fichier, delimiter=";")
            writer.writerow(
                [
                    "rang",
                    "source",
                    "entreprise",
                    "titre",
                    "lieu",
                    "eligible",
                    "motifs",
                    "deja_candidature",
                    "score_retenue",
                    "score_fit",
                    "verdict_fit",
                    "base",
                    "url",
                ]
            )
            for rank, r in enumerate(rows, 1):
                motifs = "; ".join(f"{m}: {p}" for m, p in json.loads(r["motifs"]))
                writer.writerow(
                    [
                        rank,
                        r["source"],
                        r["entreprise"],
                        r["titre"],
                        r["lieu"],
                        r["eligible"],
                        motifs,
                        r["deja"],
                        None if r["score_retenue"] is None else round(r["score_retenue"], 3),
                        round(r["score_fit"], 3),
                        r["verdict_fit"],
                        r["base"],
                        r["url"],
                    ]
                )
        return dict(
            total=len(rows),
            avec_texte=len(with_text),
            eligibles=sum(r["eligible"] for r in rows),
            par_source={s: sum(r["source"] == s for r in rows) for s in ("bot", "swelist")},
            verdicts=dict(
                db.execute("SELECT verdict_fit,COUNT(*) FROM classement GROUP BY verdict_fit")
            ),
        )
    finally:
        db.close()
        embed_body.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True, help="artefact texte JSON")
    parser.add_argument("--cache", type=Path, help="cache SQLite des embeddings")
    sub = parser.add_subparsers(dest="commande", required=True)
    tr = sub.add_parser("entrainer")
    tr.add_argument("--report", type=Path, required=True)
    cl = sub.add_parser("classer")
    cl.add_argument("--modele-titre", type=Path, required=True)
    cl.add_argument("--sortie", type=Path, required=True)
    args = parser.parse_args()
    if args.commande == "entrainer":
        result = train(args.db, args.model, args.report, cache=args.cache)
    else:
        result = classer(args.db, args.model, args.modele_titre, args.sortie, cache=args.cache)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
