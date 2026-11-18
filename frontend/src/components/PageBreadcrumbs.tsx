import type { MouseEvent } from "react";
import type { PageCrumb } from "../pageNavigation";

export function PageBreadcrumbs({ crumbs, onNavigate }: { crumbs: PageCrumb[]; onNavigate: (path: string) => void }) {
  const follow = (event: MouseEvent<HTMLAnchorElement>, href: string) => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigate(href);
  };
  return (
    <nav className="page-breadcrumbs" aria-label="Ruta de navegación">
      <ol>
        {crumbs.map((crumb, index) => (
          <li key={`${index}:${crumb.label}`}>
            {index > 0 ? <span className="breadcrumb-separator" aria-hidden="true">/</span> : null}
            {crumb.href ? <a href={crumb.href} onClick={(event) => follow(event, crumb.href!)}>{crumb.label}</a>
              : <span aria-current={index === crumbs.length - 1 ? "page" : undefined}>{crumb.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}
