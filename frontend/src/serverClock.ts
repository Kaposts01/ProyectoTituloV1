/**
 * Reloj del servidor. El navegador puede tener la hora desajustada; el backend es la fuente de verdad del tiempo.
 * Cada respuesta HTTP trae la cabecera `Date`; se guarda la diferencia con el reloj local y `serverNow()` la aplica.
 * Limitaciones: la cabecera tiene resolución de 1 s y, si un proxy/caché la reemplazara por una fecha antigua, el
 * desfase sería erróneo (las rutas de la API no se cachean). Sin cabecera se usa el reloj del navegador.
 * Lo ideal es que el backend envíe `expires_in_days` / un tiempo restante calculado (ver informe de la tanda 3).
 */
let offsetMs = 0;

export function noteServerDate(header: string | null | undefined): void {
  if (!header) return;
  const server = Date.parse(header);
  if (Number.isNaN(server)) return;
  offsetMs = server - Date.now();
}

export function serverNow(): number {
  return Date.now() + offsetMs;
}

export function resetServerClock(): void {
  offsetMs = 0;
}
