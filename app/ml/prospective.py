"""ML-14 synthetic observational ledger contracts. Never execute or infer causality."""

from collections import Counter
from datetime import timedelta
from uuid import UUID

from app.ml.batch_contract import digest
from app.ml.evaluation_protocol import instant, token
from app.ml.export_snapshot import exact
from app.ml.temporal_dataset import SOURCES

VERSION = "rejection-prospective-v1-draft"
MAX_EVENTS = 2000
CHECK_FIELDS = {"state", "mandate_active", "retry_limit_reached", "links_verified", "settlement_verified", "checked_at", "state_check_sha256"}


def template() -> dict:
    return {"version": VERSION, "purpose": "synthetic", "study_id": None, "source": None,
        "resource_type": "charge", "design": "observational_process_pilot", "enrollment_end": None,
        "horizon_days": 30, "minimum_mature_cases": 30, "minimum_units": 20,
        "minimum_followup_coverage": 0.8, "maximum_state_age_seconds": 3600,
        "criteria_status": "draft", "criteria_reference_sha256": None, "capture_frame_sha256": None}


def protocol(config: dict, *, registered_at: str) -> dict:
    exact(config, set(template()))
    if (config["version"] != VERSION or config["purpose"] != "synthetic" or config["source"] not in SOURCES
            or config["resource_type"] not in {"charge", "payment", "transaction"}
            or config["design"] != "observational_process_pilot" or type(config["horizon_days"]) is not int
            or config["horizon_days"] != 30):
        raise ValueError("Protocolo prospectivo sintetico invalido")
    token(config["study_id"])
    token(config["capture_frame_sha256"])
    registered = instant(registered_at)
    if instant(config["enrollment_end"]) <= registered:
        raise ValueError("La inscripcion debe terminar despues del registro")
    for name in ("minimum_mature_cases", "minimum_units"):
        if type(config[name]) is not int or not 1 <= config[name] <= MAX_EVENTS:
            raise ValueError("Soporte minimo invalido")
    coverage = config["minimum_followup_coverage"]
    if type(coverage) not in {int, float} or not 0 <= coverage <= 1:
        raise ValueError("Cobertura minima invalida")
    if type(config["maximum_state_age_seconds"]) is not int or not 1 <= config["maximum_state_age_seconds"] <= 86400:
        raise ValueError("Vigencia invalida")
    if config["criteria_status"] not in {"draft", "agreed"}:
        raise ValueError("Criterios invalidos")
    if config["criteria_status"] == "agreed":
        token(config["criteria_reference_sha256"])
    elif config["criteria_reference_sha256"] is not None:
        raise ValueError("Borrador sin aprobacion acreditada")
    return config | {"registered_at": registered.isoformat()}


def eligible(payload, at, definition):
    if payload["state"] not in {"rejected", "paid", "cancelled", "unknown"}:
        raise ValueError("Estado no admitido")
    for name in ("mandate_active", "retry_limit_reached"):
        if payload[name] is not None and type(payload[name]) is not bool:
            raise ValueError("Restriccion invalida")
    for name in ("links_verified", "settlement_verified"):
        if type(payload[name]) is not bool:
            raise ValueError("Verificacion invalida")
    token(payload["state_check_sha256"])
    checked = instant(payload["checked_at"])
    if checked > at:
        raise ValueError("Estado futuro")
    return (at-checked <= timedelta(seconds=definition["maximum_state_age_seconds"])
        and payload["state"] == "rejected" and payload["mandate_active"] is True
        and payload["retry_limit_reached"] is False and payload["links_verified"] and payload["settlement_verified"])


def event_record(*, study_id: str, protocol_sha256: str, revision: int, previous_id: str | None,
                 request_id: UUID, actor_id: UUID, kind: str, case_id: str,
                 occurred_at: str, recorded_at: str, payload: dict) -> dict:
    record = {"version": VERSION, "study_id": study_id, "protocol_sha256": protocol_sha256,
        "revision": revision, "previous_id": previous_id, "request_id": str(request_id), "actor_id": str(actor_id),
        "kind": kind, "case_id": case_id, "occurred_at": instant(occurred_at).isoformat(),
        "recorded_at": instant(recorded_at).isoformat(), "payload": payload}
    return record | {"event_id": digest(record)}


def replay(definition: dict, events: list[dict], *, as_of: str):
    """Verify complete signed/exported revision; filter knowledge by server recorded_at."""
    exact(definition, set(template()) | {"registered_at"})
    config = {key: value for key, value in definition.items() if key != "registered_at"}
    if protocol(config, registered_at=definition["registered_at"]) != definition:
        raise ValueError("Protocolo alterado")
    cutoff, start = instant(as_of), instant(definition["registered_at"])
    if cutoff < start or type(events) is not list or len(events) > MAX_EVENTS:
        raise ValueError("Corte o presupuesto invalido")
    if events:
        last_clock = max(instant(row["recorded_at"]) for row in events)
        if last_clock > cutoff:
            replay(definition, events, as_of=last_clock.isoformat())  # Validate future payloads without using them at cutoff.
    cases, visible, requests, enrollments = {}, {}, set(), set()
    previous, last_recorded = None, start
    sha = digest(definition)
    for revision, original in enumerate(events, 1):
        exact(original, {"version", "study_id", "protocol_sha256", "revision", "previous_id", "request_id", "actor_id",
                         "kind", "case_id", "occurred_at", "recorded_at", "payload", "event_id"})
        record = dict(original)
        identifier = record.pop("event_id")
        token(identifier)
        token(record["case_id"])
        for key in ("request_id", "actor_id"):
            if type(record[key]) is not str:
                raise ValueError("Actor o solicitud invalida")
            UUID(record[key])
        occurred, recorded = instant(record["occurred_at"]), instant(record["recorded_at"])
        if (digest(record) != identifier or record["version"] != VERSION or record["study_id"] != definition["study_id"]
                or record["protocol_sha256"] != sha or type(record["revision"]) is not int or record["revision"] != revision or record["previous_id"] != previous
                or record["request_id"] in requests or recorded < last_recorded or not start <= occurred <= recorded):
            raise ValueError("Historial prospectivo inconsistente")
        previous, last_recorded = identifier, recorded
        requests.add(record["request_id"])
        # All signatures/chain links verified, but future-ingested records are not knowledge at cutoff.
        if recorded > cutoff:
            continue
        case_id, kind, payload = record["case_id"], record["kind"], record["payload"]
        if kind == "enrolled":
            exact(payload, CHECK_FIELDS | {"obligation_id", "unit_id"})
            token(payload["obligation_id"])
            token(payload["unit_id"])
            if case_id in cases or payload["obligation_id"] in enrollments or occurred >= instant(definition["enrollment_end"]):
                raise ValueError("Inscripcion duplicada o fuera de ventana")
            if recorded-occurred > timedelta(seconds=definition["maximum_state_age_seconds"]):
                raise ValueError("Inscripcion retrospectiva fuera del presupuesto de captura")
            enrollments.add(payload["obligation_id"])
            cases[case_id] = {"enrolled_at": occurred, "eligible": eligible(payload, occurred, definition),
                             "unit_id": payload["unit_id"], "exposures": [], "decisions": [], "outcomes": []}
        else:
            if case_id not in cases or occurred < cases[case_id]["enrolled_at"]:
                raise ValueError("Evento sin inscripcion prospectiva")
            case = cases[case_id]
            if kind == "exposed":
                exact(payload, {"recommendation_id", "input_sha256", "bundle_sha256", "content_sha256", "analysis_as_of", "display_id"})
                for key in ("recommendation_id", "input_sha256", "bundle_sha256", "content_sha256", "display_id"):
                    token(payload[key])
                if instant(payload["analysis_as_of"]) > occurred or any(
                        visible[event_id]["payload"]["display_id"] == payload["display_id"] for event_id in case["exposures"]):
                    raise ValueError("Exposicion futura o repetida")
                case["exposures"].append(identifier)
            elif kind == "decision":
                exact(payload, CHECK_FIELDS | {"choice", "exposure_event_id", "supersedes"})
                exposure = visible.get(payload["exposure_event_id"])
                if payload["exposure_event_id"] is not None and (exposure is None or exposure["kind"] != "exposed"
                        or exposure["case_id"] != case_id or instant(exposure["occurred_at"]) > occurred):
                    raise ValueError("Decision vinculada a otra exposicion")
                if payload["supersedes"] != (case["decisions"][-1] if case["decisions"] else None):
                    raise ValueError("La decision debe corregir su ultima revision")
                if payload["choice"] not in {"refer_existing_workflow", "defer", "dismiss", "needs_review"}:
                    raise ValueError("Decision no admitida")
                allowed = eligible(payload, occurred, definition)
                if payload["choice"] == "refer_existing_workflow" and (not case["eligible"] or not allowed):
                    raise ValueError("No derivar gestion con estado/restricciones sin verificar")
                if case["decisions"] and occurred < instant(visible[case["decisions"][-1]]["occurred_at"]):
                    raise ValueError("Correccion de decision anterior a su revision")
                case["decisions"].append(identifier)
            elif kind == "outcome":
                exact(payload, {"status", "assessment_at", "coverage_through", "link_verified", "evidence_sha256", "payment_at", "supersedes"})
                deadline = case["enrolled_at"] + timedelta(days=30)
                assessed = instant(payload["assessment_at"])
                if not case["enrolled_at"] <= assessed <= min(deadline, occurred):
                    raise ValueError("Resultado fuera del horizonte objetivo")
                if payload["status"] not in {"full_net_payment", "unpaid", "partial", "reversed", "unknown"} or type(payload["link_verified"]) is not bool:
                    raise ValueError("Resultado invalido")
                if payload["evidence_sha256"] is not None:
                    token(payload["evidence_sha256"])
                if payload["coverage_through"] is not None and instant(payload["coverage_through"]) > occurred:
                    raise ValueError("Cobertura futura")
                if payload["payment_at"] is not None and not case["enrolled_at"] <= instant(payload["payment_at"]) <= assessed:
                    raise ValueError("Pago fuera de la ventana declarada")
                if payload["status"] in {"unpaid", "unknown"} and payload["payment_at"] is not None:
                    raise ValueError("Estado y pago contradictorios")
                if payload["status"] == "unpaid" and assessed != deadline:
                    raise ValueError("Un negativo no puede cerrarse antes de treinta dias")
                if payload["supersedes"] != (case["outcomes"][-1] if case["outcomes"] else None):
                    raise ValueError("El resultado debe corregir su ultima revision")
                if case["outcomes"] and (assessed < instant(visible[case["outcomes"][-1]]["payload"]["assessment_at"])
                        or occurred < instant(visible[case["outcomes"][-1]]["occurred_at"])):
                    raise ValueError("Correccion de resultado retrocede el reloj")
                case["outcomes"].append(identifier)
            else:
                raise ValueError("Tipo de evento no admitido")
        visible[identifier] = record
    return cases, visible


def measure(definition: dict, events: list[dict], *, as_of: str) -> dict:
    cases, visible = replay(definition, events, as_of=as_of)
    cutoff = instant(as_of)
    counts = Counter({name: 0 for name in ("screened", "eligible", "ineligible", "exposed_cases", "exposure_events",
        "decision_events", "without_decision", "eligible_exposed", "eligible_with_decision", "immature_eligible",
        "mature_eligible", "verified_paid", "verified_unpaid")})
    counts.update(screened=len(cases), eligible=sum(case["eligible"] for case in cases.values()))
    exclusions, decisions, mature_units, verified_units = Counter(), Counter(), set(), set()
    for case in cases.values():
        counts["exposed_cases"] += bool(case["exposures"])
        counts["exposure_events"] += len(case["exposures"])
        counts["decision_events"] += len(case["decisions"])
        if case["decisions"]:
            decisions[visible[case["decisions"][-1]]["payload"]["choice"]] += 1
        else:
            counts["without_decision"] += 1
        if not case["eligible"]:
            counts["ineligible"] += 1
            continue
        counts["eligible_exposed"] += bool(case["exposures"])
        counts["eligible_with_decision"] += bool(case["decisions"])
        deadline = case["enrolled_at"]+timedelta(days=30)
        if deadline > cutoff:
            counts["immature_eligible"] += 1
            continue
        counts["mature_eligible"] += 1
        mature_units.add(case["unit_id"])
        outcome = visible[case["outcomes"][-1]]["payload"] if case["outcomes"] else None
        if outcome is None:
            exclusions["no_followup"] += 1
        elif instant(outcome["assessment_at"]) != deadline:
            exclusions["horizon_assessment_pending"] += 1
        elif (not outcome["link_verified"] or outcome["evidence_sha256"] is None or outcome["coverage_through"] is None
              or instant(outcome["coverage_through"]) < deadline):
            exclusions["unverified_link_or_coverage"] += 1
        elif outcome["status"] == "unpaid":
            counts["verified_unpaid"] += 1
            verified_units.add(case["unit_id"])
        elif outcome["status"] == "full_net_payment" and outcome["payment_at"] is not None:
            counts["verified_paid"] += 1
            verified_units.add(case["unit_id"])
        else:
            exclusions["partial_reversed_or_unknown"] += 1
    verified = counts["verified_paid"]+counts["verified_unpaid"]
    coverage = verified/counts["mature_eligible"] if counts["mature_eligible"] else None
    complete = (verified >= definition["minimum_mature_cases"] and len(verified_units) >= definition["minimum_units"]
                and coverage is not None and coverage >= definition["minimum_followup_coverage"])
    return {"version": VERSION, "purpose": "synthetic", "study_id": definition["study_id"], "source": definition["source"],
        "resource_type": definition["resource_type"], "protocol_sha256": digest(definition), "ledger_sha256": digest(events),
        "ledger_revision": len(events), "included_events": len(visible), "as_of": cutoff.isoformat(),
        "design": definition["design"], "denominator": "registered_eligible_cases",
        "counts": dict(sorted(counts.items())), "latest_decisions": dict(sorted(decisions.items())),
        "excluded_mature_outcomes": dict(sorted(exclusions.items())), "distinct_mature_units": len(mature_units),
        "distinct_verified_units": len(verified_units),
        "exposure_coverage": counts["eligible_exposed"]/counts["eligible"] if counts["eligible"] else None,
        "decision_coverage": counts["eligible_with_decision"]/counts["eligible"] if counts["eligible"] else None,
        "verified_mature_outcomes": verified, "followup_coverage": coverage,
        "recovery_rate_denominator": "verified_mature_outcomes",
        "mature_recovery_bounds": ([counts["verified_paid"]/counts["mature_eligible"],
            (counts["verified_paid"]+counts["mature_eligible"]-verified)/counts["mature_eligible"]]
            if counts["mature_eligible"] else None),
        "observed_recovery_rate": counts["verified_paid"]/verified if verified else None,
        "status": "insufficient_followup" if not complete else "criteria_pending" if definition["criteria_status"] != "agreed" else "descriptive_only",
        "causal_effect": None, "causal_comparison": None, "workflow_execution_confirmed": False,
        "execution_authorized": False, "training_authorized": False, "promotion_authorized": False}
