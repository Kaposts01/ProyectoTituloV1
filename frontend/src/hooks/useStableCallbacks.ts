import { useLayoutEffect, useRef, useState } from "react";

type AnyFn = (...args: never[]) => unknown;

/**
 * Devuelve un objeto con las MISMAS funciones (mismas claves) pero con identidad estable entre renders: cada
 * envoltorio llama siempre a la versión más reciente de la función recibida. Sirve para pasar manejadores que
 * cierran sobre el estado de un componente grande (AppCore) a hijos con `memo` sin que el hijo se repinte en cada
 * render del padre (PERF-03f). El conjunto de claves debe ser fijo entre renders.
 */
export function useStableCallbacks<T extends Record<string, AnyFn | undefined>>(fns: T): T {
  const latest = useRef(fns);
  useLayoutEffect(() => { latest.current = fns; });
  const [stable] = useState(() => {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(fns)) {
      out[key] = (...args: unknown[]) => (latest.current[key] as ((...a: unknown[]) => unknown) | undefined)?.(...args);
    }
    return out as T;
  });
  return stable;
}
