import { useId, type Dispatch, type SetStateAction } from "react";
import { day } from "../general/unifiedDisplay";

const FIELDS = [
  ["status", "Estado", "text"], ["date_from", "Fecha de cargo desde", "date"], ["date_to", "Fecha de cargo hasta", "date"],
  ["amount_min", "Monto mínimo", "number"], ["amount_max", "Monto máximo", "number"],
] as const;

/** Uses only the existing staging filter contract; names and RUT are not searchable for charges. */
export function ChargeListFilters({ values, setValues, onResetOffset, open, onToggle }: {
  values: Record<string, string>; setValues: Dispatch<SetStateAction<Record<string, string>>>;
  onResetOffset: () => void; open: boolean; onToggle: () => void;
}) {
  const id = useId();
  const update = (field: string, value: string) => { setValues((current) => ({ ...current, [field]: value })); onResetOffset(); };
  const active = Object.entries(values).filter(([, value]) => value.trim());
  return <section className="vp-charge-filters" aria-label="Buscar y filtrar cargos">
    <div className="vp-charge-search-row">
      <label htmlFor={`${id}-subscription`}>Buscar por ID de suscripción
        <input id={`${id}-subscription`} value={values.subscription_id ?? ""} onChange={(event) => update("subscription_id", event.target.value)} placeholder="Escribe el ID de suscripción" />
      </label>
      <button type="button" className="channel-filter-toggle" aria-expanded={open} aria-controls={`${id}-advanced`} onClick={onToggle}>
        Más filtros{active.filter(([key]) => key !== "subscription_id").length ? ` (${active.filter(([key]) => key !== "subscription_id").length})` : ""}
      </button>
      <button type="button" className="clear-filter-button" disabled={!active.length} onClick={() => { setValues({}); onResetOffset(); }}>Limpiar filtros</button>
    </div>
    <div id={`${id}-advanced`} className="vp-charge-advanced" hidden={!open}>
      {FIELDS.map(([field, name, type]) => <label key={field} htmlFor={`${id}-${field}`}>{name}
        <input id={`${id}-${field}`} type={type} value={values[field] ?? ""} placeholder={field === "status" ? "Ej.: rechazado" : undefined} onChange={(event) => update(field, event.target.value)} />
      </label>)}
    </div>
    {active.length ? <div className="vp-charge-criteria" aria-label="Filtros activos">
      {active.map(([field, value]) => { const name = field === "subscription_id" ? "Suscripción" : FIELDS.find(([key]) => key === field)?.[1] ?? field;
        return <button key={field} type="button" aria-label={`Quitar filtro ${name}`} onClick={() => update(field, "")}>
          {name}: {field.startsWith("date_") ? day(value) : value}<span aria-hidden="true"> ×</span>
        </button>; })}
    </div> : null}
  </section>;
}
