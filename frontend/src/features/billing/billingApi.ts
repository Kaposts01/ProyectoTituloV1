import { getJson, postJson, putJson } from "../../api";
import { listPath, type InboxFilters, type InboxTab } from "./billingQuery";
import type {
  ApplyResponse, BillingList, BillingRequestDetail, ChangeBody, Policy, PolicyAuditList, PolicyPatch, PreviewResponse,
} from "./types";

const BASE = "/api/v1/billing";
const enc = encodeURIComponent;

export const fetchRequests = (tab: InboxTab, filters: InboxFilters, offset: number, limit: number) =>
  getJson<BillingList>(listPath(tab, filters, offset, limit));
export const fetchRequest = (id: string) => getJson<BillingRequestDetail>(`${BASE}/changes/${enc(id)}`);
export const previewChange = (body: ChangeBody) => postJson<PreviewResponse>(`${BASE}/changes/preview`, body);
export const createChange = (body: ChangeBody) => postJson<BillingRequestDetail>(`${BASE}/changes`, body);
export const approveRequest = (id: string, comment?: string) => postJson<BillingRequestDetail>(`${BASE}/changes/${enc(id)}/approve`, comment ? { comment } : undefined);
export const rejectRequest = (id: string, comment: string) => postJson<BillingRequestDetail>(`${BASE}/changes/${enc(id)}/reject`, { comment });
export const withdrawRequest = (id: string, comment?: string) => postJson<BillingRequestDetail>(`${BASE}/changes/${enc(id)}/withdraw`, comment ? { comment } : undefined);
export const reopenRequest = (id: string, comment: string) => postJson<BillingRequestDetail>(`${BASE}/changes/${enc(id)}/reopen`, { comment });
export const applyRequest = (id: string, acceptDrift: boolean) =>
  postJson<ApplyResponse>(`${BASE}/changes/${enc(id)}/apply`, acceptDrift ? { accept_drift: true } : {});

export const fetchPolicy = () => getJson<Policy>(`${BASE}/policy`);
export const updatePolicy = (patch: PolicyPatch) => putJson<Policy>(`${BASE}/policy`, patch);
export const fetchPolicyAudit = (limit = 20, offset = 0) => getJson<PolicyAuditList>(`${BASE}/policy/audit?limit=${limit}&offset=${offset}`);
