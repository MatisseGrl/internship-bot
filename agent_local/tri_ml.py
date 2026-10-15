"""Low-cost, selective title model for prioritising descriptions to retrieve.

The target is the historical first score (Fit role), not the final rejected/kept
verdict. A score never changes an application decision. No paid API is used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from import_swelist import normaliser
from ingest_swelist import title_filter

VERSION = "titre-logreg-v1"
SEED = "internbot-fit-role-2026-10-15"


@dataclass(frozen=True)
class Example:
    key: str
    company: str
    title: str
    label: int


def load_examples(db: sqlite3.Connection) -> tuple[list[Example], dict[str, int]]:
    by_title: dict[str, list[Example]] = defaultdict(list)
    stats = Counter()
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
    for title, variants in by_title.items():
        if len({v.label for v in variants}) != 1:
            stats["conflicting_titles"] += len(variants)
            continue
        examples.append(min(variants, key=lambda v: v.key))
        stats["duplicate_titles_removed"] += len(variants) - 1
    return sorted(examples, key=lambda v: v.key), dict(stats)


def split_company(examples: list[Example]) -> dict[str, list[Example]]:
    splits = {"train": [], "validation": [], "test": []}
    for item in examples:
        number = int.from_bytes(hashlib.sha256((SEED + item.company).encode()).digest()[:8], "big")
        bucket = number / 2**64
        split = "train" if bucket < 0.6 else "validation" if bucket < 0.8 else "test"
        splits[split].append(item)
    if any({x.label for x in values} != {0, 1} for values in splits.values()):
        raise ValueError("Le découpage par entreprise a perdu une classe")
    return splits


def features(title: str) -> Counter[str]:
    title = normaliser(title)
    words = re.findall(r"[a-z0-9]+", title)
    values = Counter("w:" + word for word in words)
    values.update("b:" + words[i] + "_" + words[i + 1] for i in range(len(words) - 1))
    padded = "^" + title + "$"
    for width in (3, 4, 5):
        values.update("c:" + padded[i:i + width] for i in range(len(padded) - width + 1))
    return values


class Vectorizer:
    def __init__(self, titles: list[str]):
        df = Counter()
        for title in titles:
            df.update(features(title).keys())
        candidates = [name for name, count in df.items() if count >= 2]
        candidates.sort(key=lambda name: (-df[name], name))
        self.names = candidates[:30000]
        self.lookup = {name: index for index, name in enumerate(self.names)}
        self.idf = [math.log((1 + len(titles)) / (1 + df[name])) + 1 for name in self.names]

    def transform(self, title: str) -> list[tuple[int, float]]:
        values = [(self.lookup[name], (1 + math.log(count)) * self.idf[self.lookup[name]])
                  for name, count in features(title).items() if name in self.lookup]
        length = math.sqrt(sum(value * value for _, value in values)) or 1.0
        return [(index, value / length) for index, value in values]


def sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    positive = math.exp(value)
    return positive / (1 + positive)


class Logistic:
    def __init__(self, size: int):
        self.weights = [0.0] * size
        self.bias = 0.0

    def predict(self, vector: list[tuple[int, float]]) -> float:
        return sigmoid(self.bias + sum(self.weights[index] * value for index, value in vector))

    def fit(self, rows: list[tuple[list[tuple[int, float]], int]]) -> None:
        order = list(range(len(rows)))
        rng = random.Random(42)
        for epoch in range(95):
            rng.shuffle(order)
            rate = 0.7 / (1 + epoch / 35)
            for start in range(0, len(rows), 32):
                batch = order[start:start + 32]
                gradient = defaultdict(float)
                intercept = 0.0
                for i in batch:
                    vector, label = rows[i]
                    error = self.predict(vector) - label
                    intercept += error
                    for index, value in vector:
                        gradient[index] += error * value
                scale = rate / len(batch)
                for index, value in gradient.items():
                    self.weights[index] -= scale * value
                self.bias -= scale * intercept
            # Global L2 shrinkage keeps rare n-grams from dominating.
            shrink = 1 - rate * 0.0005
            self.weights = [weight * shrink for weight in self.weights]


def auc(items: list[tuple[int, float]]) -> float:
    positives = [score for label, score in items if label == 1]
    negatives = [score for label, score in items if label == 0]
    return sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives) / (
        len(positives) * len(negatives)
    )


def metrics(items: list[tuple[int, float]], reject: float, priority: float) -> dict:
    low_priority = [(y, s) for y, s in items if s <= reject]
    prioritized = [(y, s) for y, s in items if s >= priority]
    positives = sum(y for y, _ in items)
    missed = sum(y for y, _ in low_priority)
    return {
        "n": len(items), "positifs": positives, "negatifs": len(items) - positives,
        "auc": round(auc(items), 4),
        "basse_priorite_a_relire": len(low_priority),
        "pertinents_en_basse_priorite": missed,
        "taux_faux_rejet_si_exclus": round(missed / positives, 4),
        "priorises": len(prioritized),
        "precision_priorite": round(sum(y for y, _ in prioritized) / len(prioritized), 4)
        if prioritized else None,
    }


def run(db_path: Path, report_path: Path, errors_path: Path) -> dict:
    db = sqlite3.connect(db_path, timeout=30)
    try:
        examples, data_stats = load_examples(db)
        split = split_company(examples)
        train, validation, test = (split[x] for x in ("train", "validation", "test"))
        vectorizer = Vectorizer([x.title for x in train])
        model = Logistic(len(vectorizer.names))
        model.fit([(vectorizer.transform(x.title), x.label) for x in train])
        scored = {name: [(x.label, model.predict(vectorizer.transform(x.title))) for x in rows]
                  for name, rows in split.items()}
        validation_positive = [score for label, score in scored["validation"] if label == 1]
        reject = max(0.0, min(validation_positive) - 1e-9)
        priority = sorted(score for _, score in scored["validation"])[
            int(0.8 * (len(validation) - 1))
        ]
        report = {
            "version": VERSION, "cible": "Fit role 1 contre Fit role 3-5",
            "note": "Score de tri, non une probabilite calibree ni une decision de candidature. Aucun rejet automatique.",
            "regles": "Un titre normalise une fois; entreprises distinctes entre jeux.",
            "extraction": data_stats, "taille_vocabulaire": len(vectorizer.names),
            "seuil_basse_priorite": reject, "seuil_prioriser": priority,
            "train": metrics(scored["train"], reject, priority),
            "validation": metrics(scored["validation"], reject, priority),
            "test": metrics(scored["test"], reject, priority),
        }
        overlap_company = (set(x.company for x in train) & set(x.company for x in validation)
                           | set(x.company for x in train) & set(x.company for x in test)
                           | set(x.company for x in validation) & set(x.company for x in test))
        report["entreprises_communes_entre_jeux"] = len(overlap_company)
        report["titres_communs_entre_jeux"] = len(set(normaliser(x.title) for x in train)
            & (set(normaliser(x.title) for x in validation) | set(normaliser(x.title) for x in test)))
        report["regle_existante_test"] = {
            "basse_priorite": sum(title_filter(x.title)[0] == "ecarter_titre" for x in test),
            "pertinents_en_basse_priorite": sum(x.label == 1 and title_filter(x.title)[0] == "ecarter_titre" for x in test),
        }
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='swelist_annonces'").fetchone():
            raise ValueError("Importer SWElist avant de noter les titres")
        now = datetime.now(UTC).isoformat()
        with db:
            for sid, title in db.execute("SELECT simplify_id,intitule FROM swelist_annonces").fetchall():
                score = model.predict(vectorizer.transform(title))
                verdict = "basse_priorite_a_relire" if score <= reject else (
                    "prioriser" if score >= priority else "a_lire"
                )
                db.execute("""UPDATE swelist_annonces SET score_fit=?,verdict_ml=?,
                           version_modele=?,evalue_le=? WHERE simplify_id=?""",
                           (score, verdict, VERSION, now, sid))
        report["swelist_classes"] = dict(db.execute(
            "SELECT verdict_ml,COUNT(*) FROM swelist_annonces GROUP BY verdict_ml"
        ))
        audit = list(db.execute(
            "SELECT label_humain,score_fit FROM swelist_annonces WHERE label_humain IS NOT NULL"
        ))
        if audit:
            report["audit_humain_swelist"] = (
                metrics(audit, reject, priority) if {label for label, _ in audit} == {0, 1}
                else {"n": len(audit), "note": "Deux classes nécessaires pour calculer les métriques."}
            )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with errors_path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["entreprise", "titre", "label_fit", "score_fit", "erreur"])
            for example, (label, score) in zip(test, scored["test"], strict=True):
                error = "pertinent_en_basse_priorite" if label == 1 and score <= reject else (
                    "hors_metier_priorise" if label == 0 and score >= priority else ""
                )
                if error:
                    writer.writerow([example.company, example.title, label, round(score, 6), error])
        return report
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--errors", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.db, args.report, args.errors)
    print(json.dumps({"validation": report["validation"], "test": report["test"],
                      "swelist_classes": report["swelist_classes"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
