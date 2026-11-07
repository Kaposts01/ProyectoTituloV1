import { formatRut } from "./rut";

/**
 * RUT en JetBrains Mono con el formato único `12.345.678-9` (QA-08; DESIGN.md: todo valor que viene del sistema va
 * en mono). Si no es un RUT válido se muestra tal cual con la marca «no válido» (texto, no solo color).
 */
export function Rut({ value, fallback = "—" }: { value: unknown; fallback?: string }) {
  const rut = formatRut(value);
  if (!rut) return <>{fallback}</>;
  if (rut.valid) return <span className="mono rut">{rut.text}</span>;
  return (
    <span className="mono rut rut-invalid" title="RUT no válido: el formato o el dígito verificador no calzan">
      {rut.text} <span className="rut-invalid-tag">no válido</span>
    </span>
  );
}
