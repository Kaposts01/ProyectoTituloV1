import { useEffect, useRef } from "react";
import type { GeneralClient } from "../shared/types";
import type { GeneralClientDetail } from "./generalClientAdapter";
import { StatusText, canOpenRecordPath, channelText, detailPath } from "../general/unifiedDisplay";
import { Rut } from "../shared/RutCell";

export function MemberDetail({ member, detail, can, onOpenPath, onClose }: {
  member: GeneralClient | null; detail: GeneralClientDetail; can?: (permission: string) => boolean;
  onOpenPath?: (path: string) => void; onClose: () => void;
}) {
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => { title.current?.focus(); }, [detail]);
  return <section className="record-detail member-detail" aria-labelledby="member-detail-title">
    <div className="member-detail-heading">
      <div><h2 id="member-detail-title" tabIndex={-1} ref={title}>{member?.name || "Ficha del socio"}</h2><p>RUT: <Rut value={detail.rut} /></p></div>
      <button type="button" className="secondary-button" onClick={onClose}>← Volver a socios</button>
    </div>
    {(["subscriptions", "charges", "transactions"] as const).map((section) => {
      const entity = section === "subscriptions" ? "subscription" : section === "charges" ? "charge" : "payment";
      const heading = section === "subscriptions" ? "Suscripciones" : section === "charges" ? "Cobros" : "Pagos";
      return <section key={section} className="member-related" aria-label={`${heading} del socio`}>
        <h3>{heading} <span className="muted-copy">({detail[section].length})</span></h3>
        {detail[section].length === 0 ? <p className="muted-copy">Sin registros relacionados.</p> : <>
          <div className="table-wrap"><table><thead><tr><th>Canal</th><th>Estado</th><th>Monto de origen</th><th>Detalle</th></tr></thead><tbody>
            {detail[section].map((item) => {
              const path = detailPath(entity, item.portal.toLowerCase(), item.externalId);
              const allowed = path && can && canOpenRecordPath(path, can);
              return <tr key={`${item.portal}-${item.externalId}`}><td>{channelText(item.portal.toLowerCase())}</td><td><StatusText value={item.status} /></td>
                <td className="num">{item.amount === null || item.amount === "" ? "—" : Number.isFinite(Number(item.amount)) ? Number(item.amount).toLocaleString("es-CL") : item.amount}</td>
                <td>{allowed && onOpenPath ? <button className="record-link" type="button" onClick={() => onOpenPath(path)}>{`Ver ${entity === "subscription" ? "suscripción" : entity === "charge" ? "cobro" : "pago"}`}</button>
                  : <span className="muted-copy">{path ? "Sin acceso a la ficha del canal" : "Detalle no disponible"}</span>}
                  <details className="member-record-ids"><summary>Identificadores</summary><p>ID de origen: {item.externalId || "—"}<br />ID interno: {item.internalId || "—"}</p></details>
                </td></tr>;
            })}
          </tbody></table></div>
          {detail[section].some((item) => item.amount !== null && item.amount !== "") ? <p className="muted-copy">Esta ficha no informa la moneda de los importes.</p> : null}
        </>}
      </section>;
    })}
    <details className="member-record-ids"><summary>Identificadores de cliente por canal</summary>
      {detail.clients.map((item) => <p key={`${item.portal}-${item.externalId}`}>{channelText(item.portal.toLowerCase())}: {item.externalId || "—"} · ID interno: {item.internalId || "—"}</p>)}
      {detail.clients.length === 0 ? <p>Sin registros relacionados.</p> : null}
    </details>
  </section>;
}
