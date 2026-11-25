/** ML-12 reads only the synthetic, rules-only ML-11 contract. Never infer missing data. */
export const PILOT_PERMISSIONS = ["general.recovery.tch.view", "ml.rejections.read", "ml.tch.access", "tch.transacciones.view"] as const;
export const PILOT_PAGE_SIZE = 10;
export const PILOT_PATH = "/api/v1/ml/tch/charge/results";
export const CATEGORY_LABELS = {
  FUNDS: "Fondos insuficientes", LIMIT: "Límite informado", TECH: "Problema técnico",
  EXPIRED: "Medio de pago vencido", BLOCKED: "Medio de pago bloqueado", INVALID: "Datos del medio de pago",
  FRAUD: "Señal de seguridad", ISSUER: "Rechazo del emisor",
} as const;
export const ADVICE = {
  no_action: { title: "No proponer una gestión", description: "La evidencia contiene una condición que impide gestionar el caso, como pago, cancelación o baja. Confirma el estado actual." },
  refresh_data: { title: "Verificar la información", description: "Falta cobertura verificable o el análisis usa información antigua. Revisa los datos actuales antes de decidir." },
  review_evidence: { title: "Revisar los antecedentes", description: "No hay evidencia suficiente para recomendar una gestión. Revisa el motivo y los resguardos pendientes." },
  review_security_signal: { title: "Revisar la señal de seguridad", description: "Una señal del medio de pago requiere revisión especializada. No demuestra fraude de la persona." },
  review_mandate_or_instrument: { title: "Verificar el mandato o medio de pago", description: "Hay un resguardo sobre el mandato, la cuenta o el medio de pago. No reintentes el cobro desde este análisis." },
  review_service_incident: { title: "Revisar el incidente técnico", description: "El motivo informado apunta a un problema técnico. Verifica su estado con el equipo responsable." },
  review_collection_options: { title: "Evaluar opciones con un responsable", description: "El motivo permite revisar alternativas, pero no autoriza cobros ni permite elegir una fecha de reintento." },
} as const;
export const REASONS: Record<string, string> = {
  p1_unavailable: "No hay un clasificador entrenado validado.", p2_unavailable: "No hay una probabilidad de recuperación validada.",
  coverage_missing_or_stale: "La cobertura de los datos no está confirmada o está desactualizada.",
  state_links_or_settlement_unverified: "Falta verificar el estado, los vínculos o la conciliación de pagos.",
  already_paid_cancelled_or_subscription_inactive: "Se informó una condición de pago, cancelación o suscripción inactiva.",
  human_review_required: "Se requiere revisión humana antes de decidir.",
  conflicting_evidence: "Los antecedentes entregan señales contradictorias.",
  unmapped_code: "El código informado todavía no tiene una interpretación revisada.",
  uninterpreted_text: "El motivo informado necesita revisión.", draft_text_rule: "La interpretación del texto es provisional.",
  domain_validation_pending: "La interpretación debe confirmarse con un especialista del canal.",
  processor_code_requires_review: "El código del procesador requiere revisión.", ambiguous_text: "El texto admite más de una interpretación.",
};
export const RESTRICTIONS: Record<string, string> = {
  no_automatic_retry: "Sin reintentos automáticos", retry_limit: "Límite de reintentos informado",
  mandate_inactive: "Mandato inactivo", account_closed: "Cuenta cerrada", instrument_unusable: "Medio de pago no utilizable",
  security_review: "Revisión de seguridad requerida", invalid_state: "Estado incompatible con la gestión",
};
const STATES = ["classified", "unmapped", "missing", "conflict", "not_rejection", "unsupported_source"];
export type PilotResult = {
  id: string; category: keyof typeof CATEGORY_LABELS | null; advice: keyof typeof ADVICE;
  method: "rule" | "unmapped"; asOf: string; state: string; severity: string;
  reasons: string[]; restrictions: string[]; matchedRules: string[];
  versions: { engine: string; policy: string; rules: string; taxonomy: string };
};
function record(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
function strings(value: unknown, max: number): value is string[] {
  return Array.isArray(value) && value.length <= max && value.every((v) => typeof v === "string" && /^[a-zA-Z0-9:_-]{1,100}$/.test(v));
}
function invalid(): never { throw new Error("La respuesta no corresponde al piloto de datos de prueba. No se mostraron los casos."); }
export function parsePilotResults(value: unknown): PilotResult[] {
  if (!Array.isArray(value) || value.length > PILOT_PAGE_SIZE) return invalid();
  const seen = new Set<string>();
  return value.map((row): PilotResult => {
    if (!record(row) || typeof row.id !== "string" || !/^[a-f0-9]{64}$/.test(row.id) || seen.has(row.id)
      || row.source !== "tch" || row.purpose !== "synthetic" || row.recovery_probability !== null || row.confidence !== null
      || row.execution_allowed !== false || (row.method !== "rule" && row.method !== "unmapped")
      || (row.category !== null && (typeof row.category !== "string" || !Object.hasOwn(CATEGORY_LABELS, row.category)))
      || typeof row.advice !== "string" || !Object.hasOwn(ADVICE, row.advice)
      || typeof row.as_of !== "string" || !/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(row.as_of) || !Number.isFinite(Date.parse(row.as_of))
      || !STATES.includes(String(row.classification_state)) || row.rules_state !== row.classification_state
      || !["temporary", "permanent", "unknown"].includes(String(row.severity))
      || !strings(row.reasons, 30) || !strings(row.restrictions, 20) || !row.restrictions.includes("no_automatic_retry")
      || !strings(row.matched_rules, 20)
      || row.engine_version !== "rejection-engine-v1-draft" || row.policy_version !== "rejection-advice-v1-draft"
      || row.rules_version !== "reason-rules-v1-draft" || row.taxonomy_version !== "reason-taxonomy-v1-draft") return invalid();
    seen.add(row.id);
    if ((row.classification_state === "classified") !== (row.category !== null)) return invalid();
    if (row.method === "unmapped" && row.matched_rules.length > 0) return invalid();
    return { id: row.id, category: row.category as PilotResult["category"], advice: row.advice as PilotResult["advice"],
      method: row.method, asOf: row.as_of, state: String(row.classification_state), severity: String(row.severity),
      reasons: [...row.reasons], restrictions: [...row.restrictions], matchedRules: [...row.matched_rules],
      versions: { engine: row.engine_version, policy: row.policy_version, rules: row.rules_version, taxonomy: row.taxonomy_version } };
  });
}
export function canOpenPilot(can: (p: string) => boolean, owner?: string): boolean {
  return Boolean(owner) && PILOT_PERMISSIONS.every(can);
}
export function pilotDate(value: string): string {
  return new Intl.DateTimeFormat("es-CL", { timeZone: "America/Santiago", dateStyle: "medium", timeStyle: "short", hourCycle: "h23" }).format(new Date(value));
}
