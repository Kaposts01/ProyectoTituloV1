"""Complete TCH contacts and peso equivalents from existing raw report payloads."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.tch import TchCliente, TchSuscripcion


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
        clients = {client.rut: client for client in db.scalars(select(TchCliente)).all()}
        updated_clients = 0
        updated_subscriptions = 0
        subscriptions = db.scalars(select(TchSuscripcion).order_by(TchSuscripcion.updated_at.desc())).all()
        for subscription in subscriptions:
            payload = subscription.raw_payload or {}
            equivalent = _amount(payload)
            if equivalent and not subscription.equivalente_pesos:
                subscription.equivalente_pesos = equivalent
                updated_subscriptions += 1

            client = clients.get(subscription.cliente_rut or "")
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
                "telefono": _value(payload, "telefono"),
                "email": _value(payload, "email"),
                "direccion": address,
                "comuna": _value(payload, "comuna"),
                "ciudad": _value(payload, "ciudad"),
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
