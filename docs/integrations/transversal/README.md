# Flujos transversales — comparacion entre canales

> Este directorio contiene sintesis que comparan el comportamiento de los tres canales (VirtualPOS, Toku, Payku) para flujos operacionales que existen en todos ellos.
>
> Cada archivo tabula las diferencias clave para implementar la capa comun sin asumir contratos compartidos.

---

## Flujos documentados

| Flujo | Archivo | Descripcion |
|---|---|---|
| Link seguro de inscripcion de tarjeta | [link-inscripcion.md](link-inscripcion.md) | Como cada canal emite y confirma el link de inscripcion de medio de pago en un alta o para un socio existente |
| Seguimiento de cobros recurrentes | [seguimiento-cobros.md](seguimiento-cobros.md) | Como cada canal modela la cuota esperada, el cobro efectivo, los intentos y la liquidacion |
| Cambiar el monto del aporte | [cambiar-monto.md](cambiar-monto.md) | Que permite cada canal por API para cambiar el monto de una suscripcion recurrente |

---

## Principios de uso

- Los archivos en este directorio son **sintesis**: no reemplazan los adaptadores por canal (que viven en cada `workflows/`).
- Cuando una diferencia entre canales requiere una decision de diseno, escalarla al arquitecto o registrarla como TBD.
- Los bloqueantes criticos por canal (T-A1 en Toku, Q-06/Q-08 en Payku, V-1..V-4 en VirtualPOS) estan resumidos en los README de cada canal; aqui solo se mencionan cuando afectan la capa comun.

---

## Referencias por canal

| Canal | Documentacion operacional | Referencia tecnica plana |
|---|---|---|
| VirtualPOS | [virtualpos/README.md](../virtualpos/README.md) | [virtualpos.md](../virtualpos.md) |
| Toku | [toku/README.md](../toku/README.md) | [toku.md](../toku.md) |
| Payku | [payku/README.md](../payku/README.md) | [payku.md](../payku.md) |
