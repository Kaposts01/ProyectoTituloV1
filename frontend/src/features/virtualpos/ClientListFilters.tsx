import { useId, type Dispatch, type SetStateAction } from "react";

const EXTRA = [["email", "Correo electrónico"], ["phone_number", "Teléfono"], ["status", "Estado"], ["uuid", "ID de cliente"]] as const;
const NAMES: Record<string, string> = { name: "Nombre", social_id: "RUT o documento", ...Object.fromEntries(EXTRA) };

/** Combines the existing staging fields with AND; personal terms stay in memory. */
export function ClientListFilters({ values, setValues, onResetOffset, open, onToggle }: {
  values: Record<string, string>; setValues: Dispatch<SetStateAction<Record<string, string>>>;
  onResetOffset: () => void; open: boolean; onToggle: () => void;
}) {
  const id = useId();
  const update = (field: string, value: string) => { setValues((current) => ({ ...current, [field]: value })); onResetOffset(); };
  const active = Object.entries(values).filter(([, value]) => value.trim());
  const extraCount = active.filter(([key]) => EXTRA.some(([field]) => field === key)).length;
  return <section className="vp-charge-filters vp-client-filters" aria-label="Buscar y filtrar clientes">
    <div className="vp-charge-search-row">
      <label htmlFor={`${id}-name`}>Nombre del cliente
        <input id={`${id}-name`} value={values.name ?? ""} onChange={(e) => update("name", e.target.value)} placeholder="Escribe nombre o apellido" autoComplete="off" />
      </label>
      <label htmlFor={`${id}-rut`}>RUT o documento
        <input id={`${id}-rut`} value={values.social_id ?? ""} onChange={(e) => update("social_id", e.target.value)} placeholder="Escribe el RUT o documento" autoComplete="off" />
      </label>
      <button type="button" className="channel-filter-toggle" aria-expanded={open} aria-controls={`${id}-advanced`} onClick={onToggle}>Más filtros{extraCount ? ` (${extraCount})` : ""}</button>
      <button type="button" className="clear-filter-button" disabled={!active.length} onClick={() => { setValues({}); onResetOffset(); }}>Limpiar filtros</button>
    </div>
    <div id={`${id}-advanced`} className="vp-charge-advanced" hidden={!open}>
      {EXTRA.map(([field, name]) => <label key={field} htmlFor={`${id}-${field}`}>{name}
        <input id={`${id}-${field}`} value={values[field] ?? ""} autoComplete="off" inputMode={field === "phone_number" ? "tel" : field === "email" ? "email" : "text"} onChange={(e) => update(field, e.target.value)} />
      </label>)}
    </div>
    {active.length ? <div className="vp-charge-criteria" aria-label="Filtros activos">
      {active.map(([field, value]) => <button key={field} type="button" aria-label={`Quitar filtro ${NAMES[field] ?? field}`} onClick={() => update(field, "")}>{NAMES[field] ?? field}: {value}<span aria-hidden="true"> ×</span></button>)}
    </div> : null}
  </section>;
}
