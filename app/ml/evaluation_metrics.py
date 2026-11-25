"""Metrics on supplied predictions only. Standard library, no estimator fitting."""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict


def primary(task: str, counts: Counter, classes: tuple) -> float | None:
    if not counts or any(sum(n for (y, _), n in counts.items() if y == label) == 0 for label in classes):
        return None
    if task == "p2":
        return sum((p-y)**2*n for (y, p), n in counts.items()) / sum(counts.values())
    scores = []
    for label in classes:
        tp = counts[label, label]
        fp = sum(n for (y, p), n in counts.items() if p == label and y != label)
        fn = sum(n for (y, p), n in counts.items() if y == label and p != label)
        scores.append(2*tp/(2*tp+fp+fn))
    return sum(scores)/len(scores)


def summarize(task: str, labels: list, predictions: list, *, classes: tuple, bins: int) -> dict:
    if len(labels) != len(predictions) or not labels:
        raise ValueError("Cohorte vacia o desalineada")
    covered = [(y, p) for y, p in zip(labels, predictions, strict=True) if p is not None]
    support = Counter(labels)
    result = {"rows": len(labels), "covered": len(covered), "coverage": len(covered)/len(labels),
              "support": {str(label): support[label] for label in classes}}
    if task == "p1":
        counts = Counter(zip(labels, predictions, strict=True))
        per_class = {}
        for label in classes:
            tp = counts[label, label]
            predicted = sum(p == label for p in predictions)
            per_class[str(label)] = {"precision": tp/predicted if predicted else None,
                                     "recall": tp/support[label] if support[label] else None,
                                     "support": support[label]}
        result.update(primary=primary(task, counts, classes), per_class=per_class,
                      accuracy_end_to_end=sum(y == p for y, p in zip(labels, predictions, strict=True))/len(labels),
                      accuracy_conditional=sum(y == p for y, p in covered)/len(covered) if covered else None,
                      confusion={str(label): {str(pred): counts[label, pred] for pred in (*classes, None)} for label in classes})
        return result
    brier = sum((p-y)**2 for y, p in covered)/len(covered) if covered else None
    calibration = []
    for index in range(bins):
        values = [(y, p) for y, p in covered if min(int(p*bins), bins-1) == index]
        calibration.append({"bin": index, "rows": len(values),
                            "mean_prediction": sum(p for _, p in values)/len(values) if values else None,
                            "observed_rate": sum(y for y, _ in values)/len(values) if values else None})
    positives = sum(y for y, _ in covered)
    negatives = len(covered)-positives
    auc, ap = None, None
    if positives and negatives:
        tied = defaultdict(lambda: [0, 0])
        for y, probability in covered:
            tied[probability][y] += 1
        rank, rank_sum = 1, 0
        for probability in sorted(tied):
            negative, positive = tied[probability]
            size = negative+positive
            rank_sum += positive*(rank+(size-1)/2)
            rank += size
        auc = (rank_sum-positives*(positives+1)/2)/(positives*negatives)
        tp, fp, ap = 0, 0, 0.0
        for probability in sorted(tied, reverse=True):
            negative, positive = tied[probability]
            tp += positive
            fp += negative
            ap += positive/positives * tp/(tp+fp)
    result.update(primary=brier, brier=brier, auroc=auc, average_precision=ap, calibration=calibration,
                  ece=sum(row["rows"]*abs(row["mean_prediction"]-row["observed_rate"]) for row in calibration if row["rows"])/len(covered) if covered else None)
    return result


def paired_interval(task: str, labels: list, baseline: list, candidate: list, groups: list,
                    *, classes: tuple, repetitions: int, seed: int, minimum_units: int) -> dict:
    """Paired percentile cluster bootstrap, conditional common cohort for P2 abstentions.

    Reports inadequate replication/support rather than manufacturing a finite interval.
    Validity of the chosen cluster unit must be reviewed with the domain/data owner.
    """
    paired = [(y, b, c, g) for y, b, c, g in zip(labels, baseline, candidate, groups, strict=True)
              if task == "p1" or (b is not None and c is not None)]
    result = {"common_rows": len(paired), "independent_units": len({g for *_, g in paired if g is not None}),
              "lower": None, "upper": None, "benefit": None, "repetitions": repetitions, "valid_repetitions": 0}
    if not paired or any(g is None for *_, g in paired):
        return result | {"reason": "missing_uncertainty_unit"}
    clusters = defaultdict(lambda: (Counter(), Counter()))
    moments = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for y, b, c, group in paired:
        if task == "p2":
            moments[group][0] += 1
            moments[group][1] += y
            moments[group][2] += (b-y)**2
            moments[group][3] += (c-y)**2
        else:
            clusters[group][0][y, b] += 1
            clusters[group][1][y, c] += 1
    units = sorted(moments if task == "p2" else clusters)
    if len(units) < minimum_units or len(units)*repetitions > 2_000_000:
        return result | {"reason": "insufficient_units_or_resampling_budget"}
    if task == "p2":
        positive = sum(row[0] for row in paired)
        if positive == 0 or positive == len(paired):
            return result | {"reason": "missing_class_support"}
        b_score = sum(value[2] for value in moments.values())/len(paired)
        c_score = sum(value[3] for value in moments.values())/len(paired)
    else:
        b_all, c_all = Counter(), Counter()
        for b, c in clusters.values():
            b_all.update(b)
            c_all.update(c)
        b_score, c_score = primary(task, b_all, classes), primary(task, c_all, classes)
    if b_score is None or c_score is None:
        return result | {"reason": "missing_class_support"}
    direction = 1 if task == "p1" else -1
    result["benefit"] = direction*(c_score-b_score)
    randomizer = random.Random(seed)
    estimates = []
    for _ in range(repetitions):
        weights = Counter(randomizer.choices(units, k=len(units)))
        if task == "p2":
            total = sum(moments[unit][0]*weight for unit, weight in weights.items())
            positive = sum(moments[unit][1]*weight for unit, weight in weights.items())
            if positive and positive < total:
                estimates.append(sum((moments[unit][2]-moments[unit][3])*weight for unit, weight in weights.items())/total)
            continue
        b_counts, c_counts = Counter(), Counter()
        for unit, weight in weights.items():
            for pair, count in clusters[unit][0].items():
                b_counts[pair] += count*weight
            for pair, count in clusters[unit][1].items():
                c_counts[pair] += count*weight
        b_score, c_score = primary(task, b_counts, classes), primary(task, c_counts, classes)
        if b_score is not None and c_score is not None:
            estimates.append(direction*(c_score-b_score))
    result["valid_repetitions"] = len(estimates)
    if len(estimates) < math.ceil(0.9*repetitions):
        return result | {"reason": "insufficient_valid_bootstrap_replicates"}
    estimates.sort()

    def percentile(q):
        position = q*(len(estimates)-1)
        lower = int(position)
        upper = min(lower+1, len(estimates)-1)
        return estimates[lower]+(position-lower)*(estimates[upper]-estimates[lower])

    return result | {"lower": percentile(0.025), "upper": percentile(0.975), "reason": None}
