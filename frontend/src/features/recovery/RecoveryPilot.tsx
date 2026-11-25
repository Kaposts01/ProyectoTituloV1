import { useEffect, useRef, useState } from "react";
import { ApiError, getJson } from "../../api";
import { ADVICE, CATEGORY_LABELS, PILOT_PAGE_SIZE, PILOT_PATH, REASONS, RESTRICTIONS, parsePilotResults, pilotDate, type PilotResult } from "./pilotContract";
import "./recoveryPilot.css";

type LoadState = { kind: "loading" } | { kind: "error"; message: string; retry: boolean } | { kind: "ready"; rows: PilotResult[] };
function errorMessage(error: unknown): { message: string; retry: boolean } {
  if (error instanceof ApiError) {
    if (error.status === 401) return { message: "Tu sesión terminó. Vuelve a iniciar sesión para continuar.", retry: false };
    if (error.status === 403) return { message: "No tienes acceso a este análisis. Solicita los permisos del piloto a un administrador.", retry: false };
    if (error.code === "ml_api_disabled" || error.code === "ml_synthetic_only") return { message: "El piloto no está habilitado en este entorno. Pide al responsable que prepare el entorno de pruebas.", retry: false };
  }
  return { message: "No se pudo cargar un análisis de prueba válido. Revisa la conexión o vuelve a intentarlo.", retry: true };
}
function explanation(row: PilotResult) {
  if (row.state === "conflict") return "Hay antecedentes contradictorios. No se asignó un motivo definitivo.";
  if (row.category === null) return "No hay evidencia suficiente para clasificar este motivo.";
  return row.method === "rule" ? "La clasificación se basa en reglas revisables, no en un modelo entrenado." : "La evidencia requiere revisión antes de clasificar el motivo.";
}

/** Read-only ML-12 view. No cache, fixture fallback, storage, provider actions or approval mutation. */
export function RecoveryPilot() {
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [selected, setSelected] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const triggers = useRef(new Map<string, HTMLButtonElement>());
  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    getJson<unknown>(`${PILOT_PATH}?limit=${PILOT_PAGE_SIZE}&offset=${offset}`, controller.signal)
      .then((data) => { if (live) setState({ kind: "ready", rows: parsePilotResults(data) }); })
      .catch((error: unknown) => { if (live) setState({ kind: "error", ...errorMessage(error) }); });
    return () => { live = false; controller.abort(); };
  }, [offset, refresh]);
  useEffect(() => { if (selected) heading.current?.focus(); }, [selected]);
  function load(next: number) {
    setSelected(null); setState({ kind: "loading" }); setOffset(next); setRefresh((value) => value + 1);
  }
  const row = state.kind === "ready" ? state.rows.find((item) => item.id === selected) : undefined;
  return <section className="ml-pilot" aria-labelledby="ml-pilot-title">
    <header className="ml-pilot-heading"><div><p className="eyebrow">TCH · Solo lectura</p><h2 id="ml-pilot-title">Piloto de análisis de rechazos</h2></div><span className="ml-pilot-badge">Datos de prueba</span></header>
    <p className="ml-pilot-notice">Estos casos son ficticios y están separados de la cartera real. No habilitan cobros, reintentos ni cambios de datos.</p>
    <p className="ml-pilot-context">Revisa los antecedentes pendientes. El corte del análisis no confirma el estado actual del cobro.</p>
    {state.kind === "loading" && <p role="status" className="ml-pilot-message">Cargando casos de prueba…</p>}
    {state.kind === "error" && <div role="alert" className="ml-pilot-message"><p>{state.message}</p>{state.retry && <button type="button" onClick={() => load(offset)}>Volver a cargar casos</button>}</div>}
    {state.kind === "ready" && <>
      {state.rows.length === 0 ? <div className="ml-pilot-message" role="status"><h3>Sin casos de prueba en esta página</h3><p>No significa que no existan rechazos reales. El responsable debe preparar resultados sintéticos para este entorno.</p>{offset > 0 && <button type="button" onClick={() => load(Math.max(0, offset-PILOT_PAGE_SIZE))}>Volver a la página anterior</button>}</div> : <>
        <div className="ml-pilot-toolbar"><p aria-live="polite">Casos {offset+1}–{offset+state.rows.length} · Muestra de prueba</p><button type="button" onClick={() => load(offset)}>Actualizar casos</button></div>
        <div className={`ml-pilot-layout${row ? " has-detail" : ""}`}>
          <ul className="ml-pilot-list" aria-label="Casos de prueba">
            {state.rows.map((item, index) => <li key={item.id}>
              <div><strong>Caso de prueba {offset+index+1}</strong><p>{item.category ? CATEGORY_LABELS[item.category] : "Motivo por revisar"}</p><small>Corte: {pilotDate(item.asOf)} · hora de Chile</small></div>
              <button type="button" aria-expanded={selected === item.id} aria-controls={selected === item.id ? "ml-pilot-detail" : undefined} aria-label={`Revisar caso de prueba ${offset+index+1}`} ref={(element) => { if (element) triggers.current.set(item.id, element); else triggers.current.delete(item.id); }} onClick={() => setSelected(item.id)}>Ver explicación</button>
            </li>)}
          </ul>
          {row && <section id="ml-pilot-detail" className="ml-pilot-detail" aria-labelledby="ml-pilot-detail-title">
            <h3 ref={heading} tabIndex={-1} id="ml-pilot-detail-title">{ADVICE[row.advice].title}</h3>
            <p>{ADVICE[row.advice].description}</p><p>{explanation(row)}</p>
            <dl><dt>Fecha de corte del análisis</dt><dd>{pilotDate(row.asOf)} · hora de Chile</dd><dt>Probabilidad de recuperación</dt><dd>No disponible: aún no hay un modelo validado.</dd></dl>
            <h4>Qué falta revisar</h4><ul>{row.reasons.some((value) => !["p1_unavailable", "p2_unavailable"].includes(value)) ? [...new Set(row.reasons.filter((value) => !["p1_unavailable", "p2_unavailable"].includes(value)).map((reason) => REASONS[reason] ?? "Hay un antecedente pendiente de interpretar con el responsable."))].map((reason) => <li key={reason}>{reason}</li>) : <li>Confirma el estado actual y la evidencia con el responsable.</li>}</ul>
            <h4>Resguardos</h4><ul>{[...new Set(row.restrictions.map((value) => RESTRICTIONS[value] ?? "Existe una restricción pendiente de revisar."))].map((text) => <li key={text}>{text}</li>)}</ul>
            <p className="ml-pilot-human"><strong>Revisión humana obligatoria.</strong> Esta vista no registra aprobaciones. Verifica los datos y sigue los permisos y las confirmaciones del Recuperador operativo.</p>
            <details><summary>Procedencia del análisis</summary><p>Reglas aplicadas: {row.matchedRules.length.toLocaleString("es-CL")}. Sin inferir causas ni efectos de un reintento.</p><dl><dt>Motor</dt><dd>{row.versions.engine}</dd><dt>Política</dt><dd>{row.versions.policy}</dd><dt>Reglas</dt><dd>{row.versions.rules}</dd><dt>Taxonomía</dt><dd>{row.versions.taxonomy}</dd></dl></details>
            <button type="button" onClick={() => { setSelected(null); triggers.current.get(row.id)?.focus(); }}>Volver a los casos</button>
          </section>}
        </div>
        <nav className="ml-pilot-pages" aria-label="Páginas del piloto"><button type="button" disabled={offset === 0} onClick={() => load(Math.max(0, offset-PILOT_PAGE_SIZE))}>Página anterior</button><button type="button" disabled={state.rows.length < PILOT_PAGE_SIZE || offset+PILOT_PAGE_SIZE > 10000} onClick={() => load(offset+PILOT_PAGE_SIZE)}>Página siguiente</button></nav>
      </>}
    </>}
  </section>;
}
