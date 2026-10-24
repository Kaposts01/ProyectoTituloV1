import type React from "react";
import { METRIC_COLORS } from "../shared/constants";

export function KpiCard({ label, value, caption, tone }: { label: string; value: string; caption?: string; tone: string }) {
  const accent = METRIC_COLORS[tone] ?? "#4a90c4";
  return (
    <article className="metric-card kpi-card" style={{ "--accent": accent } as React.CSSProperties}>
      <p className="metric-label">{label}</p>
      <strong className="metric-value kpi-value">{value}</strong>
      {caption ? <span className="metric-amount">{caption}</span> : null}
    </article>
  );
}
