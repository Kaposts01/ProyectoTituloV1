/**
 * Íconos del menú lateral: SVG propios en línea (el proyecto no tiene librería de íconos y no se agrega una
 * dependencia por ~18 trazos). Trazo de 1.75 px en `currentColor`, caja de 20 px, decorativos (`aria-hidden`):
 * el nombre accesible de cada botón es siempre su texto.
 */

export type IconName =
  | "summary" | "members" | "subscriptions" | "charges"
  | "recovery" | "billing" | "cancellations"
  | "sync" | "admin" | "report"
  | "channels" | "chevron" | "search" | "pin" | "sun" | "moon" | "profile" | "logout" | "close";

const PATHS: Record<IconName, string[]> = {
  summary: ["M4 4h7v7H4z", "M13 4h7v4h-7z", "M13 10h7v10h-7z", "M4 13h7v7H4z"],
  members: ["M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z", "M2.5 20c.6-3.4 3.2-5.5 6.5-5.5s5.9 2.1 6.5 5.5", "M16 4.3a3.5 3.5 0 0 1 0 6.4", "M18 14.8c1.9.7 3.1 2.5 3.5 5.2"],
  subscriptions: ["M5 5.5h14a1 1 0 0 1 1 1V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6.5a1 1 0 0 1 1-1z", "M4 10h16", "M8.5 3.5v4", "M15.5 3.5v4", "M9.5 15l2 2 3.5-3.5"],
  charges: ["M3 7.5A2.5 2.5 0 0 1 5.5 5h13A2.5 2.5 0 0 1 21 7.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z", "M3 10h18", "M7 15h3"],
  recovery: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M5.6 5.6l3.6 3.6", "M14.8 14.8l3.6 3.6", "M18.4 5.6l-3.6 3.6", "M9.2 14.8l-3.6 3.6"],
  billing: ["M4 8h14", "M15 5l3 3-3 3", "M20 16H6", "M9 13l-3 3 3 3"],
  cancellations: ["M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z", "M2.5 20c.6-3.4 3.2-5.5 6.5-5.5 1.6 0 3 .5 4.1 1.3", "M16.5 15.5l4 4", "M20.5 15.5l-4 4"],
  sync: ["M20 12a8 8 0 0 1-14.3 4.9", "M4 12a8 8 0 0 1 14.3-4.9", "M18.5 3v4.2h-4.2", "M5.5 21v-4.2h4.2"],
  admin: ["M12 3l7.5 3v5.5c0 4.5-3.2 8.2-7.5 9.5-4.3-1.3-7.5-5-7.5-9.5V6z", "M9 12l2 2 4-4"],
  report: ["M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z", "M14 3v5h5", "M9.5 13h5", "M9.5 17h5"],
  channels: ["M12 3l9 4.5-9 4.5-9-4.5z", "M3 12l9 4.5 9-4.5", "M3 16.5L12 21l9-4.5"],
  chevron: ["M9 6l6 6-6 6"],
  search: ["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z", "M16 16l4.5 4.5"],
  pin: ["M4 5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z", "M9.5 4v16", "M13.5 10l2 2-2 2"],
  sun: ["M12 16.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9z", "M12 2.5v2", "M12 19.5v2", "M2.5 12h2", "M19.5 12h2", "M5.3 5.3l1.4 1.4", "M17.3 17.3l1.4 1.4", "M5.3 18.7l1.4-1.4", "M17.3 6.7l1.4-1.4"],
  moon: ["M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"],
  profile: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 12.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M6.4 18.2c1.2-2 3.2-3.2 5.6-3.2s4.4 1.2 5.6 3.2"],
  logout: ["M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4", "M10 16l-4-4 4-4", "M6 12h10"],
  close: ["M6 6l12 12", "M18 6L6 18"],
};

export function NavIcon({ name, className = "sidebar-icon" }: { name: IconName; className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" data-icon={name}>
      {PATHS[name].map((d) => <path key={d} d={d} />)}
    </svg>
  );
}
