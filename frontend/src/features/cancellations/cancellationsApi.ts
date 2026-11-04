import { getJson, postJson } from "../../api";
import { withCsrfRetry } from "../shared/csrfRetry";
import { listPath, type CancellationFilters, type CancellationTab } from "./cancellationsQuery";
import type {
  ApplyResponse, CancellationBody, CancellationDetail, CancellationEventList, CancellationList, PreviewResponse,
} from "./types";

const BASE = "/api/v1/cancellations";
const enc = encodeURIComponent;

export const fetchCancellations = (tab: CancellationTab, filters: CancellationFilters, offset: number, limit: number) =>
  getJson<CancellationList>(listPath(tab, filters, offset, limit));
export const fetchCancellation = (id: string) => getJson<CancellationDetail>(`${BASE}/${enc(id)}`);
export const fetchCancellationEvents = (id: string) => getJson<CancellationEventList>(`${BASE}/${enc(id)}/events`);

export const previewCancellation = (body: CancellationBody) =>
  withCsrfRetry(() => postJson<PreviewResponse>(`${BASE}/preview`, body));
export const createCancellation = (body: CancellationBody) =>
  withCsrfRetry(() => postJson<CancellationDetail>(BASE, body));
export const approveCancellation = (id: string, comment?: string) =>
  withCsrfRetry(() => postJson<CancellationDetail>(`${BASE}/${enc(id)}/approve`, comment ? { comment } : undefined));
export const rejectCancellation = (id: string, comment: string) =>
  withCsrfRetry(() => postJson<CancellationDetail>(`${BASE}/${enc(id)}/reject`, { comment }));
export const withdrawCancellation = (id: string, comment?: string) =>
  withCsrfRetry(() => postJson<CancellationDetail>(`${BASE}/${enc(id)}/withdraw`, comment ? { comment } : undefined));
export const reopenCancellation = (id: string, comment: string) =>
  withCsrfRetry(() => postJson<CancellationDetail>(`${BASE}/${enc(id)}/reopen`, { comment }));
/** Con `dryRun` calcula el plan sin reclamar la solicitud ni escribir en el proveedor. */
export const applyCancellation = (id: string, dryRun: boolean) =>
  withCsrfRetry(() => postJson<ApplyResponse>(`${BASE}/${enc(id)}/apply`, { dry_run: dryRun }));
