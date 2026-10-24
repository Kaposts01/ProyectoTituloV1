import type React from "react";
import { METRIC_COLORS } from "../shared/constants";

export function Metric({
  label,
  value,
  tone,
  amount,
  mode = "count",
}: {
  label: string;
  value: number;
  tone: string;
  amount?: number;
  mode?: "count" | "amount";
}) {
  const accent = METRIC_COLORS[tone] ?? "#4a90c4";
  const showAmountPrimary = mode === "amount" && amount !== undefined;
  return (
    <article className="metric-card" style={{ "--accent": accent } as React.CSSProperties}>
      <p className="metric-label">{label}</p>
      {showAmountPrimary ? (
        <>
          <strong className="metric-value metric-value-money">${amount!.toLocaleString("es-CL")}</strong>
          <span className="metric-amount">{value.toLocaleString("es-CL")} registros</span>
        </>
      ) : (
        <>
          <strong className="metric-value">{value.toLocaleString("es-CL")}</strong>
          {amount !== undefined ? <span className="metric-amount">${amount.toLocaleString("es-CL")}</span> : null}
        </>
      )}
    </article>
  );
}
