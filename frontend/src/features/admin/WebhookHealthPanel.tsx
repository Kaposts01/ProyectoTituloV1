import { useCallback, useEffect, useState } from "react";
import { friendlyError, getJson, postJson } from "../../api";
import { label, labelOr } from "../../i18n/label";
import "../../components/ChangeToasts.css";

/**
 * Salud de webhooks (RT-14): conteos por estado, demora del pendiente más antiguo, último evento por proveedor y
 * reproceso manual de los fallidos. Requiere `webhooks.manage`. La API no devuelve datos personales ni payloads.
 */

export const WEBHOOKS_PERMISSION = "webhooks.manage";
const STATUSES = ["pending", "processing", "done", "failed", "ignored"] as const;

type SourceHealth = {
  source: string;
  counts: Record<string, number>;
  last_received_at: string | null;
  pending_lag_minutes: number | null;
  done_last_24h: number;
  avg_processing_seconds_24h: number | null;
};
export type WebhookHealth = {
  generated_at: string;
  processor_enabled: boolean;
  sources: SourceHealth[];
  error_codes_24h: Array<{ code: string; count: number }>;
};
type WebhookEventRow = { id: string; source: string; event_type: string; status: string; attempts: number; last_error_code: string | null; received_at: string | null };

function when(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("es-CL");
}

export function WebhookHealthPanel() {
  const [health, setHealth] = useState<WebhookHealth | null>(null);
  const [failed, setFailed] = useState<WebhookEventRow[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [h, list] = await Promise.all([
        getJson<WebhookHealth>("/api/v1/admin/webhooks/health"),
        getJson<{ items: WebhookEventRow[] }>("/api/v1/admin/webhooks/events?status=failed&limit=20"),
      ]);
      setHealth(h);
      setFailed(list.items);
      setError("");
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la salud de los webhooks."));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const requeue = async (body: { ids: string[] } | { all_failed: true }) => {
    setBusy(true);
    try {
      const result = await postJson<{ requeued: number }>("/api/v1/admin/webhooks/requeue", body);
      setNotice(`${result.requeued} evento(s) vuelto(s) a la cola.`);
      await load();
    } catch (err) {
      setError(friendlyError(err, "No se pudo reprocesar."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel" id="webhooks" aria-labelledby="webhooks-title">
      <h2 id="webhooks-title">Salud de webhooks</h2>
      {error ? <p role="alert">{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
      {health ? (
        <>
          <p className="muted-copy">
            {health.processor_enabled ? "El procesador de la cola está encendido." : "El procesador de la cola está apagado: los avisos solo se acumulan."}
          </p>
          <div className="webhook-health-wrap">
            <table className="webhook-health-table">
              <thead>
                <tr>
                  <th>Canal</th>
                  {STATUSES.map((s) => <th key={s}>{label("webhookStatus", s)}</th>)}
                  <th>Demora del pendiente más antiguo</th>
                  <th>Último recibido</th>
                  <th>Procesados en 24 h</th>
                </tr>
              </thead>
              <tbody>
                {health.sources.map((s) => (
                  <tr key={s.source}>
                    <td>{label("channel", s.source)}</td>
                    {STATUSES.map((st) => <td key={st} className="mono">{s.counts[st] ?? 0}</td>)}
                    <td className="mono">{s.pending_lag_minutes === null ? "—" : `${s.pending_lag_minutes} min`}</td>
                    <td className="mono">{when(s.last_received_at)}</td>
                    <td className="mono">{s.done_last_24h}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {health.error_codes_24h.length ? (
            <ul>
              {health.error_codes_24h.map((c) => <li key={c.code}>{label("webhookErrorCode", c.code)}: <span className="mono">{c.count}</span></li>)}
            </ul>
          ) : <p className="muted-copy">Sin errores en las últimas 24 h.</p>}
          <h3>Eventos fallidos</h3>
          {failed.length ? (
            <>
              <button type="button" disabled={busy} onClick={() => void requeue({ all_failed: true })}>Reprocesar todos los fallidos</button>
              <div className="webhook-health-wrap">
                <table className="webhook-health-table">
                  <thead><tr><th>Canal</th><th>Tipo de aviso</th><th>Intentos</th><th>Motivo</th><th>Recibido</th><th /></tr></thead>
                  <tbody>
                    {failed.map((ev) => (
                      <tr key={ev.id}>
                        <td>{label("channel", ev.source)}</td>
                        <td className="mono" data-raw-text>{ev.event_type}</td>
                        <td className="mono">{ev.attempts}</td>
                        <td>{labelOr("webhookErrorCode", ev.last_error_code, "—")}</td>
                        <td className="mono">{when(ev.received_at)}</td>
                        <td><button type="button" disabled={busy} onClick={() => void requeue({ ids: [ev.id] })}>Reprocesar</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : <p className="muted-copy">No hay eventos fallidos.</p>}
        </>
      ) : error ? null : <p className="muted-copy">Cargando...</p>}
    </section>
  );
}
