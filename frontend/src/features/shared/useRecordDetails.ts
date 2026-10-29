import { useState } from "react";
import { getJson, friendlyError } from "../../api";
import type { AppRoute, ProviderSource } from "../../routes";
import type {
  ProviderRecordDetail, StagingRecord, VirtualPosChargeDetail, VirtualPosClientDetail, VirtualPosPaymentDetail,
  VirtualPosPlanDetail, VirtualPosSubscriptionDetail,
} from "../shared/types";

/**
 * Fichas de detalle abiertas (cliente, plan, suscripción, cargo, transacción y registro de Toku/Payku) y
 * las funciones para abrirlas. Se llama desde AppCore porque las escrituras actualizan estas fichas y para
 * que la ficha abierta sobreviva igual que antes de la extracción.
 */
export function useRecordDetails(ctx: {
  navigate: (route: AppRoute, replace?: boolean) => void;
  setError: (message: string | null) => void;
}) {
  const { navigate, setError } = ctx;
  const [clientDetail, setClientDetail] =
    useState<VirtualPosClientDetail | null>(null);
  const [planDetail, setPlanDetail] = useState<VirtualPosPlanDetail | null>(
    null,
  );
  const [subscriptionDetail, setSubscriptionDetail] =
    useState<VirtualPosSubscriptionDetail | null>(null);
  const [chargeDetail, setChargeDetail] = useState<VirtualPosChargeDetail | null>(null);
  const [paymentDetail, setPaymentDetail] = useState<VirtualPosPaymentDetail | null>(null);
  const [providerRecordDetail, setProviderRecordDetail] =
    useState<ProviderRecordDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  function clearDetails() {
    setClientDetail(null);
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setProviderRecordDetail(null);
  }

  async function openVirtualPosClient(record: Pick<StagingRecord, "external_id">, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "record", source: "virtualpos", resource: "client", externalId: record.external_id });
      return;
    }
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setClientDetail(
        await getJson<VirtualPosClientDetail>(
          `/api/v1/staging/virtualpos/clients/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del cliente."));
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosPlan(record: Pick<StagingRecord, "external_id">, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "record", source: "virtualpos", resource: "plan", externalId: record.external_id });
      return;
    }
    setClientDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setPlanDetail(
        await getJson<VirtualPosPlanDetail>(
          `/api/v1/staging/virtualpos/plans/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del plan."));
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosSubscription(record: Pick<StagingRecord, "external_id">, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "record", source: "virtualpos", resource: "subscription", externalId: record.external_id });
      return;
    }
    setClientDetail(null);
    setPlanDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setSubscriptionDetail(
        await getJson<VirtualPosSubscriptionDetail>(
          `/api/v1/staging/virtualpos/subscriptions/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha de la subscripción."));
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosCharge(record: Pick<StagingRecord, "external_id">, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "record", source: "virtualpos", resource: "charge", externalId: record.external_id });
      return;
    }
    setClientDetail(null);
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setChargeDetail(
        await getJson<VirtualPosChargeDetail>(
          `/api/v1/staging/virtualpos/charges/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del cargo."));
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosPayment(record: Pick<StagingRecord, "external_id">, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "record", source: "virtualpos", resource: "payment", externalId: record.external_id });
      return;
    }
    setClientDetail(null);
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setPaymentDetail(
        await getJson<VirtualPosPaymentDetail>(
          `/api/v1/staging/virtualpos/payments/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del pago."));
    } finally {
      setDetailLoading(false);
    }
  }
  async function openProviderRecord(
    source: ProviderSource,
    resource: string,
    record: Pick<StagingRecord, "external_id">,
    updateUrl = true,
  ) {
    if (updateUrl) {
      navigate({ kind: "record", source, resource, externalId: record.external_id });
      return;
    }
    clearDetails();
    setDetailLoading(true);
    setError(null);
    try {
      setProviderRecordDetail(
        await getJson<ProviderRecordDetail>(
          `/api/v1/staging/${source}/${resource}/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del registro."));
    } finally {
      setDetailLoading(false);
    }
  }

  function openRecord(source: ProviderSource, resource: string, externalId: string, updateUrl = true) {
    const record = { external_id: externalId };
    if (source === "virtualpos") {
      if (resource === "client") return openVirtualPosClient(record, updateUrl);
      if (resource === "plan") return openVirtualPosPlan(record, updateUrl);
      if (resource === "subscription") return openVirtualPosSubscription(record, updateUrl);
      if (resource === "charge") return openVirtualPosCharge(record, updateUrl);
      if (resource === "payment") return openVirtualPosPayment(record, updateUrl);
      return;
    }
    return openProviderRecord(source, resource, record, updateUrl);
  }

  return {
    clientDetail,
    setClientDetail,
    planDetail,
    setPlanDetail,
    subscriptionDetail,
    setSubscriptionDetail,
    chargeDetail,
    setChargeDetail,
    paymentDetail,
    setPaymentDetail,
    providerRecordDetail,
    setProviderRecordDetail,
    detailLoading,
    setDetailLoading,
    clearDetails,
    openVirtualPosClient,
    openVirtualPosPlan,
    openVirtualPosSubscription,
    openVirtualPosCharge,
    openVirtualPosPayment,
    openProviderRecord,
    openRecord,
  };
}

export type RecordDetailsState = ReturnType<typeof useRecordDetails>;
