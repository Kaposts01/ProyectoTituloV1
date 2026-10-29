import { useRef, type KeyboardEvent } from "react";
import type { ChartRange } from "./chartRows";

const ORDER: ChartRange[] = ["12m", "year", "all"];

/**
 * Selector de rango del gráfico de evolución: «Últimos 12 meses / Año / Todo».
 * Es independiente del gráfico: el padre guarda el valor y recorta los datos con
 * `filterByRange(data, value)` antes de pasarlos a `ChannelChart`.
 * Accesible como grupo de radios: Tab entra una sola vez, flechas/Inicio/Fin cambian la opción.
 */
export function ChartRangeSelector({ value, onChange, yearLabel = "Año", ariaLabel = "Rango del gráfico" }: {
  value: ChartRange;
  onChange: (range: ChartRange) => void;
  /** Texto de la opción de año, p. ej. «Año 2026». */
  yearLabel?: string;
  ariaLabel?: string;
}) {
  const labels: Record<ChartRange, string> = { "12m": "Últimos 12 meses", year: yearLabel, all: "Todo" };
  const refs = useRef<Record<ChartRange, HTMLButtonElement | null>>({ "12m": null, year: null, all: null });

  const move = (to: ChartRange) => {
    onChange(to);
    refs.current[to]?.focus();
  };
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, current: ChartRange) => {
    const i = ORDER.indexOf(current);
    if (e.key === "ArrowRight" || e.key === "ArrowDown") move(ORDER[(i + 1) % ORDER.length]);
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") move(ORDER[(i + ORDER.length - 1) % ORDER.length]);
    else if (e.key === "Home") move(ORDER[0]);
    else if (e.key === "End") move(ORDER[ORDER.length - 1]);
    else return;
    e.preventDefault();
  };

  return (
    <div className="chart-range" role="radiogroup" aria-label={ariaLabel}>
      {ORDER.map((r) => (
        <button
          key={r}
          ref={(el) => { refs.current[r] = el; }}
          type="button"
          role="radio"
          aria-checked={value === r}
          tabIndex={value === r ? 0 : -1}
          className={`chart-range-option${value === r ? " active" : ""}`}
          onClick={() => onChange(r)}
          onKeyDown={(e) => onKeyDown(e, r)}
        >
          {labels[r]}
        </button>
      ))}
    </div>
  );
}
