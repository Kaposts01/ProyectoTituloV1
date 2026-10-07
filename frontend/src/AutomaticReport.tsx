import { useEffect, useState } from "react";

type ChannelStats = {
  new_subscriptions: number;
  cancellations: number;
  active_start: number;
  active_end: number;
  revenue: number;
  revenue_count: number;
  rejected: number;
  total_charges: number;
  rejection_rate: number;
  churn_rate: number;
};

type ReportPeriod = {
  date_from: string;
  date_to: string;
  channels: {
    global: ChannelStats;
    virtualpos: ChannelStats;
    toku: ChannelStats;
    payku: ChannelStats;
    tch: ChannelStats;
  };
  rejection_reasons: { reason: string; count: number; channel: string }[];
  alerts: { sev: "alta" | "media" | "baja"; tipo: string; detalle: string }[];
};

type AutomaticReportData = {
  generated_at: string;
  periods: {
    annual: ReportPeriod;
    monthly: ReportPeriod;
    weekly: ReportPeriod;
  };
};

type Period = "annual" | "monthly" | "weekly";

const PERIOD_LABELS: Record<Period, string> = {
  annual: "Año en curso",
  monthly: "Mes en curso",
  weekly: "Semana en curso",
};

const CHANNEL_LABELS: Record<string, string> = {
  global: "Global",
  virtualpos: "VirtualPOS",
  toku: "Toku",
  payku: "Payku",
  tch: "TCH",
};

const CHANNELS = ["global", "virtualpos", "toku", "payku", "tch"] as const;

function clp(n: number): string {
  return "$" + Math.round(n).toLocaleString("es-CL");
}

function pct(n: number): string {
  return n.toFixed(1) + "%";
}

async function fetchReport(): Promise<AutomaticReportData> {
  const r = await fetch("/api/v1/reports/automatic", { credentials: "include" });
  if (!r.ok) throw new Error(`Error ${r.status}: ${r.statusText}`);
  return r.json() as Promise<AutomaticReportData>;
}

function ChurnBadge({ rate }: { rate: number }) {
  const cls = rate > 10 ? "red" : rate > 5 ? "orange" : rate > 2 ? "blue" : "green";
  return <span className={`badge badge-${cls}`}>{pct(rate)}</span>;
}

function RejectBadge({ rate }: { rate: number }) {
  const cls = rate > 50 ? "red" : rate > 30 ? "orange" : "green";
  return <span className={`badge badge-${cls}`}>{pct(rate)}</span>;
}

function AlertRow({ a }: { a: { sev: string; tipo: string; detalle: string } }) {
  const color = a.sev === "alta" ? "var(--red, #e84040)" : a.sev === "media" ? "var(--amber, #f59e0b)" : "var(--muted, #8b949e)";
  const badgeCls = a.sev === "alta" ? "red" : a.sev === "media" ? "orange" : "gray";
  return (
    <div style={{
      background: "var(--card, #fff)",
      border: "1px solid var(--border, #e2e8f0)",
      borderLeft: `4px solid ${color}`,
      borderRadius: "8px",
      padding: "10px 14px",
      display: "flex",
      gap: "12px",
      alignItems: "flex-start",
      fontSize: "13px",
    }}>
      <span className={`badge badge-${badgeCls}`} style={{ flexShrink: 0, textTransform: "uppercase", fontSize: "10px", letterSpacing: ".3px", marginTop: "2px" }}>
        {a.sev}
      </span>
      <strong style={{ minWidth: "180px", flexShrink: 0 }}>{a.tipo}</strong>
      <span className="muted-copy">{a.detalle}</span>
    </div>
  );
}

function BarCell({ value, total }: { value: number; total: number }) {
  const pctValue = total > 0 ? (value / total) * 100 : 0;
  return (
    <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
      <span style={{ flex: "none", minWidth: "38px" }}>{pctValue.toFixed(1)}%</span>
      <span style={{ flex: 1, background: "var(--border, #e2e8f0)", borderRadius: "4px", height: "6px", overflow: "hidden", minWidth: "60px" }}>
        <span style={{ display: "block", width: `${pctValue}%`, background: "var(--accent, #4a90c4)", height: "100%" }} />
      </span>
    </span>
  );
}

export function AutomaticReport() {
  const [data, setData] = useState<AutomaticReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<Period>("monthly");

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    fetchReport()
      .then((d) => { if (mounted) { setData(d); setLoading(false); } })
      .catch((err: unknown) => { if (mounted) { setError(String(err)); setLoading(false); } });
    return () => { mounted = false; };
  }, []);

  if (loading) {
    return (
      <main className="app-shell">
        <p className="muted-copy">Cargando reporte automático...</p>
      </main>
    );
  }

  if (error || !data) {
    return (
      <main className="app-shell">
        <p className="error-message">No se pudo cargar el reporte: {error}</p>
      </main>
    );
  }

  const p = data.periods[period];
  const g = p.channels.global;
  const generatedAt = new Date(data.generated_at).toLocaleString("es-CL");

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">CRM</span>
          <div>
            <p className="eyebrow">ANALÍTICA</p>
            <h1>Reporte automático</h1>
          </div>
        </div>
        <p className="muted-copy" style={{ fontSize: "12px", alignSelf: "center" }}>
          Generado: {generatedAt}
        </p>
      </header>

      <section className="hero-panel">
        <div>
          <p className="eyebrow">PERÍODO DE ANÁLISIS</p>
          <h2>Vista {PERIOD_LABELS[period]}</h2>
          <p className="muted-copy">{p.date_from} → {p.date_to}</p>
        </div>
        <div className="mode-switch">
          {(Object.keys(PERIOD_LABELS) as Period[]).map((key) => (
            <button key={key} className={period === key ? "active" : ""} onClick={() => setPeriod(key)}>
              {PERIOD_LABELS[key]}
            </button>
          ))}
        </div>
      </section>

      <section className="metrics provider-metrics" aria-label="KPIs del período">
        <article className="metric-card" data-tone="green">
          <p className="metric-label">Suscripciones activas</p>
          <p className="metric-value">{g.active_end.toLocaleString("es-CL")}</p>
          <p className="metric-sub">al cierre del período</p>
        </article>
        <article className="metric-card" data-tone="blue">
          <p className="metric-label">Nuevas altas</p>
          <p className="metric-value">{g.new_subscriptions.toLocaleString("es-CL")}</p>
          <p className="metric-sub">{g.cancellations} bajas en el período</p>
        </article>
        <article className="metric-card" data-tone="gold">
          <p className="metric-label">Recaudación</p>
          <p className="metric-value">{clp(g.revenue)}</p>
          <p className="metric-sub">{g.revenue_count.toLocaleString("es-CL")} cobros aceptados</p>
        </article>
        <article className="metric-card" data-tone={g.rejection_rate > 50 ? "red" : "orange"}>
          <p className="metric-label">Rechazos</p>
          <p className="metric-value">{g.rejected.toLocaleString("es-CL")}</p>
          <p className="metric-sub">{pct(g.rejection_rate)} tasa de rechazo</p>
        </article>
        <article className="metric-card" data-tone={g.churn_rate > 5 ? "red" : "teal"}>
          <p className="metric-label">Churn global</p>
          <p className="metric-value">{pct(g.churn_rate)}</p>
          <p className="metric-sub">{g.cancellations} bajas / {g.active_start} al inicio</p>
        </article>
      </section>

      {p.alerts.length > 0 && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">ALERTAS</p>
              <h3>{p.alerts.length} {p.alerts.length === 1 ? "alerta" : "alertas"} del período</h3>
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "8px", paddingBottom: "4px" }}>
            {p.alerts.map((a, i) => <AlertRow key={i} a={a} />)}
          </div>
        </section>
      )}

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">SUSCRIPCIONES</p>
            <h3>Movimiento por canal</h3>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Canal</th>
                <th>Al inicio</th>
                <th>Nuevas altas</th>
                <th>Bajas</th>
                <th>Al cierre</th>
                <th>Saldo neto</th>
                <th>Churn</th>
              </tr>
            </thead>
            <tbody>
              {CHANNELS.map((ch) => {
                const s = p.channels[ch];
                const saldo = s.new_subscriptions - s.cancellations;
                const isGlobal = ch === "global";
                return (
                  <tr key={ch} style={isGlobal ? { fontWeight: 700 } : undefined}>
                    <td>{CHANNEL_LABELS[ch]}</td>
                    <td>{s.active_start.toLocaleString("es-CL")}</td>
                    <td style={{ color: "var(--green, #2db87a)" }}>
                      {s.new_subscriptions > 0 ? `+${s.new_subscriptions.toLocaleString("es-CL")}` : "0"}
                    </td>
                    <td style={{ color: s.cancellations > 0 ? "var(--red, #e84040)" : undefined }}>
                      {s.cancellations > 0 ? `-${s.cancellations.toLocaleString("es-CL")}` : "0"}
                    </td>
                    <td>{s.active_end.toLocaleString("es-CL")}</td>
                    <td style={{ color: saldo >= 0 ? "var(--green, #2db87a)" : "var(--red, #e84040)", fontWeight: 600 }}>
                      {saldo >= 0 ? "+" : ""}{saldo.toLocaleString("es-CL")}
                    </td>
                    <td><ChurnBadge rate={s.churn_rate} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">RECAUDACIÓN</p>
            <h3>Ingresos por canal</h3>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Canal</th>
                <th>Recaudado</th>
                <th>Aceptados</th>
                <th>Rechazados</th>
                <th>Total intentos</th>
                <th>Tasa rechazo</th>
                <th>% del total</th>
              </tr>
            </thead>
            <tbody>
              {CHANNELS.map((ch) => {
                const s = p.channels[ch];
                const isGlobal = ch === "global";
                return (
                  <tr key={ch} style={isGlobal ? { fontWeight: 700 } : undefined}>
                    <td>{CHANNEL_LABELS[ch]}</td>
                    <td>{clp(s.revenue)}</td>
                    <td>{s.revenue_count.toLocaleString("es-CL")}</td>
                    <td style={{ color: s.rejected > 0 ? "var(--red, #e84040)" : undefined }}>
                      {s.rejected.toLocaleString("es-CL")}
                    </td>
                    <td>{s.total_charges.toLocaleString("es-CL")}</td>
                    <td><RejectBadge rate={s.rejection_rate} /></td>
                    <td>
                      {!isGlobal && g.revenue > 0
                        ? <BarCell value={s.revenue} total={g.revenue} />
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {p.rejection_reasons.length > 0 && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">MOTIVOS DE RECHAZO</p>
              <h3>Razones más frecuentes (TCH)</h3>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Motivo</th>
                  <th>Canal</th>
                  <th>Cantidad</th>
                  <th>Proporción</th>
                </tr>
              </thead>
              <tbody>
                {p.rejection_reasons.map((r, i) => {
                  const total = p.rejection_reasons.reduce((s, x) => s + x.count, 0);
                  return (
                    <tr key={i}>
                      <td>{r.reason}</td>
                      <td>{CHANNEL_LABELS[r.channel] ?? r.channel}</td>
                      <td>{r.count.toLocaleString("es-CL")}</td>
                      <td>
                        <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <span style={{ flex: "none", minWidth: "38px" }}>{(r.count / total * 100).toFixed(1)}%</span>
                          <span style={{ flex: 1, background: "var(--border, #e2e8f0)", borderRadius: "4px", height: "6px", overflow: "hidden", minWidth: "60px" }}>
                            <span style={{ display: "block", width: `${(r.count / total * 100)}%`, background: "var(--red, #e84040)", height: "100%" }} />
                          </span>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <footer style={{ padding: "16px 0 8px", borderTop: "1px solid var(--border, #e2e8f0)", marginTop: "8px" }}>
        <p className="muted-copy" style={{ fontSize: "12px" }}>
          Reporte automático · fuente: base de datos local CRM · {generatedAt}
        </p>
      </footer>
    </main>
  );
}
