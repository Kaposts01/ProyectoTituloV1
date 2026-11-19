/** Keep React useId references stable while preserving distinct IDs and their relationships. */
export function normalizeReactIds(html: string): string {
  const ids = new Map<string, string>();
  return html.replace(/_r_[a-z0-9]+_/gi, (id) => {
    if (!ids.has(id)) ids.set(id, `react-id-${ids.size + 1}`);
    return ids.get(id)!;
  });
}
