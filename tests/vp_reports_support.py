"""Constructor de CSV SINTETICOS de los reportes PAT de VirtualPOS para pruebas (VP-PAR-02). Cero datos reales.

Mismos encabezados y orden que los reportes reales (TransaccionesPAT: 33 columnas; SuscriptoresPAT: 40), con
SENTINELAS en las columnas personales para comprobar que nunca llegan a la BD, a los logs ni a los errores.
Se importa como modulo plano (`from vp_reports_support import ...`, igual que `toku_reports_support`).
"""

import csv
from pathlib import Path
from typing import Any

SENTINEL_NAME = "SENTINELA-NOMBRE"
SENTINEL_LAST = "SENTINELA-APELLIDO"
SENTINEL_MAIL = "sentinela@example.invalid"
SENTINEL_RUT = "00.000.001-K"
SENTINEL_PHONE = "SENTINELA-FONO"
SENTINEL_BIRTH = "SENTINELA-NACIMIENTO"
SENTINEL_GENDER = "SENTINELA-GENERO"
SENTINEL_ADDRESS = "SENTINELA-DIRECCION"
SENTINEL_SELLER = "00.000.002-7"
SENTINEL_PAN = "4111111111111111"
PII_SENTINELS = (
    SENTINEL_NAME, SENTINEL_LAST, SENTINEL_MAIL, SENTINEL_RUT, SENTINEL_PHONE, SENTINEL_BIRTH, SENTINEL_GENDER,
    SENTINEL_ADDRESS, SENTINEL_SELLER, SENTINEL_PAN,
)  # fmt: skip
PEPPER = "pepper-vp-de-pruebas"

COLUMNS: dict[str, list[str]] = {
    "transacciones": [
        "Id suscripción", "Nombre cliente", "Apellido cliente", "Email cliente", "RUT cliente", "Plan suscrito",
        "Estado de suscripción", "Total de cargos programados", "Número de cargo", "Monto de cargo",
        "Moneda de cargo", "Costo de despacho", "Fecha programada de cargo", "Estado del cargo", "Id plan",
        "Id cargo", "Id cargo comercio", "Total comisión (imp. incl.)", "Total abono", "Fecha de abono",
        "Código de autorización/error/rechazo", "Glosa de autorización/error/rechazo", "UUID transacción",
        "Final número tarjeta", "Medio de pago", "Fecha de autorización", "Fecha de suscripción",
        "Origen de la suscripción", "Alias POS", "ID suscripción interno", "Código de vendedor",
        "Origen del cargo", "Cód. de nómina",
    ],
    "suscriptores": [
        "Id de suscripción", "Fecha de suscripción", "Nombre cliente", "Apellido cliente", "Email cliente",
        "RUT cliente", "Teléfono cliente", "Fecha de nacimiento cliente", "Género cliente", "Plan suscrito",
        "Id de plan", "Estado de suscripción", "Total de cargos programados", "Fecha de cancelación",
        "Total de cargos autorizados", "Total de cargos rechazados", "Total de cargos pendientes",
        "Total de cargos en proceso", "Total de cargos cancelados", "Fecha próximo cargo",
        "Número de próximo cargo", "Monto próximo cargo", "Moneda", "Canal/Origen", "Num serie POS", "Alias POS",
        "Código de vendedor", "Tipo tarjeta", "Últimos 4 dígitos pan", "Marca", "Estado próximo cargo",
        "Dirección de despacho", "Número de dpto", "Información adicional", "Comuna", "Región",
        "Política de despacho", "Costo de despacho", "Motivo de rechazo", "ID suscripción interno",
    ],
}  # fmt: skip

assert len(COLUMNS["transacciones"]) == 33 and len(COLUMNS["suscriptores"]) == 40


def sub_id(n: int) -> str:
    return f"S{n:05d}xyz"


def charge_id(n: int) -> str:
    return f"cid_T{n:05d}.9"


def uuid_of(n: int) -> str:
    return f"U{n:015d}"


def payment_row(n: int, **over: Any) -> dict[str, Any]:
    """Fila de TransaccionesPAT: cobro pagado por defecto, con sentinelas de PII."""
    row: dict[str, Any] = {
        "Id suscripción": sub_id(n) + "\t",  # el portal agrega un tabulador final
        "Nombre cliente": SENTINEL_NAME, "Apellido cliente": SENTINEL_LAST, "Email cliente": SENTINEL_MAIL,
        "RUT cliente": SENTINEL_RUT, "Plan suscrito": "Plan $9.990 Mensual", "Estado de suscripción": "ACTIVA",
        "Total de cargos programados": "12", "Número de cargo": "Cargo 3 de 12", "Monto de cargo": "9990",
        "Moneda de cargo": "CLP", "Costo de despacho": "", "Fecha programada de cargo": "05/10/2026",
        "Estado del cargo": "pagado", "Id plan": "plan-abc", "Id cargo": charge_id(n), "Id cargo comercio": "",
        "Total comisión (imp. incl.)": "250", "Total abono": "9740", "Fecha de abono": "07/10/2026 00:00",
        "Código de autorización/error/rechazo": "004378", "Glosa de autorización/error/rechazo": "",
        "UUID transacción": uuid_of(n), "Final número tarjeta": "1234", "Medio de pago": "Débito",
        "Fecha de autorización": "05/10/2026 09:30", "Fecha de suscripción": "01/03/2026 10:00",
        "Origen de la suscripción": "POS", "Alias POS": "TEST_POS_1", "ID suscripción interno": "1234",
        "Código de vendedor": SENTINEL_SELLER, "Origen del cargo": "", "Cód. de nómina": "",
    }  # fmt: skip
    row.update(over)
    return row


def rejected_payment_row(n: int, code: str = "-11", text: str = "Excede límite de reintentos de rechazo", **over: Any):
    base = {
        "Estado del cargo": "rechazado", "Código de autorización/error/rechazo": code,
        "Glosa de autorización/error/rechazo": text, "Total comisión (imp. incl.)": "", "Total abono": "",
        "Fecha de abono": "", "Final número tarjeta": "", "Medio de pago": "", "Fecha de autorización": "",
    }  # fmt: skip
    base.update(over)
    return payment_row(n, **base)


def subscription_row(n: int, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "Id de suscripción": sub_id(n) + "\t", "Fecha de suscripción": "01/03/2026 10:00",
        "Nombre cliente": SENTINEL_NAME, "Apellido cliente": SENTINEL_LAST, "Email cliente": SENTINEL_MAIL,
        "RUT cliente": SENTINEL_RUT, "Teléfono cliente": SENTINEL_PHONE,
        "Fecha de nacimiento cliente": SENTINEL_BIRTH, "Género cliente": SENTINEL_GENDER,
        "Plan suscrito": "Plan $9.990 Mensual", "Id de plan": "plan-abc", "Estado de suscripción": "ACTIVA",
        "Total de cargos programados": "12", "Fecha de cancelación": "", "Total de cargos autorizados": "3",
        "Total de cargos rechazados": "1", "Total de cargos pendientes": "7", "Total de cargos en proceso": "0",
        "Total de cargos cancelados": "1", "Fecha próximo cargo": "", "Número de próximo cargo": "",
        "Monto próximo cargo": "", "Moneda": "CLP", "Canal/Origen": "POS", "Num serie POS": "12345678901234",
        "Alias POS": "TEST_POS_1", "Código de vendedor": SENTINEL_SELLER, "Tipo tarjeta": "TD",
        "Últimos 4 dígitos pan": "1234", "Marca": "visa", "Estado próximo cargo": "",
        "Dirección de despacho": SENTINEL_ADDRESS, "Número de dpto": "", "Información adicional": "",
        "Comuna": "", "Región": "", "Política de despacho": "", "Costo de despacho": "", "Motivo de rechazo": "",
        "ID suscripción interno": "1234",
    }  # fmt: skip
    row.update(over)
    return row


def default_row(kind: str, n: int, **over: Any) -> dict[str, Any]:
    return (payment_row if kind == "transacciones" else subscription_row)(n, **over)


def write_report(
    path: Path,
    kind: str,
    rows: list[dict[str, Any]] | None = None,
    *,
    bom: bool = True,
    delimiter: str = ",",
    title_lines: int = 0,
    encoding: str = "utf-8",
    header_override: list[str] | None = None,
    extra_columns: dict[str, Any] | None = None,
    mojibake: bool = False,
) -> Path:
    """Escribe un CSV con los encabezados reales. `extra_columns` agrega columnas al final (p. ej. duplicadas)."""
    header = list(header_override or COLUMNS[kind])
    rows = rows if rows is not None else [default_row(kind, i) for i in (1, 2, 3)]
    extras = extra_columns or {}
    out_header = header + list(extras)
    if mojibake:  # UTF-8 leido como latin-1 y vuelto a guardar en UTF-8 (doble codificacion)
        out_header = [h.encode("utf-8").decode("latin-1") for h in out_header]

    def cell(row: dict[str, Any], col: str, orig: str) -> str:
        value = row.get(orig, extras.get(orig, ""))
        text = "" if value is None else str(value)
        return text.encode("utf-8").decode("latin-1") if mojibake else text

    with open(path, "w", encoding=encoding + ("-sig" if bom and encoding == "utf-8" else ""), newline="") as fh:
        for i in range(title_lines):
            fh.write(f"Reporte de prueba linea {i}\n")
        writer = csv.writer(fh, delimiter=delimiter)
        writer.writerow(out_header)
        original = header + list(extras)
        for row in rows:
            writer.writerow([cell(row, c, o) for c, o in zip(out_header, original, strict=True)])
    return path
