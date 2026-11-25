"""ML-13 descriptive synthetic monitoring. No fitting, inference or promotion.

Missing labels are never negatives. P2 uses the same full 30-day observability
requirement for positive and negative outcomes. Thresholds are reviewed policy,
not statistical significance or permission to change a live model.
"""

from collections import Counter
from datetime import timedelta
from math import isfinite

from app.ml.batch_contract import digest
from app.ml.evaluation_metrics import summarize
from app.ml.evaluation_protocol import CANDIDATES, Protocol, instant, token
from app.ml.export_snapshot import exact
from app.ml.pipelines import TASKS, recipe
from app.ml.taxonomy import Category
from app.ml.temporal_dataset import DATASET_VERSION, HORIZON, SOURCES

VERSION = "rejection-monitor-v1-draft"
REQUEST_VERSION = "rejection-candidate-request-v1-draft"
CLASSES = tuple(category.value for category in Category)
MAX_ROWS = 5000


def policy_template() -> dict:
    """Draft engineering values only. Operator must review costs/support first."""
    return {"version": VERSION, "criteria_status": "draft", "review_sha256": None,
        "minimum_rows": 100, "minimum_units": 30, "minimum_labels": 100, "minimum_class_rows": 5,
        "maximum_source_age_hours": 48, "minimum_prediction_coverage": 0.8, "minimum_label_coverage": 0.8,
        "maximum_missing_rate": 0.1, "maximum_unknown_rate": 0.1, "maximum_failure_rate": 0.05,
        "maximum_distribution_tvd": 0.2, "maximum_brier_increase": 0.03, "maximum_ece": 0.1, "maximum_f1_drop": 0.03,
        "amount_edges_clp": [1000, 5000, 20000], "elapsed_edges_days": [1, 7, 15], "due_edges_days": [-30, -1, 1, 30]}


def _number(value, lower, upper):
    if type(value) not in {int, float} or not isfinite(value) or not lower <= value <= upper:
        raise ValueError("Valor numerico de monitoreo invalido")
    return value


def validate_policy(value: dict) -> dict:
    exact(value, set(policy_template()))
    if value["version"] != VERSION or value["criteria_status"] not in {"draft", "reviewed"}:
        raise ValueError("Politica de monitoreo invalida")
    if value["criteria_status"] == "reviewed":
        token(value["review_sha256"])
    elif value["review_sha256"] is not None:
        raise ValueError("La politica borrador no acredita revision")
    for key in ("minimum_rows", "minimum_units", "minimum_labels", "minimum_class_rows"):
        if type(value[key]) is not int or not 1 <= value[key] <= MAX_ROWS:
            raise ValueError("Soporte minimo invalido")
    _number(value["maximum_source_age_hours"], 1, 720)
    for key in ("minimum_prediction_coverage", "minimum_label_coverage", "maximum_missing_rate",
                "maximum_unknown_rate", "maximum_failure_rate", "maximum_distribution_tvd",
                "maximum_brier_increase", "maximum_ece", "maximum_f1_drop"):
        _number(value[key], 0, 1)
    for key, upper in (("amount_edges_clp", 10**15), ("elapsed_edges_days", 29)):
        edges = value[key]
        if (type(edges) is not list or not 1 <= len(edges) <= 20
                or any(type(n) is not int or not 0 < n <= upper for n in edges)
                or sorted(set(edges)) != edges):
            raise ValueError("Bins fijos invalidos")
    edges = value["due_edges_days"]
    if (type(edges) is not list or not 1 <= len(edges) <= 20
            or any(type(n) is not int or not -36500 <= n <= 36500 for n in edges)
            or sorted(set(edges)) != edges):
        raise ValueError("Bins de vencimiento invalidos")
    return value


def _row(row, task, source, start, end, as_of):
    exact(row, {"event_id", "unit_id", "source", "predicted_at", "available_at", "prediction", "label",
        "label_available_at", "label_origin", "label_provenance_sha256", "outcome_link_verified",
        "outcome_verified_through", "input_missing", "context_unseen", "failed", "latency_ms",
        "amount_clp", "elapsed_days", "days_from_due"})
    token(row["event_id"])
    token(row["unit_id"])
    predicted, available = instant(row["predicted_at"]), instant(row["available_at"])
    if row["source"] != source or not start <= predicted < end or available > predicted or predicted > as_of:
        raise ValueError("Fila de otra cuenta/ventana o con fuga temporal")
    for key in ("outcome_link_verified", "input_missing", "context_unseen", "failed"):
        if type(row[key]) is not bool:
            raise ValueError("Indicador invalido")
    _number(row["latency_ms"], 0, 60000)
    if row["failed"] and row["prediction"] is not None:
        raise ValueError("Un fallo no puede incluir prediccion")
    if task == "p1":
        if any(value is not None and value not in CLASSES for value in (row["prediction"], row["label"])):
            raise ValueError("Familia P1 invalida")
        if any(row[key] is not None for key in ("amount_clp", "elapsed_days", "days_from_due")):
            raise ValueError("Variables fuera de la tarea P1")
        if row["outcome_verified_through"] is not None or row["outcome_link_verified"]:
            raise ValueError("P1 no verifica pagos futuros")
    else:
        if row["prediction"] is not None:
            _number(row["prediction"], 0, 1)
        if row["label"] is not None and (type(row["label"]) is not int or row["label"] not in {0, 1}):
            raise ValueError("Resultado P2 invalido")
        if row["amount_clp"] is not None and (type(row["amount_clp"]) is not int or not 0 < row["amount_clp"] <= 10**15):
            raise ValueError("Monto CLP invalido")
        if row["elapsed_days"] is not None:
            _number(row["elapsed_days"], 0, 29.999999)
        if row["days_from_due"] is not None:
            _number(row["days_from_due"], -36500, 36500)
    if row["label"] is None:
        if any(row[key] is not None for key in ("label_available_at", "label_origin", "label_provenance_sha256")):
            raise ValueError("Etiqueta ausente con procedencia contradictoria")
    else:
        if task == "p2" and instant(row["label_available_at"]) < predicted:
            raise ValueError("Etiqueta anterior a la prediccion")
        token(row["label_provenance_sha256"])
        expected = "independent_human_review" if task == "p1" else "verified_obligation_outcome"
        if row["label_origin"] != expected:
            raise ValueError("Etiqueta sin procedencia independiente")
    if row["outcome_verified_through"] is not None and instant(row["outcome_verified_through"]) > as_of:
        raise ValueError("Cobertura de resultado futura")


def _hist(values, bins=None):
    def bucket(value):
        if value is None:
            return "missing"
        return str(sum(value >= edge for edge in bins)) if bins is not None else str(value)
    return dict(sorted(Counter(bucket(value) for value in values).items()))


def tvd(reference: dict, current: dict) -> float | None:
    """Descriptive total variation distance over common fixed bins, missing included."""
    a, b = sum(reference.values()), sum(current.values())
    if not a or not b:
        return None
    return sum(abs(reference.get(key, 0)/a-current.get(key, 0)/b) for key in sorted(reference.keys() | current.keys()))/2


def _cohort(rows, task, as_of, policy):
    count = len(rows)
    labeled, exclusions = [], Counter()
    eligible = []
    for row in rows:
        if task == "p2" and instant(row["predicted_at"]) + HORIZON > as_of:
            exclusions["immature_30_day_window"] += 1
            continue
        eligible.append(row)
        if row["label"] is None:
            exclusions["label_missing"] += 1
        elif instant(row["label_available_at"]) > as_of:
            exclusions["label_not_available_at_cutoff"] += 1
        elif task == "p2" and row["label"] == 0 and instant(row["label_available_at"]) < instant(row["predicted_at"]) + HORIZON:
            exclusions["premature_negative_label"] += 1
        elif task == "p2" and (not row["outcome_link_verified"] or row["outcome_verified_through"] is None
                or instant(row["outcome_verified_through"]) < instant(row["predicted_at"]) + HORIZON):
            exclusions["outcome_link_or_coverage_unverified"] += 1
        else:
            labeled.append(row)
    classes = CLASSES if task == "p1" else (0, 1)
    supported = labeled if task == "p1" else [row for row in labeled if row["prediction"] is not None]
    counts = Counter(row["label"] for row in supported)
    quality_ready = (len(supported) >= policy["minimum_labels"]
        and len({row["unit_id"] for row in supported}) >= policy["minimum_units"]
        and all(counts[category] >= policy["minimum_class_rows"] for category in classes))
    metrics = summarize(task, [row["label"] for row in labeled], [row["prediction"] for row in labeled], classes=classes, bins=10) if labeled else None
    distributions = {"prediction": _hist([row["prediction"] for row in rows], [n/10 for n in range(1, 10)] if task == "p2" else None)}
    if task == "p2":
        distributions.update(amount_clp=_hist([row["amount_clp"] for row in rows], policy["amount_edges_clp"]),
                             elapsed_days=_hist([row["elapsed_days"] for row in rows], policy["elapsed_edges_days"]),
                             days_from_due=_hist([row["days_from_due"] for row in rows], policy["due_edges_days"]))
    return {"rows": count, "distinct_units": len({row["unit_id"] for row in rows}),
        "prediction_coverage": sum(row["prediction"] is not None for row in rows)/count if count else None,
        "missing_input_rate": sum(row["input_missing"] or (task == "p2" and any(row[key] is None for key in (
            "amount_clp", "elapsed_days", "days_from_due"))) for row in rows)/count if count else None,
        "unknown_context_rate": sum(row["context_unseen"] for row in rows)/count if count else None,
        "failure_rate": sum(row["failed"] for row in rows)/count if count else None,
        "mean_latency_ms": sum(row["latency_ms"] for row in rows)/count if count else None,
        "mature_or_review_eligible": len(eligible), "verified_labels": len(labeled),
        "label_coverage": len(labeled)/len(eligible) if eligible else None,
        "quality_ready": quality_ready, "exclusions": dict(sorted(exclusions.items())),
        "metrics": metrics, "distributions": distributions}


def analyze(snapshot: dict, policy: dict) -> dict:
    """No I/O. This API only accepts synthetic cohorts and returns private aggregates."""
    policy = validate_policy(policy)
    exact(snapshot, {"version", "purpose", "source", "task", "as_of", "source_verified_at",
        "reference_start", "reference_end", "current_start", "current_end", "coverage_verified",
        "model_mode", "artifact_id", "model_feature_schema_sha256", "baseline_protocol_sha256",
        "reference", "current"})
    task = snapshot["task"]
    if snapshot["version"] != VERSION or snapshot["purpose"] != "synthetic" or snapshot["source"] not in SOURCES or task not in {"p1", "p2"}:
        raise ValueError("Solo monitoreo sintetico por tarea y cuenta concreta")
    if snapshot["model_mode"] not in {"rules_only", "synthetic_predictions"}:
        raise ValueError("Modo de prediccion no admitido")
    if snapshot["model_mode"] == "rules_only":
        if task != "p1" or snapshot["artifact_id"] is not None:
            raise ValueError("Reglas P1 sin modelo no acreditan probabilidad P2")
    else:
        token(snapshot["artifact_id"])
    token(snapshot["baseline_protocol_sha256"])
    expected = recipe("char_tfidf_logistic" if task == "p1" else "logistic")["schema_sha256"]
    if snapshot["model_feature_schema_sha256"] != expected:
        raise ValueError("Esquema de variables incompatible")
    as_of = instant(snapshot["as_of"])
    a, b, c, d = (instant(snapshot[key]) for key in ("reference_start", "reference_end", "current_start", "current_end"))
    if not a < b <= c < d <= as_of or type(snapshot["coverage_verified"]) is not bool:
        raise ValueError("Ventanas de monitoreo invalidas")
    source_time = instant(snapshot["source_verified_at"]) if snapshot["source_verified_at"] is not None else None
    if source_time is not None and source_time > as_of:
        raise ValueError("Frescura futura")
    ids = set()
    for name, start, end in (("reference", a, b), ("current", c, d)):
        rows = snapshot[name]
        if type(rows) is not list or len(rows) > MAX_ROWS:
            raise ValueError("Cohorte excesiva")
        for row in rows:
            _row(row, task, snapshot["source"], start, end, as_of)
            if row["event_id"] in ids:
                raise ValueError("Evento repetido entre cohortes")
            ids.add(row["event_id"])
    reference, current = (_cohort(sorted(snapshot[key], key=lambda row: row["event_id"]), task, as_of, policy) for key in ("reference", "current"))
    drift = {key: tvd(reference["distributions"][key], current["distributions"][key]) for key in reference["distributions"]}
    support = all(cohort["rows"] >= policy["minimum_rows"] and cohort["distinct_units"] >= policy["minimum_units"] for cohort in (reference, current))
    fresh = source_time is not None and source_time >= d and as_of-source_time <= timedelta(hours=policy["maximum_source_age_hours"])
    alerts = set()
    if not fresh:
        alerts.add("refresh_source_data")
    if not snapshot["coverage_verified"]:
        alerts.add("audit_source_coverage")
    for metric, key, code, lower in (("prediction_coverage", "minimum_prediction_coverage", "review_prediction_coverage", True),
        ("missing_input_rate", "maximum_missing_rate", "audit_missing_features", False),
        ("unknown_context_rate", "maximum_unknown_rate", "review_unknown_contexts", False),
        ("failure_rate", "maximum_failure_rate", "investigate_calculation_failures", False),
        ("label_coverage", "minimum_label_coverage", "audit_mature_outcomes", True)):
        value = current[metric]
        if value is not None and (value < policy[key] if lower else value > policy[key]):
            alerts.add(code)
    if support and any(value is not None and value > policy["maximum_distribution_tvd"] for value in drift.values()):
        alerts.add("investigate_distribution_shift")
    quality_ready = (support and reference["quality_ready"] and current["quality_ready"]
                     and all(cohort["label_coverage"] is not None and cohort["label_coverage"] >= policy["minimum_label_coverage"] for cohort in (reference, current))
                     and fresh and snapshot["coverage_verified"])
    brier_increase = None
    f1_drop = None
    if task == "p1" and quality_ready:
        f1_drop = reference["metrics"]["primary"] - current["metrics"]["primary"]
        if f1_drop > policy["maximum_f1_drop"]:
            alerts.add("review_reason_classifier")
    if task == "p2" and quality_ready:
        ref, cur = reference["metrics"], current["metrics"]
        if ref["brier"] is not None and cur["brier"] is not None:
            brier_increase = cur["brier"] - ref["brier"]
        if ((brier_increase is not None and brier_increase > policy["maximum_brier_increase"])
                or (cur["ece"] is not None and cur["ece"] > policy["maximum_ece"])):
            alerts.add("review_calibration")
    if not quality_ready:
        alerts.add("insufficient_verified_labels_or_support")
    status = ("insufficient_data" if not support or not quality_ready else "criteria_pending"
              if policy["criteria_status"] != "reviewed" else "review_required" if alerts else "no_threshold_crossing")
    # Canonical ordering makes the evidence fingerprint independent of file row order.
    stable_input = snapshot | {key: sorted(snapshot[key], key=lambda row: row["event_id"]) for key in ("reference", "current")}
    return {"version": VERSION, "purpose": "synthetic", "source": snapshot["source"], "task": task,
        "as_of": as_of.isoformat(), "reference_window": [a.isoformat(), b.isoformat()], "current_window": [c.isoformat(), d.isoformat()],
        "source_verified_at": source_time.isoformat() if source_time is not None else None,
        "source_age_hours": (as_of-source_time).total_seconds()/3600 if source_time is not None else None,
        "coverage_verified": snapshot["coverage_verified"],
        "input_sha256": digest(stable_input), "policy_sha256": digest(policy), "dataset_version": DATASET_VERSION,
        "model_mode": snapshot["model_mode"], "artifact_id": snapshot["artifact_id"],
        "model_feature_schema_sha256": expected, "baseline_protocol_sha256": snapshot["baseline_protocol_sha256"],
        "status": status, "criteria_status": policy["criteria_status"], "quality_ready": quality_ready,
        "reference": reference, "current": current, "distribution_tvd": drift, "brier_increase": brier_increase, "f1_drop": f1_drop,
        "alerts": sorted(alerts), "training_authorized": False, "promotion_authorized": False}


def candidate_request(report: dict, *, report_id: str, candidate_id: str, protocol: Protocol) -> dict:
    """Call only after authenticating/recomputing report. This is a request, not approval."""
    token(report_id)
    if (report.get("version") != VERSION or report.get("purpose") != "synthetic"
            or candidate_id not in TASKS or TASKS[candidate_id] != report["task"]
            or not isinstance(protocol, Protocol) or protocol.task != report["task"]
            or tuple(protocol.expected_sources) != (report["source"],)):
        raise ValueError("Candidato o protocolo de otro ambito")
    if (protocol.fingerprint == report["baseline_protocol_sha256"]
            or protocol.boundaries[3] < instant(report["as_of"]) or protocol.boundaries[4] <= instant(report["as_of"])):
        raise ValueError("Se requiere protocolo nuevo con test futuro reservado")
    definition = recipe(candidate_id, seed=protocol.seed)
    if definition["schema_sha256"] != report["model_feature_schema_sha256"] or candidate_id not in CANDIDATES[protocol.task]:
        raise ValueError("Candidato incompatible")
    data_alerts = {"refresh_source_data", "audit_source_coverage", "audit_mature_outcomes",
                   "audit_missing_features", "investigate_calculation_failures"}
    state = ("blocked_data" if not report["quality_ready"] or data_alerts.intersection(report["alerts"]) else "blocked_criteria"
             if report["criteria_status"] != "reviewed" or protocol.criteria_status != "agreed" else "awaiting_human_review")
    return {"version": REQUEST_VERSION, "purpose": "synthetic", "source": report["source"], "task": report["task"],
        "monitor_report_id": report_id, "candidate_id": candidate_id, "recipe": definition,
        "evaluation_protocol_sha256": protocol.fingerprint, "previous_artifact_id": report["artifact_id"],
        "status": state, "training_authorized": False, "promotion_authorized": False,
        "requirements": ["independent_human_review", "authorized_external_training_and_calibration",
                         "new_reserved_temporal_test", "ml07_evidence", "ml08_independent_approval_and_rollback"]}
