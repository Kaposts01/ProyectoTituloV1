import { getJson, postJson, putJson } from "../../api";
import { refreshCsrfToken } from "../shared/utils";
import { renewalAlertPath, renewalPath, type RenewalFilters } from "./billingRenewal";
import { listPath, type InboxFilters, type InboxTab } from "./billingQuery";
import type {
  ApplyResponse, BillingList, BillingRequestDetail, ChangeBody, Policy, PolicyAuditList, PolicyPatch, PreviewResponse, RenewalTaskList, RequesterList,
} from "./types";

const BASE = "/api/v1/billing";
const enc = encodeURIComponent;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
/** 403 sin `code` estructurado: lo emite el middleware (CSRF), no el servicio de billing (que siempre envía `code`). */
function isUnstructured403(error: unknown): boolean {
  if (!isRecord(error) || error.status !== 403) return false;
  const detail = error.detail;
  return !(isRecord(detail) && typeof detail.code === "string");
}
function looksLikeCsrf(error: unknown): boolean {
  return isRecord(error) && typeof error.detail === "string" && /csrf/i.test(error.detail);
}

/**
 * Mutaciones de billing. Si otra pestaña refrescó la sesión, el token CSRF local queda obsoleto y el servidor responde
 * 403 sin `code`: se refresca el token y se reintenta UNA vez (el rechazo ocurre antes del handler, sin efectos).
 * Los errores con código estructurado (not_approver, writes_disabled, ...) nunca se reintentan.
 */
async function mutate<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call();
  } catch (first) {
    if (!isUnstructured403(first)) throw first;
    await refreshCsrfToken();
    try {
      return await call();
    } catch (second) {
      if (isUnstructured403(second) && looksLikeCsrf(second)) {
        throw Object.assign(new Error("stale_session"), { status: 403, detail: { code: "stale_session" } });
      }
      throw second;
    }
  }
}

export const fetchRequests = (tab: InboxTab, filters: InboxFilters, offset: number, limit: number) =>
  getJson<BillingList>(listPath(tab, filters, offset, limit));
export const fetchRequest = (id: string) => getJson<BillingRequestDetail>(`${BASE}/changes/${enc(id)}`);
export const previewChange = (body: ChangeBody) => mutate(() => postJson<PreviewResponse>(`${BASE}/changes/preview`, body));
export const createChange = (body: ChangeBody) => mutate(() => postJson<BillingRequestDetail>(`${BASE}/changes`, body));
export const approveRequest = (id: string, comment?: string) => mutate(() => postJson<BillingRequestDetail>(`${BASE}/changes/${enc(id)}/approve`, comment ? { comment } : undefined));
export const rejectRequest = (id: string, comment: string) => mutate(() => postJson<BillingRequestDetail>(`${BASE}/changes/${enc(id)}/reject`, { comment }));
export const withdrawRequest = (id: string, comment?: string) => mutate(() => postJson<BillingRequestDetail>(`${BASE}/changes/${enc(id)}/withdraw`, comment ? { comment } : undefined));
export const reopenRequest = (id: string, comment: string) => mutate(() => postJson<BillingRequestDetail>(`${BASE}/changes/${enc(id)}/reopen`, { comment }));
export const applyRequest = (id: string, acceptDrift: boolean) =>
  mutate(() => postJson<ApplyResponse>(`${BASE}/changes/${enc(id)}/apply`, acceptDrift ? { accept_drift: true } : {}));

export const fetchRequesters = () => getJson<RequesterList>(`${BASE}/requesters`);

export const fetchPolicy = () => getJson<Policy>(`${BASE}/policy`);
export const updatePolicy = (patch: PolicyPatch) => mutate(() => putJson<Policy>(`${BASE}/policy`, patch));
export const fetchPolicyAudit = (limit = 20, offset = 0) => getJson<PolicyAuditList>(`${BASE}/policy/audit?limit=${limit}&offset=${offset}`);

export const fetchRenewalTasks = (filters: RenewalFilters, offset: number, limit: number) =>
  getJson<RenewalTaskList>(renewalPath(filters, offset, limit));
export const fetchRenewalAlertCount = () => getJson<RenewalTaskList>(renewalAlertPath());
