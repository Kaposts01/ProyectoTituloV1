import { useState } from "react";
import { useChannelHealth } from "../../hooks/useChannelHealth";
import { ChannelFilter, MonthPicker } from "./SummaryControls";
import { SummaryCharts } from "./SummaryCharts";
import { SummaryHealth } from "./SummaryHealth";
import { SummaryKpiGrid, SummaryKpiSkeleton } from "./SummaryKpiGrid";
import { hasAnyData } from "./summaryAdapter";
import { monthLabel, shiftMonth, tchDataDate } from "./summaryFormat";
import type { SummaryChannel, UnifiedSummary } from "./summaryTypes";
import { useSummary } from "./useSummary";

function formatGeneratedAt(iso: string | null): string | null {
  if (!iso) return null;
  const time = Date.parse(iso);
  if (Number.isNaN(time)) return null;
  return new Date(time).toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short", timeZone: "America/Santiago" });
}

function QualityNote({ summary }: { summary: UnifiedSummary }) {
  const { activationsWithoutDate: upFree, cancellationsWithoutDate: downFree } = summary.dataQuality;
  if (upFree <= 0 && downFree <= 0) return null;
  const parts = [
    upFree > 0 ? `${upFree.toLocaleString("es-CL")} ${upFree === 1 ? "suscripción sin fecha de alta válida" : "suscripciones sin fecha de alta válida"}` : null,
    downFree > 0 ? `${downFree.toLocaleString("es-CL")} ${downFree === 1 ? "baja sin fecha de baja válida" : "bajas sin fecha de baja válida"}` : null,
  ].filter(Boolean);
  return <p className="summary-quality">Datos incompletos: {parts.join(" y ")}. No entran en los indicadores de ningún mes.</p>;
}

/**
 * Resumen unificado de la jefatura (UX-06): selector de mes, filtro de canales, KPIs del mes con variación contra el
 * mes anterior y gráficos de 12 meses. Consume `GET /api/v1/dashboard/general` solo a través de `summaryApi` /
 * `summaryAdapter`. No existen metas todavía (D2): todos los KPIs muestran el chip «sin meta».
 */
export function SummaryView() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [selected, setSelected] = useState<SummaryChannel[] | null>(null);
  const { state, availableChannels, currentMonth, reload } = useSummary(month, selected ?? undefined);
  const health = useChannelHealth(true);

  const toggleChannel = (channel: SummaryChannel) => {
    const current = selected ?? availableChannels;
    const next = current.includes(channel)
      ? current.filter((item) => item !== channel)
      : availableChannels.filter((item) => item === channel || current.includes(item));
    if (next.length === 0) return;
    setSelected(next.length === availableChannels.length ? null : next);
  };

  const shown = state.status === "ready" ? state.data : null;
  const monthValue = month ?? shown?.month ?? currentMonth ?? "";
  const generatedAt = formatGeneratedAt(shown?.generatedAt ?? null);
  const empty = shown !== null && !hasAnyData(shown);

  return (
    <main className="app-shell summary-view">
      <header className="summary-header">
        <div>
          <h1 className="summary-title">Resumen</h1>
          <p className="summary-subtitle">
            {shown ? `Datos de ${monthLabel(shown.month)}` : month ? `Datos de ${monthLabel(month)}` : "Datos del mes actual"}
            {generatedAt ? <span className="summary-generated mono"> · Calculado el {generatedAt}</span> : null}
          </p>
        </div>
        <div className="summary-controls">
          <MonthPicker value={monthValue} picked={month !== undefined} onChange={setMonth} onReset={() => setMonth(undefined)} />
          <ChannelFilter available={availableChannels} selected={selected} onToggle={toggleChannel} />
        </div>
      </header>

      {shown ? <SummaryHealth channels={shown.channels} health={health} /> : null}

      {state.status === "loading" ? (
        <>
          <p role="status" className="sr-only">Cargando el resumen…</p>
          <SummaryKpiSkeleton />
        </>
      ) : null}

      {state.status === "error" ? (
        <div className="error-message summary-error" role="alert">
          <p>{state.message}</p>
          <button type="button" className="secondary-button" onClick={reload}>Reintentar</button>
        </div>
      ) : null}

      {shown ? (
        <>
          {empty ? (
            <div className="summary-empty" role="status" aria-label="Mes sin datos">
              <p className="summary-empty-title">No hay datos para {monthLabel(shown.month)}.</p>
              <p className="summary-empty-copy">
                {shown.channels.length === 0
                  ? "No tienes canales con permiso para ver este resumen."
                  : "Ningún canal tiene actividad registrada en ese mes."}
              </p>
              <div className="summary-empty-actions">
                <button type="button" className="secondary-button" onClick={() => setMonth(shiftMonth(shown.month, -1))}>Ver el mes anterior</button>
                {month !== undefined ? <button type="button" className="secondary-button" onClick={() => setMonth(undefined)}>Volver al mes actual</button> : null}
              </div>
            </div>
          ) : null}
          <SummaryKpiGrid summary={shown} />
          <QualityNote summary={shown} />
          {empty ? null : <SummaryCharts summary={shown} tchDataDate={tchDataDate(health)} />}
        </>
      ) : null}
    </main>
  );
}
