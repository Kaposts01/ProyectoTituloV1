import { useEffect, useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { deleteJson, friendlyError, postJson, putJson } from "../../api";
import type { RecordDetailsState } from "../shared/useRecordDetails";
import type { StagingRecord, StagingResponse } from "../shared/types";
import { documentType, normalizeRut, refreshCsrfToken, text } from "../shared/utils";
import {
  virtualPosClientEditFields, virtualPosPlanCreateFields, virtualPosSubscriptionCreateFields,
} from "./constants";

/**
 * Formularios y confirmaciones de escritura contra VirtualPOS (cliente, plan, suscripción y cargos): estado
 * de cada diálogo y sus manejadores. Se llama desde AppCore porque los manejadores actualizan la lista de
 * registros y las fichas abiertas.
 */
export function useVirtualPosWrites(ctx: {
  records: StagingResponse;
  setRecords: Dispatch<SetStateAction<StagingResponse>>;
  details: Pick<RecordDetailsState, "clientDetail" | "setClientDetail" | "subscriptionDetail" | "setSubscriptionDetail" | "chargeDetail" | "setChargeDetail">;
}) {
  const { records, setRecords } = ctx;
  const { clientDetail, setClientDetail, subscriptionDetail, setSubscriptionDetail, chargeDetail, setChargeDetail } = ctx.details;
  const [editingClient, setEditingClient] = useState<StagingRecord | null>(null);
  const [creatingClient, setCreatingClient] = useState(false);
  const [clientVpPlatform, setClientVpPlatform] = useState<"virtualpos1" | "virtualpos2">("virtualpos1");
  const [savingClient, setSavingClient] = useState(false);
  const [clientFormError, setClientFormError] = useState<string | null>(null);
  const [clientFieldErrors, setClientFieldErrors] = useState<Record<string, string>>({});
  const [clientSaveNotice, setClientSaveNotice] = useState<string | null>(null);
  const [creatingPlan, setCreatingPlan] = useState(false);
  const [planVpPlatform, setPlanVpPlatform] = useState<"virtualpos1" | "virtualpos2">("virtualpos1");
  const [savingPlan, setSavingPlan] = useState(false);
  const [planFormError, setPlanFormError] = useState<string | null>(null);
  const [planFieldErrors, setPlanFieldErrors] = useState<Record<string, string>>({});
  const [planSaveNotice, setPlanSaveNotice] = useState<string | null>(null);
  const [creatingSubscription, setCreatingSubscription] = useState(false);
  const [subVpPlatform, setSubVpPlatform] = useState<"virtualpos1" | "virtualpos2">("virtualpos1");
  const [savingSubscription, setSavingSubscription] = useState(false);
  const [subscriptionFormError, setSubscriptionFormError] = useState<string | null>(null);
  const [subscriptionFieldErrors, setSubscriptionFieldErrors] = useState<Record<string, string>>({});
  const [subscriptionSaveNotice, setSubscriptionSaveNotice] = useState<string | null>(null);
  const [cancelingSubscription, setCancelingSubscription] = useState<StagingRecord | null>(null);
  const [savingCancelSubscription, setSavingCancelSubscription] = useState(false);
  const [cancelSubscriptionError, setCancelSubscriptionError] = useState<string | null>(null);
  const [creatingCharge, setCreatingCharge] = useState<StagingRecord | null>(null);
  const [savingCharge, setSavingCharge] = useState(false);
  const [chargeFormError, setChargeFormError] = useState<string | null>(null);
  const [chargeFieldErrors, setChargeFieldErrors] = useState<Record<string, string>>({});
  const [chargeSaveNotice, setChargeSaveNotice] = useState<string | null>(null);
  const [cancelingCharge, setCancelingCharge] = useState<StagingRecord | null>(null);
  const [savingCancelCharge, setSavingCancelCharge] = useState(false);
  const [cancelChargeError, setCancelChargeError] = useState<string | null>(null);
  const [retryingCharge, setRetryingCharge] = useState<StagingRecord | null>(null);
  const [savingRetryCharge, setSavingRetryCharge] = useState(false);
  const [retryChargeError, setRetryChargeError] = useState<string | null>(null);

  const clientDialogOpen = Boolean(editingClient) || creatingClient;
  useEffect(() => {
    setClientFormError(null);
    setClientFieldErrors({});
    // El aviso de éxito se fija justo al cerrar el diálogo: solo se limpia al abrir uno (igual que plan, suscripción y cargo).
    if (clientDialogOpen) setClientSaveNotice(null);
  }, [editingClient?.id, creatingClient, clientDialogOpen]);

  async function saveVirtualPOSClient(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingClient || savingClient) return;
    setClientFormError(null);
    setClientFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const changes: Record<string, string> = {};
    for (const field of virtualPosClientEditFields) {
      const rawValue = String(formData.get(field.name) ?? "").trim();
      const value = field.name === "social_id_type" ? documentType(rawValue) : rawValue;
      const current = field.name === "social_id_type"
        ? documentType(editingClient.payload[field.name])
        : text(editingClient.payload[field.name], "");
      if (value !== current) changes[field.name] = value;
    }
    const selectedDocumentType = documentType(formData.get("social_id_type"));
    if (selectedDocumentType === "1" && (changes.social_id || changes.social_id_type)) {
      const rut = normalizeRut(String(formData.get("social_id") ?? ""));
      if (!rut) {
        setClientFieldErrors({ social_id: "El RUT no es válido." });
        setClientFormError("Revisa los campos marcados.");
        return;
      }
      if (changes.social_id) changes.social_id = rut;
    }
    if (changes.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(changes.email)) {
      setClientFieldErrors({ email: "Ingresa un correo electrónico válido." });
      setClientFormError("Revisa los campos marcados.");
      return;
    }
    const privateNote = String(formData.get("private_note") ?? "").trim();
    if (privateNote !== text(editingClient.payload.private_note, "")) changes.private_note = privateNote;
    if (!Object.keys(changes).length) {
      setClientFormError("No hay cambios para guardar.");
      return;
    }

    const clientId = text(editingClient.payload.uuid, editingClient.external_id);
    setSavingClient(true);
    try {
      await refreshCsrfToken();
      const updated = await putJson<{ payload: Record<string, unknown> }>(
        `/api/v1/writes/virtualpos/clients/${encodeURIComponent(clientId)}`,
        changes,
      );
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) => (
          record.id === editingClient.id ? { ...record, payload: updated.payload } : record
        )),
      }));
      setClientDetail((current) => current && current.client.id === editingClient.id
        ? { ...current, client: { ...current.client, payload: updated.payload } }
        : current);
      setEditingClient(null);
      setClientSaveNotice("Cambios guardados correctamente.");
    } catch (saveError) {
      const message = friendlyError(saveError, "No se pudo guardar el cliente.");
      if (message === "Invalid RUT") {
        setClientFieldErrors({ social_id: "El RUT no es válido." });
        setClientFormError("Revisa los campos marcados en rojo.");
      } else {
        setClientFormError(message);
      }
    } finally {
      setSavingClient(false);
    }
  }

  async function createVirtualPOSClient(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingClient) return;
    setClientFormError(null);
    setClientFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const fieldErrors: Record<string, string> = {};

    const rawValues = Object.fromEntries(
      virtualPosClientEditFields.map((field) => [field.name, String(formData.get(field.name) ?? "").trim()] as const),
    ) as Record<string, string>;

    if (!rawValues.first_name) fieldErrors.first_name = "El nombre es obligatorio.";
    if (!rawValues.email) {
      fieldErrors.email = "El correo electrónico es obligatorio.";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(rawValues.email)) {
      fieldErrors.email = "Ingresa un correo electrónico válido.";
    }
    if (!rawValues.social_id_type) {
      fieldErrors.social_id_type = "Selecciona el tipo de documento.";
    }
    if (!rawValues.social_id) {
      fieldErrors.social_id = "El número de documento es obligatorio.";
    }

    const socialIdType = documentType(rawValues.social_id_type);
    if (!fieldErrors.social_id && rawValues.social_id) {
      if (socialIdType === "1") {
        const rut = normalizeRut(rawValues.social_id);
        if (!rut) fieldErrors.social_id = "El RUT no es válido. Ejemplo: 12345678-9";
        else rawValues.social_id = rut;
      } else if (socialIdType === "2") {
        if (rawValues.social_id.length < 5) fieldErrors.social_id = "El DNI debe tener al menos 5 caracteres.";
      }
    }

    if (rawValues.phone_number && !/^\+?[\d\s\-()]{7,20}$/.test(rawValues.phone_number)) {
      fieldErrors.phone_number = "Ingresa un teléfono válido.";
    }

    if (Object.keys(fieldErrors).length) {
      setClientFieldErrors(fieldErrors);
      setClientFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const normalizedSocialId = socialIdType === "1" ? normalizeRut(rawValues.social_id) ?? rawValues.social_id : rawValues.social_id;
    const duplicate = records.items.find((item) => {
      const itemSocial = String(item.payload.social_id ?? "");
      return itemSocial && itemSocial === normalizedSocialId;
    });
    if (duplicate) {
      setClientFieldErrors({ social_id: "Ya existe un cliente con este documento en el listado actual." });
      setClientFormError("Ya existe un cliente con ese documento de identidad en VirtualPOS.");
      return;
    }

    const client: Record<string, string> = {};
    for (const [key, value] of Object.entries(rawValues)) {
      if (value !== "") client[key] = value;
    }
    if (client.social_id_type) client.social_id_type = socialIdType;
    const privateNote = String(formData.get("private_note") ?? "").trim();
    if (privateNote) client.private_note = privateNote;
    client.platform = clientVpPlatform;

    setSavingClient(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        "/api/v1/writes/virtualpos/clients",
        client,
      );
      setRecords((current) => ({
        ...current,
        total: current.total + 1,
        items: [{ id: created.id, source: created.source, resource_type: "client", external_id: created.external_id, payload: created.payload }, ...current.items],
      }));
      setCreatingClient(false);
      setClientSaveNotice("Cliente creado correctamente.");
    } catch (createError) {
      const message = friendlyError(createError, "No se pudo crear el cliente.");
      if (message === "Invalid RUT") {
        setClientFieldErrors({ social_id: "El RUT no es válido." });
        setClientFormError("Revisa los campos marcados en rojo.");
      } else {
        setClientFormError(message);
      }
    } finally {
      setSavingClient(false);
    }
  }

  async function createVirtualPOSPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingPlan) return;
    setPlanFormError(null);
    setPlanFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const errors: Record<string, string> = {};
    const rawValues = Object.fromEntries(
      virtualPosPlanCreateFields.map((f) => [f.name, String(formData.get(f.name) ?? "").trim()] as const),
    ) as Record<string, string>;

    if (!rawValues.name) errors.name = "El nombre del plan es obligatorio.";
    const amount = rawValues.amount === "" ? NaN : Number(rawValues.amount);
    if (rawValues.amount === "" || isNaN(amount) || amount < 0) errors.amount = "Ingresa un monto válido (número ≥ 0).";
    if (!rawValues.currency) errors.currency = "Selecciona una moneda.";
    if (!rawValues.frequency_type) errors.frequency_type = "Selecciona la frecuencia de cobro.";

    const trialDays = rawValues.trial_days ? Number(rawValues.trial_days) : undefined;
    if (rawValues.trial_days && (isNaN(trialDays!) || trialDays! < 0)) errors.trial_days = "Los días de prueba deben ser un número ≥ 0.";
    const numCharges = rawValues.num_charges ? Number(rawValues.num_charges) : undefined;
    if (rawValues.num_charges && (isNaN(numCharges!) || numCharges! < 0)) errors.num_charges = "El número de cobros debe ser ≥ 0.";
    const fixedDay = rawValues.fixed_amount_day_charge ? Number(rawValues.fixed_amount_day_charge) : undefined;
    if (rawValues.fixed_amount_day_charge && (isNaN(fixedDay!) || fixedDay! < 1 || fixedDay! > 28)) errors.fixed_amount_day_charge = "El día de cobro debe ser entre 1 y 28.";
    const activationAmount = rawValues.activation_amount ? Number(rawValues.activation_amount) : undefined;
    if (rawValues.activation_amount && (isNaN(activationAmount!) || activationAmount! < 0)) errors.activation_amount = "El monto de activación debe ser ≥ 0.";

    if (Object.keys(errors).length) {
      setPlanFieldErrors(errors);
      setPlanFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const body: Record<string, unknown> = { platform: planVpPlatform, name: rawValues.name, amount, currency: rawValues.currency, frequency_type: rawValues.frequency_type };
    if (rawValues.description) body.description = rawValues.description;
    if (trialDays !== undefined) body.trial_days = trialDays;
    if (numCharges !== undefined) body.num_charges = numCharges;
    if (fixedDay !== undefined) body.fixed_amount_day_charge = fixedDay;
    if (activationAmount !== undefined) body.activation_amount = activationAmount;
    if (rawValues.automatic_renewal) body.automatic_renewal = rawValues.automatic_renewal === "true";
    if (rawValues.show_in_terminal) body.show_in_terminal = rawValues.show_in_terminal === "true";
    if (rawValues.is_active) body.is_active = rawValues.is_active === "true";
    if (rawValues.return_url) body.return_url = rawValues.return_url;
    if (rawValues.suscription_url) body.suscription_url = rawValues.suscription_url;
    if (rawValues.type) body.type = rawValues.type;

    setSavingPlan(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        "/api/v1/writes/virtualpos/plans",
        body,
      );
      setRecords((current) => ({
        ...current,
        total: current.total + 1,
        items: [{ id: created.id, source: created.source, resource_type: "plan", external_id: created.external_id, payload: created.payload }, ...current.items],
      }));
      setCreatingPlan(false);
      setPlanSaveNotice("Plan creado correctamente.");
    } catch (err) {
      setPlanFormError(friendlyError(err, "No se pudo crear el plan."));
    } finally {
      setSavingPlan(false);
    }
  }

  async function createVirtualPOSSubscription(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingSubscription) return;
    setSubscriptionFormError(null);
    setSubscriptionFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const rawValues = Object.fromEntries(
      virtualPosSubscriptionCreateFields.map((f) => [f.name, String(formData.get(f.name) ?? "").trim()] as const),
    ) as Record<string, string>;

    const errors: Record<string, string> = {};
    if (!rawValues.plan_id) errors.plan_id = "El ID del plan es obligatorio.";
    if (!rawValues.email) errors.email = "El email es obligatorio.";
    if (!rawValues.first_name) errors.first_name = "El nombre es obligatorio.";
    if (!rawValues.last_name) errors.last_name = "El apellido es obligatorio.";
    if (!rawValues.social_id) errors.social_id = "El RUT es obligatorio.";

    if (Object.keys(errors).length) {
      setSubscriptionFieldErrors(errors);
      setSubscriptionFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const body: Record<string, unknown> = {
      platform: subVpPlatform,
      plan_id: rawValues.plan_id,
      email: rawValues.email,
      first_name: rawValues.first_name,
      last_name: rawValues.last_name,
      social_id: rawValues.social_id,
    };
    if (rawValues.phone_number) body.phone_number = rawValues.phone_number;
    if (rawValues.service_id) body.service_id = rawValues.service_id;
    if (rawValues.channel) body.channel = rawValues.channel;
    if (rawValues.automatic_renewal) body.automatic_renewal = rawValues.automatic_renewal;
    if (rawValues.return_url) body.return_url = rawValues.return_url;
    if (rawValues.callback_url) body.callback_url = rawValues.callback_url;

    setSavingSubscription(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        "/api/v1/writes/virtualpos/subscriptions",
        body,
      );
      setRecords((current) => ({
        ...current,
        total: current.total + 1,
        items: [{ id: created.id, source: created.source, resource_type: "subscription", external_id: created.external_id, payload: created.payload }, ...current.items],
      }));
      setCreatingSubscription(false);
      setSubscriptionSaveNotice("Suscripción creada correctamente.");
    } catch (err) {
      setSubscriptionFormError(friendlyError(err, "No se pudo crear la suscripción."));
    } finally {
      setSavingSubscription(false);
    }
  }

  async function createVirtualPOSCharge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingCharge || !creatingCharge) return;
    setChargeFormError(null);
    setChargeFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const errors: Record<string, string> = {};
    const chargeDate = String(formData.get("charge_date") ?? "").trim();
    const amountRaw = String(formData.get("amount") ?? "").trim();
    const description = String(formData.get("description") ?? "").trim();
    const internalCode = String(formData.get("internal_code") ?? "").trim();

    if (!chargeDate) {
      errors.charge_date = "La fecha del cargo es obligatoria.";
    } else {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const selected = new Date(chargeDate);
      if (isNaN(selected.getTime())) {
        errors.charge_date = "Ingresa una fecha válida.";
      } else if (selected < today) {
        errors.charge_date = "La fecha del cargo no puede ser una fecha pasada.";
      }
    }
    const amount = amountRaw === "" ? NaN : Number(amountRaw);
    if (amountRaw === "" || isNaN(amount) || amount < 1) {
      errors.amount = "Ingresa un monto válido (número ≥ 1).";
    }

    if (Object.keys(errors).length) {
      setChargeFieldErrors(errors);
      setChargeFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const subscriptionId = String(creatingCharge.payload.id ?? creatingCharge.external_id);
    const body: Record<string, unknown> = { charge_date: chargeDate, amount };
    if (description) body.description = description;
    if (internalCode) body.internal_code = internalCode;

    setSavingCharge(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        `/api/v1/writes/virtualpos/subscriptions/${encodeURIComponent(subscriptionId)}/charges`,
        body,
      );
      setCreatingCharge(null);
      setChargeSaveNotice(`Cargo creado correctamente (ID: ${created.external_id}).`);
      if (subscriptionDetail && subscriptionDetail.subscription.external_id === creatingCharge.external_id) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                charges: [{ id: created.id, source: created.source, resource_type: "charge", external_id: created.external_id, payload: created.payload }, ...prev.charges],
                charge_total: prev.charge_total + 1,
              }
            : prev,
        );
      }
    } catch (err) {
      setChargeFormError(friendlyError(err, "No se pudo crear el cargo."));
    } finally {
      setSavingCharge(false);
    }
  }

  async function cancelVirtualPOSSubscription() {
    if (savingCancelSubscription || !cancelingSubscription) return;
    setSavingCancelSubscription(true);
    setCancelSubscriptionError(null);
    const subExternalId = String(cancelingSubscription.payload.id ?? cancelingSubscription.external_id);
    try {
      await refreshCsrfToken();
      const result = await deleteJson<{ external_id: string; status: string }>(
        `/api/v1/writes/virtualpos/subscriptions/${encodeURIComponent(subExternalId)}`,
      );
      const updatedStatus = result.status ?? "CANCELADA";
      setCancelingSubscription(null);
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) =>
          record.resource_type === "subscription" && record.external_id === subExternalId
            ? { ...record, payload: { ...record.payload, status: updatedStatus } }
            : record,
        ),
      }));
      if (subscriptionDetail && subscriptionDetail.subscription.external_id === subExternalId) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                subscription: {
                  ...prev.subscription,
                  payload: { ...prev.subscription.payload, status: updatedStatus },
                },
              }
            : prev,
        );
      }
      if (clientDetail) {
        setClientDetail((prev) =>
          prev
            ? {
                ...prev,
                subscriptions: prev.subscriptions.map((s) =>
                  s.external_id === subExternalId
                    ? { ...s, payload: { ...s.payload, status: updatedStatus } }
                    : s,
                ),
              }
            : prev,
        );
      }
    } catch (err) {
      setCancelSubscriptionError(friendlyError(err, "No se pudo cancelar la suscripción."));
    } finally {
      setSavingCancelSubscription(false);
    }
  }

  async function cancelVirtualPOSCharge() {
    if (savingCancelCharge || !cancelingCharge) return;
    setSavingCancelCharge(true);
    setCancelChargeError(null);
    const chargeExternalId = String(cancelingCharge.payload.id ?? cancelingCharge.external_id);
    try {
      await refreshCsrfToken();
      const result = await deleteJson<{ external_id: string; status: string }>(
        `/api/v1/writes/virtualpos/charges/${encodeURIComponent(chargeExternalId)}`,
      );
      const updatedStatus = result.status ?? "cancelado";
      setCancelingCharge(null);
      setChargeSaveNotice(`Cargo ${chargeExternalId} cancelado.`);
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) =>
          record.resource_type === "charge" && record.external_id === chargeExternalId
            ? { ...record, payload: { ...record.payload, status: updatedStatus } }
            : record,
        ),
      }));
      if (subscriptionDetail) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                charges: prev.charges.map((c) =>
                  c.external_id === chargeExternalId
                    ? { ...c, payload: { ...c.payload, status: updatedStatus } }
                    : c,
                ),
              }
            : prev,
        );
      }
      if (chargeDetail && chargeDetail.charge.external_id === chargeExternalId) {
        setChargeDetail((prev) =>
          prev
            ? { ...prev, charge: { ...prev.charge, payload: { ...prev.charge.payload, status: updatedStatus } } }
            : prev,
        );
      }
    } catch (err) {
      setCancelChargeError(friendlyError(err, "No se pudo cancelar el cargo."));
    } finally {
      setSavingCancelCharge(false);
    }
  }

  async function retryVirtualPOSCharge() {
    if (savingRetryCharge || !retryingCharge) return;
    setSavingRetryCharge(true);
    setRetryChargeError(null);
    const chargeExternalId = String(retryingCharge.payload.id ?? retryingCharge.external_id);
    try {
      await refreshCsrfToken();
      const result = await postJson<{ external_id: string; status: string; payload: Record<string, unknown> }>(
        `/api/v1/writes/virtualpos/charges/${encodeURIComponent(chargeExternalId)}/retry`,
      );
      const rawStatus = result.status ?? "procesando";
      const updatedStatus = rawStatus.toLowerCase() === "rechazado" ? "procesando" : rawStatus;
      const updatedPayload = result.payload ?? retryingCharge.payload;
      setRetryingCharge(null);
      setChargeSaveNotice(`Cargo ${chargeExternalId} reintentado.`);
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) =>
          record.resource_type === "charge" && record.external_id === chargeExternalId
            ? { ...record, payload: { ...record.payload, ...updatedPayload, status: updatedStatus } }
            : record,
        ),
      }));
      if (subscriptionDetail) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                charges: prev.charges.map((c) =>
                  c.external_id === chargeExternalId
                    ? { ...c, payload: { ...c.payload, ...updatedPayload, status: updatedStatus } }
                    : c,
                ),
              }
            : prev,
        );
      }
      if (chargeDetail && chargeDetail.charge.external_id === chargeExternalId) {
        setChargeDetail((prev) =>
          prev
            ? { ...prev, charge: { ...prev.charge, payload: { ...prev.charge.payload, ...updatedPayload, status: updatedStatus } } }
            : prev,
        );
      }
    } catch (err) {
      setRetryChargeError(friendlyError(err, "No se pudo reintentar el cargo."));
    } finally {
      setSavingRetryCharge(false);
    }
  }

  return {
    editingClient,
    setEditingClient,
    creatingClient,
    setCreatingClient,
    clientVpPlatform,
    setClientVpPlatform,
    savingClient,
    setSavingClient,
    clientFormError,
    setClientFormError,
    clientFieldErrors,
    setClientFieldErrors,
    clientSaveNotice,
    setClientSaveNotice,
    creatingPlan,
    setCreatingPlan,
    planVpPlatform,
    setPlanVpPlatform,
    savingPlan,
    setSavingPlan,
    planFormError,
    setPlanFormError,
    planFieldErrors,
    setPlanFieldErrors,
    planSaveNotice,
    setPlanSaveNotice,
    creatingSubscription,
    setCreatingSubscription,
    subVpPlatform,
    setSubVpPlatform,
    savingSubscription,
    setSavingSubscription,
    subscriptionFormError,
    setSubscriptionFormError,
    subscriptionFieldErrors,
    setSubscriptionFieldErrors,
    subscriptionSaveNotice,
    setSubscriptionSaveNotice,
    cancelingSubscription,
    setCancelingSubscription,
    savingCancelSubscription,
    setSavingCancelSubscription,
    cancelSubscriptionError,
    setCancelSubscriptionError,
    creatingCharge,
    setCreatingCharge,
    savingCharge,
    setSavingCharge,
    chargeFormError,
    setChargeFormError,
    chargeFieldErrors,
    setChargeFieldErrors,
    chargeSaveNotice,
    setChargeSaveNotice,
    cancelingCharge,
    setCancelingCharge,
    savingCancelCharge,
    setSavingCancelCharge,
    cancelChargeError,
    setCancelChargeError,
    retryingCharge,
    setRetryingCharge,
    savingRetryCharge,
    setSavingRetryCharge,
    retryChargeError,
    setRetryChargeError,
    saveVirtualPOSClient,
    createVirtualPOSClient,
    createVirtualPOSPlan,
    createVirtualPOSSubscription,
    createVirtualPOSCharge,
    cancelVirtualPOSSubscription,
    cancelVirtualPOSCharge,
    retryVirtualPOSCharge,
  };
}

export type VirtualPosWritesState = ReturnType<typeof useVirtualPosWrites>;
