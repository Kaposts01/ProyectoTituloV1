import { useEffect, useState } from "react";
import { getJson, friendlyError } from "../../api";
import { getCached, setCached } from "../../apiCache";
import { defaultYear, normalizeTchSummary } from "../shared/utils";
import type {
  AuthSession, TchClienteDetail, TchClientesResp, TchSuscripcionDetail, TchSuscripcionesResp, TchSummary,
  TchTransaccionDetail, TchTransaccionesResp,
} from "../shared/types";

export type TchViewName = "summary" | "clientes" | "suscripciones" | "transacciones" | "cliente-detalle" | "suscripcion-detalle" | "transaccion-detalle";

/**
 * Estado y carga de las vistas TCH. Se llama desde AppCore (no desde la vista) para que el estado
 * (modo, año, filtros, páginas) sobreviva a la navegación igual que antes de la extracción.
 */
export function useTch(session: AuthSession | null | undefined) {
  const [tchView, setTchView] = useState<TchViewName | null>(null);
  const [tchRefreshing, setTchRefreshing] = useState(false);
  const [tchSummary, setTchSummary] = useState<TchSummary | null>(null);
  const [tchSuscripciones, setTchSuscripciones] = useState<TchSuscripcionesResp | null>(null);
  const [tchTransacciones, setTchTransacciones] = useState<TchTransaccionesResp | null>(null);
  const [tchClientes, setTchClientes] = useState<TchClientesResp | null>(null);
  const [tchLoading, setTchLoading] = useState(false);
  const [tchError, setTchError] = useState<string | null>(null);
  const [tchSusPage, setTchSusPage] = useState(1);
  const [tchTransPage, setTchTransPage] = useState(1);
  const [tchSusFiltroEstado, setTchSusFiltroEstado] = useState("");
  const [tchClienteFiltro, setTchClienteFiltro] = useState("");
  const [tchClientesPage, setTchClientesPage] = useState(1);
  const [tchTransFiltroPeriodo, setTchTransFiltroPeriodo] = useState("");
  const [tchMode, setTchMode] = useState<"count" | "amount">("count");
  const [tchYear, setTchYear] = useState<number | null>(null);
  const [tchSuscripcionDetail, setTchSuscripcionDetail] = useState<TchSuscripcionDetail | null>(null);
  const [tchTransaccionDetail, setTchTransaccionDetail] = useState<TchTransaccionDetail | null>(null);
  const [tchClienteDetail, setTchClienteDetail] = useState<TchClienteDetail | null>(null);

  function showTchTransaccion(id: string) {
    setTchClienteDetail(null);
    setTchSuscripcionDetail(null);
    setTchTransaccionDetail({ id } as TchTransaccionDetail);
    setTchView("transaccion-detalle");
  }

  function showTchCliente(rut: string) {
    setTchSuscripcionDetail(null);
    setTchTransaccionDetail(null);
    setTchClienteDetail({ rut, suscripciones: [] } as unknown as TchClienteDetail);
    setTchView("cliente-detalle");
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
      const params = new URLSearchParams({ limit: "50", page: String(tchClientesPage) });
      if (tchClienteFiltro) params.set("nombre", tchClienteFiltro);
      getJson<TchClientesResp>(`/api/v1/tch/clientes?${params}`)
        .then((d) => { if (mounted) setTchClientes(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar los clientes TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "suscripciones") {
      setTchLoading(true);
      const params = new URLSearchParams({ limit: "50", page: String(tchSusPage) });
      if (tchSusFiltroEstado) params.set("estado", tchSusFiltroEstado);
      getJson<TchSuscripcionesResp>(`/api/v1/tch/suscripciones?${params}`)
        .then((d) => { if (mounted) setTchSuscripciones(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar las suscripciones TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "transacciones") {
      setTchLoading(true);
      const params = new URLSearchParams({ limit: "100", page: String(tchTransPage) });
      if (tchTransFiltroPeriodo) params.set("periodo", tchTransFiltroPeriodo);
      getJson<TchTransaccionesResp>(`/api/v1/tch/transacciones?${params}`)
        .then((d) => { if (mounted) setTchTransacciones(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar las transacciones TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "suscripcion-detalle" && tchSuscripcionDetail) {
      setTchLoading(true);
      getJson<TchSuscripcionDetail>(`/api/v1/tch/suscripciones/${tchSuscripcionDetail.numero_ficha}`)
        .then((d) => { if (mounted) setTchSuscripcionDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "transaccion-detalle" && tchTransaccionDetail) {
      setTchLoading(true);
      getJson<TchTransaccionDetail>(`/api/v1/tch/transacciones/${tchTransaccionDetail.id}`)
        .then((d) => { if (mounted) setTchTransaccionDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "cliente-detalle" && tchClienteDetail) {
      setTchLoading(true);
      getJson<TchClienteDetail>(`/api/v1/tch/clientes/${encodeURIComponent(tchClienteDetail.rut)}`)
        .then((d) => { if (mounted) setTchClienteDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha del cliente TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    }
    return () => { mounted = false; };
  }, [session, tchView, tchClientesPage, tchClienteFiltro, tchSusPage, tchSusFiltroEstado, tchTransPage, tchTransFiltroPeriodo, tchSuscripcionDetail?.numero_ficha, tchTransaccionDetail?.id, tchClienteDetail?.rut]);

  return {
    tchView,
    setTchView,
    tchRefreshing,
    setTchRefreshing,
    tchSummary,
    setTchSummary,
    tchSuscripciones,
    setTchSuscripciones,
    tchTransacciones,
    setTchTransacciones,
    tchClientes,
    setTchClientes,
    tchLoading,
    setTchLoading,
    tchError,
    setTchError,
    tchSusPage,
    setTchSusPage,
    tchTransPage,
    setTchTransPage,
    tchSusFiltroEstado,
    setTchSusFiltroEstado,
    tchClienteFiltro,
    setTchClienteFiltro,
    tchClientesPage,
    setTchClientesPage,
    tchTransFiltroPeriodo,
    setTchTransFiltroPeriodo,
    tchMode,
    setTchMode,
    tchYear,
    setTchYear,
    tchSuscripcionDetail,
    setTchSuscripcionDetail,
    tchTransaccionDetail,
    setTchTransaccionDetail,
    tchClienteDetail,
    setTchClienteDetail,
    showTchTransaccion,
    showTchCliente,
  };
}
export type TchState = ReturnType<typeof useTch>;
