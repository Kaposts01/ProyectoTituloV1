import { pageLabels } from "../../pageLabels";
import { useEffect, useRef, useState } from "react";
import { useChannelHealthState } from "../../hooks/useChannelHealth";
import { ChannelFilter, MonthPicker } from "./SummaryControls";
import { SummaryCharts } from "./SummaryCharts";
import { SummaryHealth } from "./SummaryHealth";
import { SummaryKpiGrid, SummaryKpiSkeleton } from "./SummaryKpiGrid";
import { hasAnyData } from "./summaryAdapter";
import { monthLabel, shiftMonth, tchDataDate } from "./summaryFormat";
import type { SummaryChannel, UnifiedSummary } from "./summaryTypes";
import { useSummary } from "./useSummary";
import { dashboardSelection, type PrimaryMetric } from "./dashboardContext";
import { SummaryMetricDetail } from "./SummaryMetricDetail";
import { SummaryActions } from "./SummaryActions";

function formatGeneratedAt(iso: string | null): string | null {
  if (!iso) return null;
  const time = Date.parse(iso);
  if (Number.isNaN(time)) return null;
  return new Date(time).toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short", timeZone: "America/Santiago" });
}

/**
 * QA-07 (decisión: opción A). El Resumen sigue abriendo en el mes en curso, pero lo dice sin prometer frescura:
 * datos parciales, y las tarjetas de flujo no muestran variación contra el mes anterior (comparar unos días contra
 * un mes completo dibujaba caídas que no ocurrieron). Un botón lleva al último mes cerrado.
 */
function PartialMonthNote({ summary, onClosedMonth }: { summary: UnifiedSummary; onClosedMonth: () => void }) {
  if (!summary.isCurrentMonth) return null;
  return (
    <div className="summary-partial" role="note" aria-label="Mes en curso">
      <p>
        <strong>Mes en curso · Cierre pendiente</strong>
        <span>Datos parciales. Ingresos, altas, bajas y churn tendrán comparación mensual cuando termine el mes.</span>
      </p>
      <button type="button" className="secondary-button" onClick={onClosedMonth}>Ver el último mes cerrado</button>
    </div>
  );
}


/**
 * Resumen unificado de la jefatura (UX-06): selector de mes, filtro de canales, KPIs del mes con variación contra el
 * mes anterior y gráficos de 12 meses. Consume `GET /api/v1/dashboard/general` solo a través de `summaryApi` /
 * `summaryAdapter`. No existen metas todavía (D2): todos los KPIs muestran el chip «sin meta».
 */
const noPermissions = () => false;
export function SummaryView({ can = noPermissions, onOpenPath }: { can?: (permission: string) => boolean; onOpenPath?: (path: string) => void }) {
  const [initial] = useState(() => dashboardSelection(window.location.search));
  const [month, setMonth] = useState<string | undefined>(initial.month);
  const [selected, setSelected] = useState<SummaryChannel[] | null>(initial.channels ?? null);
  const [detail, setDetail] = useState<PrimaryMetric | null>(null);
  const detailTrigger = useRef<HTMLButtonElement | null>(null);
  const chooseMonth = (value: string | undefined) => { setDetail(null); setMonth(value); };
  const showDetail = (metric: PrimaryMetric, button: HTMLButtonElement) => {
    detailTrigger.current = button; setDetail((current) => current === metric ? null : metric);
  };
  const closeDetail = () => { setDetail(null); if (detailTrigger.current?.isConnected) detailTrigger.current.focus(); };
  const selectedKey = selected?.join(",") ?? "";
  useEffect(() => {
    if (window.location.pathname !== "/central/resumen") return;
    const params = new URLSearchParams();
    if (month) params.set("mes", month);
    if (selectedKey) params.set("canales", selectedKey);
    const search = params.toString();
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`);
  }, [month, selectedKey]);
  const { state, availableChannels, currentMonth, reload } = useSummary(month, selected ?? undefined);
  const { health, ready: healthReady } = useChannelHealthState(true);

  const toggleChannel = (channel: SummaryChannel) => {
    setDetail(null);
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
          <h1 className="summary-title">{pageLabels.dashboard}</h1>
          <p className="summary-subtitle">{shown ? `Resumen de ${monthLabel(shown.month)}` : month ? `Resumen de ${monthLabel(month)}` : "Resumen del mes actual"}</p>
        </div>
      </header>
      <section className="summary-controls" aria-label="Filtros del Dashboard">
        <MonthPicker value={monthValue} picked={month !== undefined} onChange={chooseMonth} onReset={() => chooseMonth(undefined)} />
        <ChannelFilter available={availableChannels} selected={selected} onToggle={toggleChannel} />
      </section>

      {shown && shown.channels.length > 0 ? <PartialMonthNote summary={shown} onClosedMonth={() => chooseMonth(shiftMonth(shown.month, -1))} /> : null}
      {shown ? <SummaryHealth channels={shown.channels} health={health} ready={healthReady} generatedAt={generatedAt} /> : null}

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
          {empty || shown.channels.length === 0 ? (
            <div className="summary-empty" role="status" aria-label={shown.channels.length === 0 ? "Acceso a canales restringido" : "Mes sin datos"}>
              <p className="summary-empty-title">{shown.channels.length === 0 ? "No tienes canales habilitados para este Dashboard." : `No hay indicadores disponibles para ${monthLabel(shown.month)}.`}</p>
              <p className="summary-empty-copy">
                {shown.channels.length === 0
                  ? "Solicita a un administrador revisar tus permisos de consulta."
                  : "La falta de datos no confirma que no haya actividad. Revisa el mes seleccionado y la actualización de los canales."}
              </p>
              {shown.channels.length > 0 ? <div className="summary-empty-actions">
                <button type="button" className="secondary-button" onClick={() => chooseMonth(shiftMonth(shown.month, -1))}>Ver el mes anterior</button>
                {month !== undefined ? <button type="button" className="secondary-button" onClick={() => chooseMonth(undefined)}>Volver al mes actual</button> : null}
              </div> : null}
            </div>
          ) : null}
          {shown.channels.length > 0 ? <SummaryKpiGrid summary={shown} onDetail={showDetail} selectedDetail={detail} detail={detail
            ? <SummaryMetricDetail summary={shown} metric={detail} can={can} onClose={closeDetail} onOpenPath={onOpenPath} />
            : <div id="summary-metric-detail" hidden />}
            review={<SummaryActions summary={shown} health={health} healthReady={healthReady} can={can} onOpenPath={onOpenPath} onDetail={showDetail} />} /> : null}
          {empty || shown.channels.length === 0 ? null : <SummaryCharts summary={shown} tchDataDate={tchDataDate(health)} />}
        </>
      ) : null}
    </main>
  );
}
