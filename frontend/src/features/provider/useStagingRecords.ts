import { useEffect, useState } from "react";
import { getJson, friendlyError } from "../../api";
import { useDebouncedValue } from "../../hooks";
import type { ProviderSection } from "../../routes";
import { RECORDS_PAGE_SIZE } from "../shared/utils";
import { filterFieldForColumn } from "../virtualpos/constants";
import type { AuthSession, SortDirection, StagingResponse } from "../shared/types";

/**
 * Lista de registros de staging de la sección activa: datos, paginación, filtros, orden y cuenta de
 * VirtualPOS. Se llama desde AppCore porque las escrituras y las fichas actualizan `records` y para que
 * los filtros sobrevivan a la navegación igual que antes de la extracción.
 */
export function useStagingRecords(ctx: {
  session: AuthSession | null | undefined;
  activeSection: ProviderSection | null;
  setError: (message: string | null) => void;
  setLoading: (loading: boolean) => void;
}) {
  const { session, activeSection, setError, setLoading } = ctx;
  const [records, setRecords] = useState<StagingResponse>({
    items: [],
    total: 0,
    offset: 0,
    limit: RECORDS_PAGE_SIZE,
  });
  const [recordsOffset, setRecordsOffset] = useState(0);
  const [statusValues, setStatusValues] = useState<string[]>([]);
  const [filterField, setFilterField] = useState("");
  const [filterQuery, setFilterQuery] = useState("");
  const [vpColumnFilters, setVpColumnFilters] = useState<Record<string, string>>({});
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [vpPlatform, setVpPlatform] = useState<"all" | "virtualpos1" | "virtualpos2">("all");
  const debouncedFilterQuery = useDebouncedValue(filterQuery);
  const debouncedVpColumnFilters = useDebouncedValue(vpColumnFilters);

  useEffect(() => {
    if (!session || !activeSection) return;
    if (filterQuery !== debouncedFilterQuery) return;
    let mounted = true;
    const controller = new AbortController();
    const effectiveSource =
      activeSection.source === "virtualpos" && vpPlatform !== "all"
        ? vpPlatform
        : activeSection.source;
    const params = new URLSearchParams({
      source: effectiveSource,
      resource_type: activeSection.resource,
      offset: String(recordsOffset),
      limit: String(RECORDS_PAGE_SIZE),
    });
    const effectiveFilterQuery = filterQuery ? debouncedFilterQuery : "";
    if (activeSection.source === "virtualpos") {
      for (const [field, value] of Object.entries(debouncedVpColumnFilters)) {
        if (!value.trim()) continue;
        if (field.endsWith("_min") || field.endsWith("_max") || field.endsWith("_from") || field.endsWith("_to")) {
          params.set(field, value.trim());
        } else {
          params.append("filters", `${field}:${value.trim()}`);
        }
      }
    } else if (filterField && effectiveFilterQuery.trim()) {
      params.set("filter_field", filterField);
      params.set("query", effectiveFilterQuery.trim());
    }
    const sortField = sortColumn
      ? filterFieldForColumn(activeSection.source, activeSection.resource, sortColumn)
      : null;
    if (sortField) {
      params.set("sort_field", sortField);
      params.set("sort_direction", sortDirection);
    }
    const path = `/api/v1/staging/records?${params}`;
    setLoading(true);
    getJson<StagingResponse>(path, controller.signal)
      .then((data) => {
        if (mounted) {
          setRecords((current) => recordsOffset === 0
            ? data
            : { ...data, items: [...current.items, ...data.items.filter((item) => !current.items.some((existing) => existing.id === item.id))] });
        }
      })
      .catch((err: unknown) => {
        if (mounted && !(err instanceof DOMException && err.name === "AbortError")) setError(friendlyError(err, "No se pudieron cargar los registros."));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
      controller.abort();
    };
  }, [session, activeSection, filterField, filterQuery, debouncedFilterQuery, debouncedVpColumnFilters, sortColumn, sortDirection, vpPlatform, recordsOffset, setError, setLoading]);

  useEffect(() => {
    if (!session || !activeSection || !["status", "secondary_status"].includes(filterField)) {
      setStatusValues([]);
      return;
    }
    const source = activeSection.source === "virtualpos" && vpPlatform !== "all"
      ? vpPlatform
      : activeSection.source;
    const params = new URLSearchParams({
      source,
      resource_type: activeSection.resource,
      filter_field: filterField,
    });
    getJson<{ values: string[] }>(`/api/v1/staging/records/filter-values?${params}`)
      .then((data) => setStatusValues(data.values))
      .catch((err: unknown) => setError(friendlyError(err, "No se pudieron cargar los estados.")));
  }, [session, activeSection, filterField, vpPlatform, setError]);

  return {
    records,
    setRecords,
    recordsOffset,
    setRecordsOffset,
    statusValues,
    setStatusValues,
    filterField,
    setFilterField,
    filterQuery,
    setFilterQuery,
    vpColumnFilters,
    setVpColumnFilters,
    sortColumn,
    setSortColumn,
    sortDirection,
    setSortDirection,
    vpPlatform,
    setVpPlatform,
  };
}

export type StagingRecordsState = ReturnType<typeof useStagingRecords>;
