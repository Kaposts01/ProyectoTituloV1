"""Real JWT/CSRF/RBAC and PostgreSQL with synthetic users/data; no app lifespan."""

from dataclasses import dataclass, field, replace
from importlib.util import module_from_spec, spec_from_file_location
from itertools import count
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from test_ml_artifacts import SECRET, fixture_artifact
from test_ml_batch_contract import snapshot
from test_ml_batches import FACTORY, ON, batch, resolve

from app.api.v1.router import api_router
from app.api.v1.routes import ml
from app.core.config import Settings, settings
from app.core.security import ACCESS_COOKIE, create_access_token, get_db
from app.db.session import engine
from app.ml import export_files, recommendation
from app.ml.artifacts import verify_artifact
from app.models.auth import Permission, Role, User
from app.models.ml_artifact import MlArtifactRelease
from app.models.rejection_annotation import RejectionReasonLabelRevision
from app.services import ml_batches, rbac
from app.services.ml_artifacts import register_artifact
from app.services.ml_permissions import ML_PERMISSIONS, required_permissions

SERIALS = count(500)


@dataclass(frozen=True)
class Identity:
    user: User
    token: str = field(repr=False)
    csrf: str = field(repr=False)

    def __getitem__(self, index):
        return (self.user, self.token, self.csrf)[index]


def actor(codes=(), *, active=True):
    with Session(engine, expire_on_commit=False) as db, db.begin():
        permissions = []
        for code in codes:
            value = db.scalar(select(Permission).where(Permission.code == code))
            if value is None:
                value = Permission(code=code, description="Synthetic permission")
                db.add(value)
                db.flush()
            permissions.append(value)
        user = User(username=f"ml-api-{uuid4()}", password_hash="not-a-login", is_active=active,
                    roles=[Role(name=f"ml-api-role-{uuid4()}", permissions=permissions)])
        db.add(user)
        db.flush()
    token, csrf = create_access_token(user)
    return Identity(user, token, csrf)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "ml_rejections_api_enabled", True)
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    def db():
        with factory() as session:
            yield session
    def forbidden(*args, **kwargs):
        raise AssertionError("No provider network, worker or inference in ML API")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(recommendation, "recommend", forbidden)
    app = FastAPI()
    app.state.ml_factory = factory
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = db
    # No main lifespan, scheduler, cleanup or production connection.
    browser = TestClient(app)
    try:
        yield browser
    finally:
        browser.close()
        transaction.rollback()
        connection.close()


def call(client, method, path, identity=None, body=None, *, csrf=True):
    client.cookies.clear()
    headers = {}
    if identity:
        client.cookies.set(ACCESS_COOKIE, identity[1])
        if csrf:
            headers["X-CSRF-Token"] = identity[2]
    return client.request(method, f"/api/v1/ml{path}", json=body, headers=headers)


def label_body(**overrides):
    value = dict(synthetic=True, request_id=str(uuid4()), processor="bank-12", code="1001",
                 normalized_text="Sin fondos", privacy_reviewed=True, category="FUNDS", severity="temporary")
    value.update(overrides)
    return value


def review_body(**overrides):
    value = dict(synthetic=True, request_id=str(uuid4()), expected_revision=1, decision="approved",
                 category="FUNDS", severity="temporary", rationale="independent_review")
    value.update(overrides)
    return value


def label_path(source="tch", resource="charge"):
    return f"/{source}/{resource}/labels"


def test_authentication_uses_real_session_active_user_and_revocation(client):
    path = "/tch/charge/results"
    assert call(client, "GET", path).status_code == 401
    inactive = actor(required_permissions("ml.rejections.read", "tch", "charge"), active=False)
    assert call(client, "GET", path, inactive).status_code == 401
    user = actor(required_permissions("ml.rejections.read", "tch", "charge"))
    assert call(client, "GET", path, user).status_code == 200
    with Session(engine) as db, db.begin():
        db.get(User, user[0].id).token_version += 1
    assert call(client, "GET", path, user).status_code == 401


@pytest.mark.parametrize("source", ["virtualpos1", "virtualpos2", "toku", "payku", "tch"])
@pytest.mark.parametrize("resource", ["charge", "payment", "transaction", "subscription_state"])
def test_resource_matrix_requires_ml_account_and_existing_channel_permission(client, source, resource):
    required = required_permissions("ml.labels.read", source, resource)
    full = actor(required)
    path = f"{label_path(source, resource)}/{uuid4()}"
    assert call(client, "GET", path, full).status_code == 404
    for missing in sorted(required):
        incomplete = actor(required - {missing})
        response = call(client, "GET", path, incomplete)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "permission_denied"


def test_api_flag_is_off_by_default_and_no_ml_table_is_read_when_disabled(client, monkeypatch):
    assert Settings.model_fields["ml_rejections_api_enabled"].default is False
    user = actor(required_permissions("ml.rejections.read", "tch", "charge"))
    monkeypatch.setattr(settings, "ml_rejections_api_enabled", False)
    monkeypatch.setattr(ml, "result_query", lambda *args: pytest.fail("Disabled ML must not read results"))
    response = call(client, "GET", "/tch/charge/results", user)
    assert response.status_code == 503 and response.json()["detail"]["code"] == "ml_api_disabled"


def test_synthetic_database_guard_rejects_operational_name_without_using_one():
    class FakeDb:
        def scalar(self, statement):
            return "crm_qa_local_20261118"
    previous = settings.ml_rejections_api_enabled
    try:
        settings.ml_rejections_api_enabled = True
        with pytest.raises(ml.HTTPException) as exc:
            ml.synthetic_api(None, FakeDb())
        assert exc.value.status_code == 503
    finally:
        settings.ml_rejections_api_enabled = previous


def test_label_writes_require_csrf_and_reject_client_selected_actor_or_path(client):
    user = actor(required_permissions("ml.labels.propose", "tch", "charge"))
    payload = label_body()
    assert call(client, "POST", label_path(), user, payload, csrf=False).status_code == 403
    client.cookies.set(ACCESS_COOKIE, user[1])
    response = client.post("/api/v1/ml/tch/charge/labels", json=payload, headers={"X-CSRF-Token": "wrong"})
    assert response.status_code == 403
    for extra_name in ("actor_id", "manifest_relative", "api_key"):
        response = call(client, "POST", label_path(), user, payload | {extra_name: "sensitive-value-never-echo"})
        assert response.status_code == 422 and "sensitive-value-never-echo" not in response.text
    for value in (False, 1, "true"):
        assert call(client, "POST", label_path(), user, payload | {"synthetic": value}).status_code == 422
    response = call(client, "POST", label_path(), user, payload | {"sensitive-extra-field-name": "value"})
    assert response.status_code == 422 and "sensitive-extra-field-name" not in response.text


def test_review_permission_cannot_be_replaced_by_propose_permission(client):
    author = actor(required_permissions("ml.labels.propose", "tch", "charge"))
    reviewer = actor(required_permissions("ml.labels.review", "tch", "charge"))
    proposal = call(client, "POST", label_path(), author, label_body(code=str(uuid4().int % 900000 + 10000)))
    path = f"{label_path()}/{proposal.json()['label_id']}/revisions"
    assert call(client, "POST", path, author, review_body()).status_code == 403
    assert call(client, "POST", path, reviewer, review_body(decision="draft", rationale="correction")).status_code == 403
    assert call(client, "POST", path, reviewer, review_body()).status_code == 200


def test_permissions_are_rechecked_after_role_change_with_same_jwt(client):
    identity = actor(required_permissions("ml.rejections.read", "tch", "charge"))
    assert call(client, "GET", "/tch/charge/results", identity).status_code == 200
    with Session(engine) as db, db.begin():
        role = db.get(User, identity[0].id).roles[0]
        role.permissions = [permission for permission in role.permissions if permission.code != "tch.transacciones.view"]
    assert call(client, "GET", "/tch/charge/results", identity).status_code == 403


def test_label_revision_lifecycle_actor_idempotence_and_latest_not_old_approval(client):
    codes = set().union(*(required_permissions(code, "tch", "charge") for code in (
        "ml.labels.read", "ml.labels.propose", "ml.labels.review")))
    author, reviewer = actor(codes), actor(codes)
    payload = label_body(code=str(uuid4().int % 900000 + 10000))
    proposal = call(client, "POST", label_path(), author, payload)
    assert proposal.status_code == 200, proposal.text
    event = proposal.json()
    assert event["actor_id"] == str(author[0].id) and event["revision"] == 1
    assert call(client, "POST", label_path(), author, payload).json() == event
    path = f"{label_path()}/{event['label_id']}"
    body = review_body()
    assert call(client, "POST", path+"/revisions", author, body).status_code == 409
    assert call(client, "POST", path+"/revisions", reviewer, body, csrf=False).status_code == 403
    approval = call(client, "POST", path+"/revisions", reviewer, body)
    assert approval.status_code == 200, approval.text
    assert approval.json()["actor_id"] == str(reviewer[0].id)
    stale = call(client, "POST", path+"/revisions", reviewer, review_body())
    assert stale.status_code == 409
    correction = review_body(expected_revision=2, decision="draft", rationale="correction")
    assert call(client, "POST", path+"/revisions", author, correction).status_code == 200
    current = call(client, "GET", path, reviewer)
    assert current.status_code == 200 and current.json()["latest"]["decision"] == "draft"
    assert [r["revision"] for r in current.json()["history"]] == [1, 2, 3]
    withdrawal = review_body(expected_revision=3, decision="withdrawn", category=None, severity="unknown", rationale="withdrawal")
    assert call(client, "POST", path+"/revisions", reviewer, withdrawal).status_code == 200
    assert call(client, "GET", path, reviewer).json()["latest"]["decision"] == "withdrawn"
    page = call(client, "GET", label_path()+"?limit=1", reviewer)
    assert page.status_code == 200 and len(page.json()) == 1
    assert page.json()[0]["latest"]["decision"] == "withdrawn" and page.json()[0]["history"] == []


def test_same_provider_account_and_other_resource_ids_are_not_interchangeable(client):
    codes = set().union(*(required_permissions(code, source, resource)
        for code in ("ml.labels.read", "ml.labels.propose") for source in ("virtualpos1", "virtualpos2")
        for resource in ("charge", "payment")))
    user = actor(codes)
    response = call(client, "POST", label_path("virtualpos1"), user, label_body(code="-4", normalized_text=""))
    label_id = response.json()["label_id"]
    assert call(client, "GET", f"{label_path('virtualpos2')}/{label_id}", user).status_code == 404
    assert call(client, "GET", f"{label_path('virtualpos1', 'payment')}/{label_id}", user).status_code == 404
    limited = actor(required_permissions("ml.labels.read", "virtualpos1", "charge"))
    assert call(client, "GET", f"{label_path('virtualpos2')}/{label_id}", limited).status_code == 403


def test_invalid_context_privacy_pii_and_revision_errors_are_sanitized(client):
    user = actor(required_permissions("ml.labels.propose", "tch", "charge"))
    for values in ({"privacy_reviewed": False}, {"normalized_text": "secret-person@example.invalid"}, {"processor": "../../secret"}):
        response = call(client, "POST", label_path(), user, label_body(**values))
        assert response.status_code == 422
        assert "example.invalid" not in response.text and "../../secret" not in response.text


def test_results_are_resource_filtered_and_get_does_not_compute_or_dispatch(client, monkeypatch):
    identity, rows = batch()
    claim = ml_batches.claim_next(FACTORY, identity, **ON)
    # client fixture forbids recommend: only the pre-existing worker may create fixtures.
    monkeypatch.setattr(ml_batches, "recommend", lambda row, **kwargs: recommendation_saved(row, **kwargs))
    assert ml_batches.process_claim(FACTORY, claim, resolve(rows), **ON) == "succeeded"
    monkeypatch.setattr(ml_batches, "process_next", lambda *args, **kwargs: pytest.fail("GET must not dispatch"))
    user = actor(set().union(*(required_permissions("ml.rejections.read", "tch", r) for r in ("charge", "payment"))))
    with Session(engine) as db:
        before = db.scalar(select(func.count()).select_from(RejectionReasonLabelRevision))
    response = call(client, "GET", "/tch/charge/results?limit=1", user)
    assert response.status_code == 200 and len(response.json()) == 1
    result = response.json()[0]
    assert result["purpose"] == "synthetic" and result["recovery_probability"] is None and result["execution_allowed"] is False
    assert result["rules_state"] == result["classification_state"]
    assert result["severity"] in {"temporary", "permanent", "unknown"} and isinstance(result["matched_rules"], list)
    assert "input_sha256" not in result and "normalized_text" not in result
    result_id = db_result_id(identity)
    assert call(client, "GET", f"/tch/charge/results/{result_id}", user).status_code == 200
    assert call(client, "GET", f"/tch/payment/results/{result_id}", user).status_code == 404
    assert call(client, "GET", f"/tch/payment/batches/{identity}", user).status_code == 404
    detail = call(client, "GET", f"/tch/charge/batches/{identity}", user)
    assert detail.json()["total"] == 1 and detail.json()["states"] == {"succeeded": 1}
    assert response.headers["cache-control"] == "no-store"
    assert call(client, "GET", "/tch/charge/results?limit=101", user).status_code == 422
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(RejectionReasonLabelRevision)) == before


def test_mixed_batch_only_exposes_counts_of_authorized_resource(client):
    charge = snapshot(uuid4().int % 10**12, source="toku")
    payment = replace(charge, resource_type="payment")
    identity, _ = batch((charge, payment), source="toku")
    user = actor(required_permissions("ml.rejections.read", "toku", "charge"))
    response = call(client, "GET", f"/toku/charge/batches/{identity}", user)
    assert response.status_code == 200 and response.json()["total"] == 1
    assert response.json()["states"] == {"queued": 1}
    assert call(client, "GET", f"/toku/payment/batches/{identity}", user).status_code == 403


recommendation_saved = recommendation.recommend


def db_result_id(identity):
    from app.models.ml_batch import MlBatchItem
    with Session(engine) as db:
        return db.get(MlBatchItem, (identity, 0)).result_id


@pytest.fixture
def registered(client, monkeypatch, tmp_path):
    monkeypatch.setattr(export_files, "_permissions", lambda *args, **kwargs: None)
    scopes = set().union(*(required_permissions(code, "virtualpos1") for code in (
        "ml.artifacts.read", "ml.artifacts.review", "ml.artifacts.simulate")))
    author, reviewer = actor(scopes), actor(scopes)
    root = tmp_path / "private"
    artifact = fixture_artifact(root, serial=next(SERIALS))
    factory = client.app.state.ml_factory
    revision = current_revision("p2", "virtualpos1", factory)
    with factory() as db, db.begin():
        register_artifact(db, artifact, actor=author[0].id, expected_revision=revision)
    checked = []
    def checker(row):
        checked.append(row.id)
        return verify_artifact(root, row.manifest_relative, secret=SECRET)
    client.app.dependency_overrides[ml.artifact_verifier] = lambda: checker
    return artifact, author, reviewer, checked, root


def current_revision(task, source, factory=FACTORY):
    with factory() as db:
        row = db.get(MlArtifactRelease, (task, source))
        return row.revision if row else 0


def test_artifact_metadata_get_never_opens_files_and_needs_all_scope_resources(client, registered):
    artifact, author, _, checked, _ = registered
    response = call(client, "GET", f"/virtualpos1/artifacts/{artifact.artifact_id}", author)
    assert response.status_code == 200 and not checked
    assert "payload" not in response.text and "manifest_relative" not in response.text
    incomplete = actor(required_permissions("ml.artifacts.read", "virtualpos1") - {"virtualpos.payments.view"})
    assert call(client, "GET", f"/virtualpos1/artifacts/{artifact.artifact_id}", incomplete).status_code == 403


def test_artifact_review_simulation_csrf_independent_actor_and_corrupt_bytes(client, registered):
    artifact, author, reviewer, checked, root = registered
    path = f"/virtualpos1/artifacts/{artifact.artifact_id}/approval"
    revision = current_revision("p2", "virtualpos1", client.app.state.ml_factory)
    body = {"synthetic": True, "expected_revision": revision, "approval_sha256": "a"*64}
    assert call(client, "POST", path, reviewer, body, csrf=False).status_code == 403
    assert not checked
    assert call(client, "POST", path, author, body).status_code == 409
    assert call(client, "POST", path, reviewer, body).status_code == 200
    assert checked
    release_path = "/virtualpos1/releases/p2/simulation"
    release = body | {"expected_revision": revision+1, "action": "promoted", "target_id": artifact.artifact_id}
    assert call(client, "POST", release_path, reviewer, release, csrf=False).status_code == 403
    response = call(client, "POST", release_path, reviewer, release)
    assert response.status_code == 200 and response.json()["simulation"] is True
    assert response.json()["active_artifact_id"] == artifact.artifact_id
    assert call(client, "POST", release_path, reviewer, release).status_code == 409
    (root / artifact.descriptor["payload"]["path"]).write_bytes(b"corrupted-synthetic-payload")
    disable = release | {"expected_revision": revision+2, "action": "disabled", "target_id": None}
    response = call(client, "POST", release_path, reviewer, disable)
    assert response.status_code == 409 and "payload" not in response.text
    assert current_revision("p2", "virtualpos1", client.app.state.ml_factory) == revision+2


def test_artifact_authorization_and_scope_fail_before_private_file_access(client, registered):
    artifact, _, reviewer, checked, _ = registered
    body = {"synthetic": True, "expected_revision": 0, "approval_sha256": "a"*64}
    outsider = actor(required_permissions("ml.artifacts.review", "virtualpos2"))
    response = call(client, "POST", f"/virtualpos2/artifacts/{artifact.artifact_id}/approval", outsider, body)
    assert response.status_code == 404 and not checked
    only_read = actor(required_permissions("ml.artifacts.read", "virtualpos1"))
    response = call(client, "POST", f"/virtualpos1/artifacts/{artifact.artifact_id}/approval", only_read, body)
    assert response.status_code == 403 and not checked
    assert call(client, "GET", "/virtualpos1/releases/p2/simulation", reviewer).status_code == 405
    assert call(client, "POST", "/train", reviewer, {}).status_code == 404
    assert call(client, "POST", "/virtualpos1/releases/p2/activate", reviewer, {}).status_code == 404


def test_simulated_publish_rollback_disable_and_wrong_task(client, registered):
    artifact, _, reviewer, _, _ = registered
    revision = current_revision("p2", "virtualpos1", client.app.state.ml_factory)
    body = {"synthetic": True, "expected_revision": revision, "approval_sha256": "a"*64}
    assert call(client, "POST", f"/virtualpos1/artifacts/{artifact.artifact_id}/approval", reviewer, body).status_code == 200
    release = body | {"expected_revision": revision+1, "action": "promoted", "target_id": artifact.artifact_id}
    assert call(client, "POST", "/virtualpos1/releases/p1/simulation", reviewer, release).status_code == 404
    assert call(client, "POST", "/virtualpos1/releases/p2/simulation", reviewer, release).status_code == 200
    rollback = release | {"expected_revision": revision+2, "action": "rolled_back"}
    assert call(client, "POST", "/virtualpos1/releases/p2/simulation", reviewer, rollback).status_code == 200
    disable = release | {"expected_revision": revision+3, "action": "disabled", "target_id": None}
    response = call(client, "POST", "/virtualpos1/releases/p2/simulation", reviewer, disable)
    assert response.status_code == 200 and response.json()["active_artifact_id"] is None
    current = call(client, "GET", "/virtualpos1/releases/p2", reviewer)
    assert current.status_code == 200 and current.json()["revision"] == revision+4


def test_real_artifact_metadata_is_rejected_without_opening_any_file(client, registered):
    _, author, _, checked, _ = registered
    from app.models.ml_artifact import MlArtifact
    identity = uuid4().hex * 2
    with client.app.state.ml_factory() as db, db.begin():
        # Inert metadata sentinel, NOT a real model or a verified artifact.
        db.add(MlArtifact(id=identity, source="virtualpos1", task="p2", created_by=author[0].id,
                         manifest_relative="never-open", manifest_sha256="f"*64,
                         descriptor={"purpose": "reviewed-real"}))
    response = call(client, "GET", f"/virtualpos1/artifacts/{identity}", author)
    assert response.status_code == 409 and not checked


def test_bad_verification_never_advances_registry_revision(client, registered):
    artifact, _, reviewer, _, _ = registered
    revision = current_revision("p2", "virtualpos1", client.app.state.ml_factory)
    client.app.dependency_overrides[ml.artifact_verifier] = lambda: lambda row: replace(artifact, compatible=False)
    body = {"synthetic": True, "expected_revision": revision, "approval_sha256": "a"*64}
    response = call(client, "POST", f"/virtualpos1/artifacts/{artifact.artifact_id}/approval", reviewer, body)
    assert response.status_code == 409
    assert current_revision("p2", "virtualpos1", client.app.state.ml_factory) == revision


def test_storage_error_hides_sql_credentials_and_input(client, monkeypatch):
    user = actor(required_permissions("ml.rejections.read", "tch", "charge"))
    def broken(*args):
        raise SQLAlchemyError("sensitive-sql-secret-path")
    monkeypatch.setattr(ml, "result_query", broken)
    response = call(client, "GET", "/tch/charge/results", user)
    assert response.status_code == 503 and "sensitive-sql-secret-path" not in response.text


def test_permissions_seed_no_automatic_executive_grant_and_downgrade_preserves_assignments():
    assert ML_PERMISSIONS.keys() <= rbac.PERMISSIONS.keys()
    assert not (set(ML_PERMISSIONS) & rbac.executive_permission_codes())
    assert not (set(ML_PERMISSIONS) & rbac.support_permission_codes())
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261125_0086_ml_api_permissions.py"
    spec = spec_from_file_location("ml_api_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.PERMISSIONS == ML_PERMISSIONS
    actor({"ml.labels.read"})
    with Session(engine) as db:
        module.op = Operations(MigrationContext.configure(db.connection()))
        with pytest.raises(RuntimeError, match="Downgrade blocked"):
            module.downgrade()
