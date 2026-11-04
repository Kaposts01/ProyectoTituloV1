import { Badge } from "../billing/ui";
import { statusText, statusTone } from "./cancellationLabels";

/** Estado de la solicitud: punto + texto + color (nunca solo color). */
export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTone(status)}>{statusText(status)}</Badge>;
}
