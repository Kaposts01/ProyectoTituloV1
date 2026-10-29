"""D21: usuario temporal para capturas en el sandbox (scripts/sandbox/ephemeral_user.py).

Las funciones reciben la sesion/fabrica inyectada: aqui corren contra `crm_test`. El modulo NO toca el entorno al
importarse (solo `main()` fija APP_ENV=sandbox), asi que importarlo no contamina la suite.
"""

import importlib.util
import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.core.security import verify_password
from app.db.session import SessionLocal
from app.models.auth import Role, User

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sandbox" / "ephemeral_user.py"


def _load():
    spec = importlib.util.spec_from_file_location("ephemeral_user_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


eu = _load()


@pytest.fixture(autouse=True)
def _clean_before_and_after():
    db = SessionLocal()
    try:
        eu.cleanup_users(db)
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        eu.cleanup_users(db)
        db.commit()
    finally:
        db.close()


def _pw_users(db) -> list[User]:
    return list(db.scalars(select(User).where(User.username.like("PW-%"))))


def test_importing_the_module_does_not_touch_the_environment() -> None:
    assert os.environ.get("APP_ENV") != "sandbox"


@pytest.mark.parametrize("name", ["crm", "crm_test", "crm_qa", "", None, "postgres", "CRM"])
def test_guard_rejects_production_test_and_non_sandbox_databases(name) -> None:
    with pytest.raises(SystemExit):
        eu.guard_database(name)


def test_guard_accepts_only_sandbox_database() -> None:
    assert eu.guard_database("crm_sandbox") == "crm_sandbox"


def test_create_default_role_is_ejecutivo_with_app_hash_and_random_password() -> None:
    db = SessionLocal()
    try:
        username, password = eu.create_user(db)
        db.commit()
        user = db.scalar(select(User).where(User.username == username))
        assert username.startswith("PW-") and len(username) >= 11
        assert [r.name for r in user.roles] == ["ejecutivo"]
        assert user.is_active and verify_password(password, user.password_hash)
        assert len(password) >= 24 and password not in user.password_hash
        other_user, other_password = eu.create_user(db)
        assert other_user != username and other_password != password
    finally:
        db.close()


def test_role_rules_soporte_explicit_admin_needs_confirmation() -> None:
    db = SessionLocal()
    try:
        username, _ = eu.create_user(db, "soporte")
        db.flush()
        assert [r.name for r in db.scalar(select(User).where(User.username == username)).roles] == ["soporte"]
        with pytest.raises(SystemExit):
            eu.create_user(db, "admin")  # sin i_know
        with pytest.raises(SystemExit):
            eu.create_user(db, "coordinador", i_know=True)  # rol no permitido
        if db.scalar(select(Role).where(Role.name == "admin")) is not None:
            u, _ = eu.create_user(db, "admin", i_know=True)
            db.flush()
            assert [r.name for r in db.scalar(select(User).where(User.username == u)).roles] == ["admin"]
        db.commit()
    finally:
        db.close()


def test_cleanup_removes_only_pw_users_and_their_role_links() -> None:
    db = SessionLocal()
    try:
        keep = f"keep-{uuid.uuid4().hex[:6]}"
        db.add(User(username=keep, password_hash="x", is_active=True))
        a, _ = eu.create_user(db)
        b, _ = eu.create_user(db, "soporte")
        db.commit()
        ids = [u.id for u in _pw_users(db)]
        assert len(ids) == 2
        assert eu.cleanup_users(db) == 2
        db.commit()
        assert _pw_users(db) == []
        assert db.scalar(select(User).where(User.username == keep)) is not None
        left = db.execute(text("select count(*) from user_roles where user_id = any(:ids)"), {"ids": ids}).scalar()
        assert left == 0
        assert a != b
        db.execute(text("delete from users where username = :u"), {"u": keep})
        db.commit()
    finally:
        db.close()


def test_password_is_never_printed_and_reaches_child_only_through_env(capsys) -> None:
    script = (
        "import os,sys\n"
        "u=os.environ.get('PW_USER','');p=os.environ.get('PW_PASS','')\n"
        "sys.exit(0 if u.startswith('PW-') and len(p)>=24 else 9)\n"
    )
    argv = [sys.executable, "-c", script]
    seen_argv: list[list[str]] = []
    real_run = eu.subprocess.run

    def spy(cmd, **kwargs):
        seen_argv.append(list(cmd))
        seen_argv.append([kwargs["env"]["PW_PASS"]])  # solo para comprobar que NO esta en argv
        return real_run(cmd, **kwargs)

    eu.subprocess.run = spy
    try:
        code = eu.run_session(SessionLocal, argv, "ejecutivo", False)
    finally:
        eu.subprocess.run = real_run
    out = capsys.readouterr()
    password = seen_argv[1][0]
    assert code == 0
    assert password not in out.out and password not in out.err
    assert password not in " ".join(seen_argv[0])


def test_session_deletes_user_even_when_child_fails() -> None:
    code = eu.run_session(SessionLocal, [sys.executable, "-c", "import sys; sys.exit(3)"], "ejecutivo", False)
    assert code == 3
    db = SessionLocal()
    try:
        assert _pw_users(db) == []
    finally:
        db.close()


def test_session_deletes_user_when_interrupted_or_runner_crashes() -> None:
    real_run = eu.subprocess.run

    def boom(*_a, **_k):
        raise KeyboardInterrupt

    eu.subprocess.run = boom
    try:
        with pytest.raises(KeyboardInterrupt):
            eu.run_session(SessionLocal, ["no-importa"], "ejecutivo", False)
    finally:
        eu.subprocess.run = real_run
    db = SessionLocal()
    try:
        assert _pw_users(db) == []
    finally:
        db.close()


def test_session_user_exists_while_child_runs() -> None:
    script = (
        "import os,sys\n"
        "sys.exit(0 if os.environ.get('PW_USER','').startswith('PW-') else 9)\n"
    )
    seen: list[int] = []
    real_run = eu.subprocess.run

    def spy(cmd, **kwargs):
        db = SessionLocal()
        try:
            seen.append(len(_pw_users(db)))
        finally:
            db.close()
        return real_run(cmd, **kwargs)

    eu.subprocess.run = spy
    try:
        assert eu.run_session(SessionLocal, [sys.executable, "-c", script], "ejecutivo", False) == 0
    finally:
        eu.subprocess.run = real_run
    assert seen == [1]
