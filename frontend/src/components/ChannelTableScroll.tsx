import { type ReactNode } from "react";

/** Native two-axis scrolling keeps the rows bounded without adding a second toolbar. */
export function ChannelTableScroll({ label, children }: { label: string; children: ReactNode }) {
  return <div className="channel-table-frame">
    <div className="table-wrap channel-table-scroll" role="region" aria-label={`Tabla de ${label}`} tabIndex={0}>
      {children}
    </div>
  </div>;
}
