import { useState } from "react";
import type { SortDirection, StagingRecord, VirtualPosDetailColumn } from "../shared/types";

export function VirtualPosDetailTable({
  records,
  columns,
  empty,
}: {
  records: StagingRecord[];
  columns: VirtualPosDetailColumn[];
  empty: string;
}) {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<{ index: number; direction: SortDirection } | null>(null);
  const visible = records
    .filter((record) => columns.every((column, index) => {
      if (column.filterable === false) return true;
      const value = filters[String(index)]?.trim().toLocaleLowerCase() ?? "";
      const from = filters[`${index}:from`] ?? "";
      const to = filters[`${index}:to`] ?? "";
      const cell = column.value(record);
      if (column.kind === "amount") {
        const amount = Number(cell);
        return (!from || (Number.isFinite(amount) && amount >= Number(from))) && (!to || (Number.isFinite(amount) && amount <= Number(to)));
      }
      if (column.kind === "date") {
        const day = cell.slice(0, 10);
        return (!from || day >= from) && (!to || day <= to);
      }
      return !value || cell.toLocaleLowerCase().includes(value);
    }))
    .sort((left, right) => {
      if (!sort) return 0;
      const column = columns[sort.index];
      const leftValue = column.value(left);
      const rightValue = column.value(right);
      const comparison = column.kind === "amount"
        ? Number(leftValue) - Number(rightValue)
        : column.kind === "date"
          ? leftValue.slice(0, 10).localeCompare(rightValue.slice(0, 10))
          : leftValue.localeCompare(rightValue, "es", { sensitivity: "base" });
      return sort.direction === "asc" ? comparison : -comparison;
    });
  const update = (key: string, value: string) => setFilters((current) => ({ ...current, [key]: value }));
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map((column, index) => <th key={column.label}>{column.filterable === false ? column.label : <button className={`table-sort-button${sort?.index === index ? " active" : ""}`} onClick={() => setSort((current) => current?.index === index ? { index, direction: current.direction === "asc" ? "desc" : "asc" } : { index, direction: "asc" })}>{column.label}<span aria-hidden="true">{sort?.index === index ? (sort.direction === "asc" ? "↑" : "↓") : "↕"}</span></button>}</th>)}</tr>
          <tr className="table-column-filters">{columns.map((column, index) => {
            if (column.filterable === false) return <th key={column.label} />;
            if (column.kind === "amount") return <th key={column.label} className="range-filter"><input aria-label={`${column.label} mínimo`} type="number" placeholder="Mín." value={filters[`${index}:from`] ?? ""} onChange={(event) => update(`${index}:from`, event.target.value)} /><input aria-label={`${column.label} máximo`} type="number" placeholder="Máx." value={filters[`${index}:to`] ?? ""} onChange={(event) => update(`${index}:to`, event.target.value)} /></th>;
            if (column.kind === "date") return <th key={column.label} className="range-filter"><input aria-label={`${column.label} desde`} type="date" value={filters[`${index}:from`] ?? ""} onChange={(event) => update(`${index}:from`, event.target.value)} /><input aria-label={`${column.label} hasta`} type="date" value={filters[`${index}:to`] ?? ""} onChange={(event) => update(`${index}:to`, event.target.value)} /></th>;
            return <th key={column.label}><input aria-label={`Buscar por ${column.label}`} placeholder="Buscar" value={filters[String(index)] ?? ""} onChange={(event) => update(String(index), event.target.value)} /></th>;
          })}</tr>
        </thead>
        <tbody>
          {visible.map((record) => <tr key={record.id}>{columns.map((column) => <td key={column.label}>{column.render ? column.render(record) : column.value(record)}</td>)}</tr>)}
          {!visible.length ? <tr><td colSpan={columns.length}>{empty}</td></tr> : null}
        </tbody>
      </table>
    </div>
  );
}
