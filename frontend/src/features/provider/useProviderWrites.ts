import { useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { deleteJson, friendlyError, postJson, putJson } from "../../api";
import type { StagingRecord, StagingResponse } from "../shared/types";
import { refreshCsrfToken } from "../shared/utils";
import { providerEditFields } from "../virtualpos/constants";

/**
 * Edición, eliminación y cambio de estado de registros de Toku y Payku: estado de cada diálogo y sus
 * manejadores. Se llama desde AppCore porque actualizan la lista de registros (y la ficha de transacción de
 * VirtualPOS abre aquí su diálogo de eliminación).
 */
export function useProviderWrites(ctx: { setRecords: Dispatch<SetStateAction<StagingResponse>> }) {
  const { setRecords } = ctx;
  const [editingProviderRecord, setEditingProviderRecord] = useState<{
    record: StagingRecord;
    source: string;
    resourceType: string;
  } | null>(null);
  const [savingProviderEdit, setSavingProviderEdit] = useState(false);
  const [providerEditError, setProviderEditError] = useState<string | null>(null);
  const [deletingRecord, setDeletingRecord] = useState<{
    record: StagingRecord;
    source: string;
    resourceType: string;
  } | null>(null);
  const [savingProviderDelete, setSavingProviderDelete] = useState(false);
  const [providerDeleteError, setProviderDeleteError] = useState<string | null>(null);
  const [managingTokuSub, setManagingTokuSub] = useState<StagingRecord | null>(null);
  const [savingTokuSubStatus, setSavingTokuSubStatus] = useState(false);
  const [tokuSubStatusError, setTokuSubStatusError] = useState<string | null>(null);

  async function saveProviderEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingProviderRecord || savingProviderEdit) return;
    setProviderEditError(null);
    const { record, source, resourceType } = editingProviderRecord;
    const formData = new FormData(event.currentTarget);
    const fields = providerEditFields[source]?.[resourceType] ?? [];
    const changes: Record<string, unknown> = {};
    for (const field of fields) {
      const val = String(formData.get(field.name) ?? "").trim();
      const current = String(record.payload[field.name] ?? "").trim();
      if (val !== "" && val !== current) changes[field.name] = field.type === "number" ? Number(val) : val;
    }
    if (Object.keys(changes).length === 0) { setEditingProviderRecord(null); return; }
    setSavingProviderEdit(true);
    try {
      await refreshCsrfToken();
      let updatedPayload: Record<string, unknown> = record.payload;
      if (source === "toku" && resourceType === "customer") {
        const result = await putJson<{ external_id: string; payload: Record<string, unknown> }>(
          `/api/v1/writes/toku/customers/${encodeURIComponent(record.external_id)}`,
          changes,
        );
        updatedPayload = result.payload;
      } else if (source === "payku" && resourceType === "client") {
        const result = await putJson<{ external_id: string; payload: Record<string, unknown> }>(
          `/api/v1/writes/payku/clients/${encodeURIComponent(record.external_id)}`,
          changes,
        );
        updatedPayload = result.payload;
      }
      setEditingProviderRecord(null);
      setRecords((prev) => ({
        ...prev,
        items: prev.items.map((item) =>
          item.external_id === record.external_id && item.source === source
            ? { ...item, payload: updatedPayload }
            : item,
        ),
      }));
    } catch (err) {
      setProviderEditError(friendlyError(err, "No se pudo guardar el cambio."));
    } finally {
      setSavingProviderEdit(false);
    }
  }

  async function confirmProviderDelete() {
    if (!deletingRecord || savingProviderDelete) return;
    setProviderDeleteError(null);
    const { record, source, resourceType } = deletingRecord;
    setSavingProviderDelete(true);
    try {
      await refreshCsrfToken();
      if (source === "toku" && resourceType === "customer") {
        await deleteJson<{ external_id: string; status: string }>(
          `/api/v1/writes/toku/customers/${encodeURIComponent(record.external_id)}`,
        );
        setDeletingRecord(null);
        setRecords((prev) => ({
          ...prev,
          items: prev.items.map((item) =>
            item.external_id === record.external_id && item.source === source
              ? { ...item, payload: { ...item.payload, status: "deleted" } }
              : item,
          ),
        }));
      } else if (source === "payku" && resourceType === "client") {
        await deleteJson<{ external_id: string; status: string }>(
          `/api/v1/writes/payku/clients/${encodeURIComponent(record.external_id)}`,
        );
        setDeletingRecord(null);
        setRecords((prev) => ({
          ...prev,
          items: prev.items.map((item) =>
            item.external_id === record.external_id && item.source === source
              ? { ...item, payload: { ...item.payload, status: "deleted" } }
              : item,
          ),
        }));
      } else if (source === "payku" && resourceType === "subscription") {
        await deleteJson<{ external_id: string; status: string }>(
          `/api/v1/writes/payku/subscriptions/${encodeURIComponent(record.external_id)}`,
        );
        setDeletingRecord(null);
        setRecords((prev) => ({
          ...prev,
          items: prev.items.map((item) =>
            item.external_id === record.external_id && item.source === source
              ? { ...item, payload: { ...item.payload, status: "cancelled" } }
              : item,
          ),
        }));
      }
    } catch (err) {
      setProviderDeleteError(friendlyError(err, "No se pudo eliminar el registro."));
    } finally {
      setSavingProviderDelete(false);
    }
  }

  async function changeTokuSubscriptionStatus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!managingTokuSub || savingTokuSubStatus) return;
    setTokuSubStatusError(null);
    const formData = new FormData(event.currentTarget);
    const status = String(formData.get("status") ?? "").trim();
    if (!status) { setTokuSubStatusError("Selecciona un estado."); return; }
    const subId = String(managingTokuSub.payload.id ?? managingTokuSub.external_id);
    setSavingTokuSubStatus(true);
    try {
      await refreshCsrfToken();
      const result = await postJson<{ external_id: string; status: string; payload: Record<string, unknown> }>(
        `/api/v1/writes/toku/subscriptions/${encodeURIComponent(subId)}/status`,
        { status },
      );
      const updatedPayload = result.payload;
      setManagingTokuSub(null);
      setRecords((prev) => ({
        ...prev,
        items: prev.items.map((item) =>
          item.external_id === managingTokuSub.external_id && item.source === "toku"
            ? { ...item, payload: { ...item.payload, ...updatedPayload, status: result.status } }
            : item,
        ),
      }));
    } catch (err) {
      setTokuSubStatusError(friendlyError(err, "No se pudo cambiar el estado."));
    } finally {
      setSavingTokuSubStatus(false);
    }
  }

  return {
    editingProviderRecord,
    setEditingProviderRecord,
    savingProviderEdit,
    setSavingProviderEdit,
    providerEditError,
    setProviderEditError,
    deletingRecord,
    setDeletingRecord,
    savingProviderDelete,
    setSavingProviderDelete,
    providerDeleteError,
    setProviderDeleteError,
    managingTokuSub,
    setManagingTokuSub,
    savingTokuSubStatus,
    setSavingTokuSubStatus,
    tokuSubStatusError,
    setTokuSubStatusError,
    saveProviderEdit,
    confirmProviderDelete,
    changeTokuSubscriptionStatus,
  };
}

export type ProviderWritesState = ReturnType<typeof useProviderWrites>;
