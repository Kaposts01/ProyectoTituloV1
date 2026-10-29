import { label } from "../../i18n/label";
import { parseMonth } from "./summaryFormat";
import type { SummaryChannel } from "./summaryTypes";

/** Selector de mes (`<input type="month">`) con el botón «Mes actual» cuando hay un mes elegido. */
export function MonthPicker({ value, picked, onChange, onReset }: {
  /** Mes que se muestra (el elegido o, si no hay, el actual del servidor). */
  value: string;
  /** ¿El usuario eligió un mes? Con `false` se está viendo el mes actual. */
  picked: boolean;
  onChange: (month: string) => void;
  onReset: () => void;
}) {
  return (
    <div className="summary-control">
      <label htmlFor="summary-month" className="summary-control-label">Mes</label>
      <div className="summary-month-row">
        <input
          id="summary-month"
          type="month"
          className="summary-month-input mono"
          value={value}
          onChange={(event) => { if (parseMonth(event.target.value)) onChange(event.target.value); }}
        />
        {picked ? <button type="button" className="secondary-button summary-reset" onClick={onReset}>Mes actual</button> : null}
      </div>
    </div>
  );
}

/**
 * Filtro de canales: una casilla por canal PERMITIDO (los que el servidor devolvió sin filtro). No deja la
 * selección vacía: la última casilla marcada queda deshabilitada.
 */
export function ChannelFilter({ available, selected, onToggle }: {
  available: SummaryChannel[];
  /** `null` = todos. */
  selected: SummaryChannel[] | null;
  onToggle: (channel: SummaryChannel) => void;
}) {
  if (available.length === 0) return null;
  const active = selected ?? available;
  return (
    <fieldset className="summary-control summary-channels">
      <legend className="summary-control-label">Canales</legend>
      <div className="summary-channel-list">
        {available.map((channel) => {
          const checked = active.includes(channel);
          return (
            <label key={channel} className={`summary-channel${checked ? " checked" : ""}`}>
              <input type="checkbox" checked={checked} disabled={checked && active.length === 1} onChange={() => onToggle(channel)} />
              <span>{label("channel", channel)}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
