import { useEffect, useState } from "react";
import { getJson, friendlyError } from "../../api";
import { getCached, setCached } from "../../apiCache";
import { defaultYear, normalizeTchSummary } from "../shared/utils";
import type {
  AuthSession, TchClienteDetail, TchClientesResp, TchSuscripcionDetail, TchSuscripcionesResp, TchSummary,
  TchTransaccionDetail, TchTransaccionesResp,
} from "../shared/types";

export type TchViewName = "summary" | "clientes" | "suscripciones" | "transacciones" | "client-detail" | "subscription-detail" | "transaction-detail";

/**
 * Estado y carga de las vistas TCH. Se llama desde AppCore (no desde la vista) para que el estado
 * (modo, año, filtros, páginas) sobreviva a la navegación igual que antes de la extracción.
 */
export function useTch(session: AuthSession | null | undefined) {
  const [tchView, setTchView] = useState<TchViewName | null>(null);
  const [tchRefreshing, setTchRefreshing] = useState(false);
  const [tchSummary, setTchSummary] = useState<TchSummary | null>(null);
  const [tchSubscriptions, setTchSubscriptions] = useState<TchSuscripcionesResp | null>(null);
  const [tchTransactions, setTchTransactions] = useState<TchTransaccionesResp | null>(null);
  const [tchClients, setTchClients] = useState<TchClientesResp | null>(null);
  const [tchLoading, setTchLoading] = useState(false);
  const [tchError, setTchError] = useState<string | null>(null);
  const [tchSubscriptionPage, setTchSubscriptionPage] = useState(1);
  const [tchTransactionPage, setTchTransactionPage] = useState(1);
  const [tchSubscriptionStatusFilter, setTchSubscriptionStatusFilter] = useState("");
  const [tchClientFilter, setTchClientFilter] = useState("");
  const [tchClientPage, setTchClientPage] = useState(1);
  const [tchTransactionPeriodFilter, setTchTransactionPeriodFilter] = useState("");
  const [tchMode, setTchMode] = useState<"count" | "amount">("count");
  const [tchYear, setTchYear] = useState<number | null>(null);
  const [tchSubscriptionDetail, setTchSubscriptionDetail] = useState<TchSuscripcionDetail | null>(null);
  const [tchTransactionDetail, setTchTransactionDetail] = useState<TchTransaccionDetail | null>(null);
  const [tchClientDetail, setTchClientDetail] = useState<TchClienteDetail | null>(null);

  function showTchTransaction(id: string) {
    setTchClientDetail(null);
    setTchSubscriptionDetail(null);
    setTchTransactionDetail({ id } as TchTransaccionDetail);
    setTchView("transaction-detail");
  }

  function showTchClient(rut: string) {
    setTchSubscriptionDetail(null);
    setTchTransactionDetail(null);
    setTchClientDetail({ rut, suscripciones: [] } as unknown as TchClienteDetail);
    setTchView("client-detail");
  }

  useEffect(() => {
    if (!session || !tchView) return;
    let mounted = true;
    setTchError(null);
    if (tchView === "summary") {
      const cached = getCached<TchSummary>("tch:summary", 10 * 60 * 1000);
      if (cached) {
        const summary = normalizeTchSummary(cached);
        setTchSummary(summary);
        setTchYear((current) => current ?? defaultYear(summary.years));
        setTchLoading(false);
        return () => { mounted = false; };
      }
      setTchLoading(true);
      getJson<TchSummary>("/api/v1/tch/summary")
        .then((d) => {
          if (!mounted) return;
          const summary = normalizeTchSummary(d);
          setCached("tch:summary", summary);
          setTchSummary(summary);
          setTchYear((current) => current ?? defaultYear(summary.years));
        })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar el resumen TCH.")); })
        .finally(() => { if (mounted) { setTchLoading(false); setTchRefreshing(false); } });
    } else if (tchView === "clientes") {
      setTchLoading(true);
      const params = new URLSearchParams({ limit: "50", page: String(tchClientPage) });
      if (tchClientFilter) params.set("nombre", tchClientFilter);
      getJson<TchClientesResp>(`/api/v1/tch/clientes?${params}`)
        .then((d) => { if (mounted) setTchClients(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar los clientes TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "suscripciones") {
      setTchLoading(true);
      const params = new URLSearchParams({ limit: "50", page: String(tchSubscriptionPage) });
      if (tchSubscriptionStatusFilter) params.set("estado", tchSubscriptionStatusFilter);
      getJson<TchSuscripcionesResp>(`/api/v1/tch/suscripciones?${params}`)
        .then((d) => { if (mounted) setTchSubscriptions(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar las suscripciones TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "transacciones") {
      setTchLoading(true);
      const params = new URLSearchParams({ limit: "100", page: String(tchTransactionPage) });
      if (tchTransactionPeriodFilter) params.set("periodo", tchTransactionPeriodFilter);
      getJson<TchTransaccionesResp>(`/api/v1/tch/transacciones?${params}`)
        .then((d) => { if (mounted) setTchTransactions(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar las transacciones TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "subscription-detail" && tchSubscriptionDetail) {
      setTchLoading(true);
      getJson<TchSuscripcionDetail>(`/api/v1/tch/suscripciones/${tchSubscriptionDetail.numero_ficha}`)
        .then((d) => { if (mounted) setTchSubscriptionDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "transaction-detail" && tchTransactionDetail) {
      setTchLoading(true);
      getJson<TchTransaccionDetail>(`/api/v1/tch/transacciones/${tchTransactionDetail.id}`)
        .then((d) => { if (mounted) setTchTransactionDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "client-detail" && tchClientDetail) {
      setTchLoading(true);
      getJson<TchClienteDetail>(`/api/v1/tch/clientes/${encodeURIComponent(tchClientDetail.rut)}`)
        .then((d) => { if (mounted) setTchClientDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha del cliente TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    }
    return () => { mounted = false; };
  }, [session, tchView, tchClientPage, tchClientFilter, tchSubscriptionPage, tchSubscriptionStatusFilter, tchTransactionPage, tchTransactionPeriodFilter, tchSubscriptionDetail?.numero_ficha, tchTransactionDetail?.id, tchClientDetail?.rut]);

  return {
    tchView,
    setTchView,
    tchRefreshing,
    setTchRefreshing,
    tchSummary,
    setTchSummary,
    tchSubscriptions,
    setTchSubscriptions,
    tchTransactions,
    setTchTransactions,
    tchClients,
    setTchClients,
    tchLoading,
    setTchLoading,
    tchError,
    setTchError,
    tchSubscriptionPage,
    setTchSubscriptionPage,
    tchTransactionPage,
    setTchTransactionPage,
    tchSubscriptionStatusFilter,
    setTchSubscriptionStatusFilter,
    tchClientFilter,
    setTchClientFilter,
    tchClientPage,
    setTchClientPage,
    tchTransactionPeriodFilter,
    setTchTransactionPeriodFilter,
    tchMode,
    setTchMode,
    tchYear,
    setTchYear,
    tchSubscriptionDetail,
    setTchSubscriptionDetail,
    tchTransactionDetail,
    setTchTransactionDetail,
    tchClientDetail,
    setTchClientDetail,
    showTchTransaction,
    showTchClient,
  };
}
export type TchState = ReturnType<typeof useTch>;
