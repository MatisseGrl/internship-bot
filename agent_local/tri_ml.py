"""Tri des titres d'offres pour choisir quelles descriptions récupérer d'abord.

La cible est la première note historique « Fit rôle » (1 = hors métier, 3-5 = pertinent),
pas le verdict final gardée/écartée. Un score ne change jamais une décision de candidature
et n'exclut aucune annonce.

Modèle titre-ensemble-v3 : moyenne à poids égaux des log-odds de deux régressions
logistiques, l'une sur des embeddings locaux (BAAI/bge-base-en-v1.5 via fastembed),
l'autre sur des n-grammes de caractères TF-IDF. Le choix, les seuils et les mesures
sont décrits dans docs/TRI_ML_RAPPORT.md. Dépendances : pip install -e ".[ml]".
Aucune API payante n'est appelée.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from import_swelist import normaliser
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold

VERSION = "titre-ensemble-v3"
SEED = "internbot-fit-role-2026-10-15"
EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
CHAR_NGRAMS = (3, 5)
C_TFIDF = 4.0
C_EMBEDDING = 16.0
EMBEDDING_WEIGHT = 0.5
# Seuil bas : au plus 2 % des titres pertinents en basse priorité, mesuré hors pli.
TARGET_FALSE_REJECTS = 0.02
PRIORITY_QUANTILE = 0.8
CV_SEEDS = (11, 12)

Embedder = Callable[[Sequence[str]], np.ndarray]


@dataclass(frozen=True)
class Example:
    key: str
    company: str
    title: str
    label: int


def load_examples(db: sqlite3.Connection) -> tuple[list[Example], dict[str, int]]:
    by_title: dict[str, list[Example]] = defaultdict(list)
    stats: Counter[str] = Counter()
    for key, company, title, raw in db.execute(
        "SELECT cle,entreprise,titre,note_json FROM offres WHERE note_json IS NOT NULL"
    ):
        try:
            note = json.loads(raw)
            grades = note.get("notes", [])
        except (TypeError, ValueError, AttributeError):
            stats["invalid_note"] += 1
            continue
        if not isinstance(grades, list) or not grades or not isinstance(grades[0], int):
            stats["no_fit_role_grade"] += 1
            continue
        if grades[0] == 2 or not title:
            stats["uncertain_or_no_title"] += 1
            continue
        if grades[0] not in (1, 3, 4, 5):
            stats["invalid_fit_role_grade"] += 1
            continue
        stats["negative" if grades[0] == 1 else "positive"] += 1
        item = Example(key, normaliser(company), title, int(grades[0] >= 3))
        by_title[normaliser(title)].append(item)
    examples = []
    for variants in by_title.values():
        votes = Counter(v.label for v in variants)
        if votes[0] == votes[1]:
            # Égalité : aucune étiquette ne l'emporte, le titre est retiré.
            stats["conflicting_titles"] += len(variants)
            continue
        label = votes.most_common(1)[0][0]
        if len(votes) == 2:
            # Un titre courant (« software engineer intern ») ne doit pas disparaître
            # parce qu'une seule de ses annonces était hors métier.
            stats["majority_resolved_titles"] += 1
        examples.append(min((v for v in variants if v.label == label), key=lambda v: v.key))
        stats["duplicate_titles_removed"] += len(variants) - 1
    return sorted(examples, key=lambda v: v.key), dict(stats)


def split_company(examples: list[Example]) -> dict[str, list[Example]]:
    splits: dict[str, list[Example]] = {"train": [], "validation": [], "test": []}
    for item in examples:
        number = int.from_bytes(hashlib.sha256((SEED + item.company).encode()).digest()[:8], "big")
        bucket = number / 2**64
        split = "train" if bucket < 0.6 else "validation" if bucket < 0.8 else "test"
        splits[split].append(item)
    if any({x.label for x in values} != {0, 1} for values in splits.values()):
        raise ValueError("Le découpage par entreprise a perdu une classe")
    return splits


def fastembed_embedder(titles: Sequence[str]) -> np.ndarray:
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=EMBEDDING_MODEL)
    return np.array(list(model.embed(list(titles), batch_size=64)))


def cached(embed: Embedder) -> Embedder:
    """Chaque titre distinct n'est encodé qu'une fois par exécution."""
    store: dict[str, np.ndarray] = {}

    def lookup(titles: Sequence[str]) -> np.ndarray:
        missing = sorted({t for t in titles if t not in store})
        if missing:
            store.update(zip(missing, embed(missing), strict=True))
        return np.vstack([store[t] for t in titles])

    return lookup


class TitleModel:
    """Ensemble figé : tout ce qui sert au score tient dans `to_artifact()`."""

    def __init__(self) -> None:
        self.vocabulary: dict[str, int] = {}
        self.idf = np.zeros(0)
        self.coef_tfidf = np.zeros(0)
        self.bias_tfidf = 0.0
        self.coef_embedding = np.zeros(0)
        self.bias_embedding = 0.0

    def fit(self, titles: Sequence[str], labels: Sequence[int], embed: Embedder) -> TitleModel:
        vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=CHAR_NGRAMS, sublinear_tf=True, min_df=2
        )
        vectorizer.fit([normaliser(t) for t in titles])
        self.vocabulary = {k: int(v) for k, v in vectorizer.vocabulary_.items()}
        self.idf = vectorizer.idf_
        tfidf = LogisticRegression(C=C_TFIDF, max_iter=4000)
        tfidf.fit(self._tfidf(titles), labels)
        self.coef_tfidf, self.bias_tfidf = tfidf.coef_[0], float(tfidf.intercept_[0])
        embedding = LogisticRegression(C=C_EMBEDDING, class_weight="balanced", max_iter=4000)
        embedding.fit(embed(titles), labels)
        self.coef_embedding = embedding.coef_[0]
        self.bias_embedding = float(embedding.intercept_[0])
        return self

    def _tfidf(self, titles: Sequence[str]):
        # Même calcul que TfidfVectorizer (tf sous-linéaire, idf, norme L2), mais à partir
        # du vocabulaire figé : un score ne dépend que de l'artefact.
        counts = CountVectorizer(
            analyzer="char_wb", ngram_range=CHAR_NGRAMS, vocabulary=self.vocabulary
        ).transform([normaliser(t) for t in titles])
        counts = counts.astype(float)
        counts.data = 1 + np.log(counts.data)
        weighted = counts.multiply(self.idf).tocsr()
        norms = np.sqrt(np.asarray(weighted.multiply(weighted).sum(axis=1))).ravel()
        norms[norms == 0] = 1.0
        return weighted.multiply(1 / norms[:, None]).tocsr()

    def score(self, titles: Sequence[str], embed: Embedder) -> np.ndarray:
        z_tfidf = self._tfidf(titles) @ self.coef_tfidf + self.bias_tfidf
        z_embedding = embed(titles) @ self.coef_embedding + self.bias_embedding
        z = EMBEDDING_WEIGHT * z_embedding + (1 - EMBEDDING_WEIGHT) * z_tfidf
        return 1 / (1 + np.exp(-z))

    def to_artifact(self) -> dict:
        return {
            "vocabulaire": self.vocabulary,
            "idf": self.idf.tolist(),
            "coef_tfidf": self.coef_tfidf.tolist(),
            "biais_tfidf": self.bias_tfidf,
            "coef_embedding": self.coef_embedding.tolist(),
            "biais_embedding": self.bias_embedding,
        }

    @classmethod
    def from_artifact(cls, artifact: dict) -> TitleModel:
        model = cls()
        model.vocabulary = artifact["vocabulaire"]
        model.idf = np.array(artifact["idf"])
        model.coef_tfidf = np.array(artifact["coef_tfidf"])
        model.bias_tfidf = artifact["biais_tfidf"]
        model.coef_embedding = np.array(artifact["coef_embedding"])
        model.bias_embedding = artifact["biais_embedding"]
        return model


def out_of_fold(examples: list[Example], embed: Embedder) -> np.ndarray:
    titles = [x.title for x in examples]
    labels = np.array([x.label for x in examples])
    groups = [x.company for x in examples]
    runs = []
    for seed in CV_SEEDS:
        scores = np.zeros(len(examples))
        folds = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
        for train, held in folds.split(titles, labels, groups):
            model = TitleModel().fit([titles[i] for i in train], labels[train], embed)
            scores[held] = model.score([titles[i] for i in held], embed)
        runs.append(scores)
    return np.mean(runs, axis=0)


def thresholds(labels: np.ndarray, scores: np.ndarray) -> tuple[float, float]:
    positives = np.sort(scores[labels == 1])
    allowed = int(np.floor(TARGET_FALSE_REJECTS * len(positives)))
    low = float(positives[allowed]) - 1e-12
    return low, float(np.quantile(scores, PRIORITY_QUANTILE))


def auc(labels: np.ndarray, scores: np.ndarray) -> float:
    pos, neg = scores[labels == 1], scores[labels == 0]
    wins = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(wins / (len(pos) * len(neg)))


def metrics(labels: np.ndarray, scores: np.ndarray, low: float, high: float) -> dict:
    in_low, in_high = scores <= low, scores >= high
    positives = int(labels.sum())
    missed = int(labels[in_low].sum())
    return {
        "n": len(labels),
        "positifs": positives,
        "auc": round(auc(labels, scores), 4),
        "basse_priorite_a_relire": int(in_low.sum()),
        "pertinents_en_basse_priorite": missed,
        "taux_faux_rejet_si_exclus": round(missed / positives, 4) if positives else None,
        "priorises": int(in_high.sum()),
        "precision_priorite": round(float(labels[in_high].mean()), 4) if in_high.any() else None,
    }


def verdict(score: float, artifact: dict) -> str:
    if score <= artifact["seuil_basse_priorite"]:
        return "basse_priorite_a_relire"
    return "prioriser" if score >= artifact["seuil_prioriser"] else "a_lire"


def score_swelist(
    db: sqlite3.Connection, artifact: dict, embed: Embedder, only_missing: bool
) -> int:
    """Écrit score, verdict et version ; ne touche ni aux labels humains ni à `offres`."""
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='swelist_annonces'"
    ).fetchone():
        raise ValueError("Importer SWElist avant de noter les titres")
    query = "SELECT simplify_id,intitule FROM swelist_annonces"
    params: tuple = ()
    if only_missing:
        query += " WHERE score_fit IS NULL OR version_modele IS NOT ?"
        params = (artifact["version"],)
    rows = db.execute(query, params).fetchall()
    if not rows:
        return 0
    model = TitleModel.from_artifact(artifact)
    scores = model.score([title for _, title in rows], embed)
    now = datetime.now(UTC).isoformat()
    with db:
        for (sid, _), value in zip(rows, scores, strict=True):
            db.execute(
                """UPDATE swelist_annonces SET score_fit=?,verdict_ml=?,
                       version_modele=?,evalue_le=? WHERE simplify_id=?""",
                (float(value), verdict(value, artifact), artifact["version"], now, sid),
            )
    return len(rows)


def swelist_classes(db: sqlite3.Connection) -> dict:
    return dict(db.execute("SELECT verdict_ml,COUNT(*) FROM swelist_annonces GROUP BY verdict_ml"))


BOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS tri_offres_bot (
    cle_offre TEXT PRIMARY KEY REFERENCES offres(cle),
    score_fit REAL NOT NULL CHECK(score_fit BETWEEN 0 AND 1),
    verdict_ml TEXT NOT NULL,
    version_modele TEXT NOT NULL,
    evalue_le TEXT NOT NULL
);
"""


def score_bot(db: sqlite3.Connection, artifact: dict, embed: Embedder) -> int:
    """Note les offres actuelles du bot sans note de grille, dans une table à part.

    Les colonnes de `offres` (note de grille, score, catégorie) ne sont jamais modifiées.
    """
    db.executescript(BOT_SCHEMA)
    rows = db.execute(
        """SELECT o.cle,o.titre FROM offres o
           LEFT JOIN tri_offres_bot t ON t.cle_offre=o.cle
           WHERE o.note_json IS NULL AND o.dans_snapshot=1 AND o.titre IS NOT NULL
             AND (t.cle_offre IS NULL OR t.version_modele IS NOT ?)""",
        (artifact["version"],),
    ).fetchall()
    if not rows:
        return 0
    scores = TitleModel.from_artifact(artifact).score([title for _, title in rows], embed)
    now = datetime.now(UTC).isoformat()
    with db:
        db.executemany(
            """INSERT INTO tri_offres_bot VALUES(?,?,?,?,?) ON CONFLICT(cle_offre) DO UPDATE SET
               score_fit=excluded.score_fit,verdict_ml=excluded.verdict_ml,
               version_modele=excluded.version_modele,evalue_le=excluded.evalue_le""",
            [
                (key, float(value), verdict(value, artifact), artifact["version"], now)
                for (key, _), value in zip(rows, scores, strict=True)
            ],
        )
    return len(rows)


def bot_classes(db: sqlite3.Connection) -> dict:
    db.executescript(BOT_SCHEMA)
    return dict(db.execute("SELECT verdict_ml,COUNT(*) FROM tri_offres_bot GROUP BY verdict_ml"))


def train(
    db_path: Path,
    model_path: Path,
    report_path: Path,
    errors_path: Path,
    embed: Embedder = fastembed_embedder,
) -> dict:
    embed = cached(embed)
    db = sqlite3.connect(db_path, timeout=30)
    try:
        examples, data_stats = load_examples(db)
        split = split_company(examples)
        dev, test = split["train"] + split["validation"], split["test"]
        dev_labels = np.array([x.label for x in dev])
        test_labels = np.array([x.label for x in test])

        # 1. Évaluation : seuils fixés hors pli sur le développement, appliqués au test.
        dev_oof = out_of_fold(dev, embed)
        low, high = thresholds(dev_labels, dev_oof)
        dev_model = TitleModel().fit([x.title for x in dev], dev_labels, embed)
        test_scores = dev_model.score([x.title for x in test], embed)

        # 2. Modèle livré : toutes les étiquettes, seuils hors pli sur l'ensemble.
        labels = np.array([x.label for x in examples])
        final_low, final_high = thresholds(labels, out_of_fold(examples, embed))
        final = TitleModel().fit([x.title for x in examples], labels, embed)
        fingerprint = hashlib.sha256(
            "\n".join(f"{x.key}\x1f{x.label}" for x in examples).encode()
        ).hexdigest()
        artifact = {
            "version": VERSION,
            "embedding": EMBEDDING_MODEL,
            "poids_embedding": EMBEDDING_WEIGHT,
            "empreinte_apprentissage": fingerprint,
            "n_apprentissage": len(examples),
            "seuil_basse_priorite": final_low,
            "seuil_prioriser": final_high,
            "cree_le": datetime.now(UTC).isoformat(),
            **final.to_artifact(),
        }
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_text(json.dumps(artifact), encoding="utf-8")

        score_swelist(db, artifact, embed, only_missing=False)
        report = {
            "version": VERSION,
            "cible": "Fit role 1 contre Fit role 3-5",
            "note": (
                "Score de tri, non une probabilite calibree ni une decision de candidature. "
                "Aucun rejet automatique."
            ),
            "extraction": data_stats,
            "developpement_hors_pli": metrics(dev_labels, dev_oof, low, high),
            "test_deja_consulte_en_v1": metrics(test_labels, test_scores, low, high),
            "seuils_livres": [final_low, final_high],
            "entreprises_communes_dev_test": len(
                {x.company for x in dev} & {x.company for x in test}
            ),
            "swelist_classes": swelist_classes(db),
        }
        audit = db.execute(
            "SELECT label_humain,score_fit FROM swelist_annonces WHERE label_humain IS NOT NULL"
        ).fetchall()
        if audit:
            audit_labels = np.array([label for label, _ in audit])
            audit_scores = np.array([score for _, score in audit])
            report["audit_humain_swelist"] = (
                metrics(audit_labels, audit_scores, final_low, final_high)
                if set(audit_labels.tolist()) == {0, 1}
                else {"n": len(audit), "note": "Deux classes nécessaires pour les métriques."}
            )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with errors_path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["entreprise", "titre", "label_fit", "score_fit", "erreur"])
            for example, score in zip(test, test_scores, strict=True):
                error = (
                    "pertinent_en_basse_priorite"
                    if example.label == 1 and score <= low
                    else ("hors_metier_priorise" if example.label == 0 and score >= high else "")
                )
                if error:
                    writer.writerow(
                        [example.company, example.title, example.label, round(score, 6), error]
                    )
        return report
    finally:
        db.close()


def score_only(db_path: Path, model_path: Path, embed: Embedder = fastembed_embedder) -> dict:
    """Note les annonces SWElist et les offres du bot sans note, sans réentraîner."""
    artifact = json.loads(model_path.read_text(encoding="utf-8"))
    embed = cached(embed)
    db = sqlite3.connect(db_path, timeout=30)
    try:
        scored = score_swelist(db, artifact, embed, only_missing=True)
        bot = score_bot(db, artifact, embed)
        return {
            "version": artifact["version"],
            "notees": scored,
            "classes": swelist_classes(db),
            "bot_notees": bot,
            "classes_bot": bot_classes(db),
        }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True, help="artefact JSON du modèle")
    parser.add_argument("--noter", action="store_true", help="noter sans réentraîner")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--errors", type=Path)
    args = parser.parse_args()
    if args.noter:
        print(json.dumps(score_only(args.db, args.model), ensure_ascii=False))
        return
    if not (args.report and args.errors):
        parser.error("--report et --errors sont requis pour entraîner")
    report = train(args.db, args.model, args.report, args.errors)
    print(
        json.dumps(
            {
                "developpement_hors_pli": report["developpement_hors_pli"],
                "test_deja_consulte_en_v1": report["test_deja_consulte_en_v1"],
                "swelist_classes": report["swelist_classes"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
