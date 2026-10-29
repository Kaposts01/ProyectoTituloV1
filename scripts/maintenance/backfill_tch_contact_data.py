"""Complete TCH contacts and peso equivalents from existing raw report payloads."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.tch import TchClient, TchSubscription


def _value(payload: dict, leaf: str) -> str | None:
    for key, value in payload.items():
        key_text = str(key).lower()
        if "contacto" in key_text and leaf in key_text and value not in (None, "", "nan", "NaT"):
            return str(value).strip() or None
    return None


def _amount(payload: dict) -> str | None:
    for key, value in payload.items():
        if "equivalente en pesos" not in str(key).lower() or value in (None, "", "nan", "NaT"):
            continue
        try:
            return str(int(float(str(value).replace("$", "").replace(".", "").replace(",", "."))))
        except ValueError:
            return None
    return None


def main() -> None:
    db = SessionLocal()
    try:
        clients = {client.rut: client for client in db.scalars(select(TchClient)).all()}
        updated_clients = 0
        updated_subscriptions = 0
        subscriptions = db.scalars(select(TchSubscription).order_by(TchSubscription.updated_at.desc())).all()
        for subscription in subscriptions:
            payload = subscription.raw_payload or {}
            equivalent = _amount(payload)
            if equivalent and not subscription.peso_equivalent:
                subscription.peso_equivalent = equivalent
                updated_subscriptions += 1

            client = clients.get(subscription.client_rut or "")
            if client is None:
                continue
            address = " ".join(
                value
                for value in (
                    _value(payload, "direccion"),
                    _value(payload, "numero"),
                    _value(payload, "casa") or _value(payload, "depto"),
                    _value(payload, "villa") or _value(payload, "pob"),
                )
                if value
            ) or None
            fields = {
                "phone": _value(payload, "telefono"),
                "email": _value(payload, "email"),
                "address": address,
                "district": _value(payload, "comuna"),
                "city": _value(payload, "ciudad"),
            }
            changed = False
            for field, value in fields.items():
                if value and not getattr(client, field):
                    setattr(client, field, value)
                    changed = True
            updated_clients += int(changed)

        db.commit()
        print({"clientes_actualizados": updated_clients, "suscripciones_actualizadas": updated_subscriptions})
    finally:
        db.close()


if __name__ == "__main__":
    main()
