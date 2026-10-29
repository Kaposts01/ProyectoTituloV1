import { useEffect, useState } from "react";
import { getJson, friendlyError } from "../../api";
import { getCached, setCached } from "../../apiCache";
import { defaultYear } from "../shared/utils";
import type { AuthSession } from "../shared/types";
import {
  adaptTchClientDetail, adaptTchClientsPage, adaptTchSubscriptionDetail, adaptTchSubscriptionsPage, adaptTchSummary,
  adaptTchTransactionDetail, adaptTchTransactionsPage, provisionalTchClientDetail, provisionalTchTransactionDetail,
  type TchClientWire, type TchPageWire, type TchSubscriptionWire, type TchSummaryWire, type TchTransactionWire,
} from "./tchAdapter";
import type {
  TchClientDetail, TchClientsPage, TchSubscriptionDetail, TchSubscriptionsPage, TchSummary, TchTransactionDetail, TchTransactionsPage,
} from "./tchTypes";

export type TchViewName = "summary" | "clientes" | "suscripciones" | "transacciones" | "client-detail" | "subscription-detail" | "transaction-detail";

/**
 * Estado y carga de las vistas TCH. Se llama desde AppCore (no desde la vista) para que el estado
 * (modo, año, filtros, páginas) sobreviva a la navegación igual que antes de la extracción.
 */
export function useTch(session: AuthSession | null | undefined) {
  const [tchView, setTchView] = useState<TchViewName | null>(null);
  const [tchRefreshing, setTchRefreshing] = useState(false);
  const [tchSummary, setTchSummary] = useState<TchSummary | null>(null);
  const [tchSubscriptions, setTchSubscriptions] = useState<TchSubscriptionsPage | null>(null);
  const [tchTransactions, setTchTransactions] = useState<TchTransactionsPage | null>(null);
  const [tchClients, setTchClients] = useState<TchClientsPage | null>(null);
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
  const [tchSubscriptionDetail, setTchSubscriptionDetail] = useState<TchSubscriptionDetail | null>(null);
  const [tchTransactionDetail, setTchTransactionDetail] = useState<TchTransactionDetail | null>(null);
  const [tchClientDetail, setTchClientDetail] = useState<TchClientDetail | null>(null);

  function showTchTransaction(id: string) {
    setTchClientDetail(null);
    setTchSubscriptionDetail(null);
    setTchTransactionDetail(provisionalTchTransactionDetail(id));
    setTchView("transaction-detail");
  }

  function showTchClient(rut: string) {
    setTchSubscriptionDetail(null);
    setTchTransactionDetail(null);
    setTchClientDetail(provisionalTchClientDetail(rut));
    setTchView("client-detail");
  }

  useEffect(() => {
    if (!session || !tchView) return;
    let mounted = true;
    setTchError(null);
    if (tchView === "summary") {
      const cached = getCached<TchSummaryWire>("tch:summary", 10 * 60 * 1000);
      if (cached) {
        const summary = adaptTchSummary(cached);
        setTchSummary(summary);
        setTchYear((current) => current ?? defaultYear(summary.years));
        setTchLoading(false);
        return () => { mounted = false; };
      }
      setTchLoading(true);
      getJson<TchSummaryWire>("/api/v1/tch/summary")
        .then((d) => {
          if (!mounted) return;
          const summary = adaptTchSummary(d);
          setCached("tch:summary", d);
          setTchSummary(summary);
          setTchYear((current) => current ?? defaultYear(summary.years));
        })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar el resumen TCH.")); })
        .finally(() => { if (mounted) { setTchLoading(false); setTchRefreshing(false); } });
    } else if (tchView === "clientes") {
      setTchLoading(true);
      const params = new URLSearchParams({ limit: "50", page: String(tchClientPage) });
      if (tchClientFilter) params.set("nombre", tchClientFilter);
      getJson<TchPageWire<TchClientWire>>(`/api/v1/tch/clientes?${params}`)
        .then((d) => { if (mounted) setTchClients(adaptTchClientsPage(d)); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar los clientes TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "suscripciones") {
      setTchLoading(true);
      const params = new URLSearchParams({ limit: "50", page: String(tchSubscriptionPage) });
      if (tchSubscriptionStatusFilter) params.set("estado", tchSubscriptionStatusFilter);
      getJson<TchPageWire<TchSubscriptionWire>>(`/api/v1/tch/suscripciones?${params}`)
        .then((d) => { if (mounted) setTchSubscriptions(adaptTchSubscriptionsPage(d)); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar las suscripciones TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "transacciones") {
      setTchLoading(true);
      const params = new URLSearchParams({ limit: "100", page: String(tchTransactionPage) });
      if (tchTransactionPeriodFilter) params.set("periodo", tchTransactionPeriodFilter);
      getJson<TchPageWire<TchTransactionWire>>(`/api/v1/tch/transacciones?${params}`)
        .then((d) => { if (mounted) setTchTransactions(adaptTchTransactionsPage(d)); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar las transacciones TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "subscription-detail" && tchSubscriptionDetail) {
      setTchLoading(true);
      getJson<TchSubscriptionWire>(`/api/v1/tch/suscripciones/${tchSubscriptionDetail.fileNumber}`)
        .then((d) => { if (mounted) setTchSubscriptionDetail(adaptTchSubscriptionDetail(d)); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "transaction-detail" && tchTransactionDetail) {
      setTchLoading(true);
      getJson<TchTransactionWire>(`/api/v1/tch/transacciones/${tchTransactionDetail.id}`)
        .then((d) => { if (mounted) setTchTransactionDetail(adaptTchTransactionDetail(d)); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "client-detail" && tchClientDetail) {
      setTchLoading(true);
      getJson<TchClientWire>(`/api/v1/tch/clientes/${encodeURIComponent(tchClientDetail.rut)}`)
        .then((d) => { if (mounted) setTchClientDetail(adaptTchClientDetail(d)); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha del cliente TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    }
    return () => { mounted = false; };
  }, [session, tchView, tchClientPage, tchClientFilter, tchSubscriptionPage, tchSubscriptionStatusFilter, tchTransactionPage, tchTransactionPeriodFilter, tchSubscriptionDetail?.fileNumber, tchTransactionDetail?.id, tchClientDetail?.rut]);

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
