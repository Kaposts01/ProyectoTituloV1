import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiDetailIs, friendlyError, getJson, postJson } from "./api";

function respond(status: number, body: unknown) {
  return {
    ok: status < 400,
    status,
    headers: { get: (key: string) => (key.toLowerCase() === "content-type" ? "application/json" : null) },
    json: async () => body,
  };
}

async function failure(status: number, body: unknown): Promise<ApiError> {
  vi.stubGlobal("fetch", vi.fn(async () => respond(status, body)));
  try {
    await getJson("/x");
  } catch (error) {
    return error as ApiError;
  }
  throw new Error("debía fallar");
}

beforeEach(() => vi.spyOn(console, "warn").mockImplementation(() => {}));
afterEach(() => vi.unstubAllGlobals());

describe("errores de la API en español (paso 11)", () => {
  it.each([
    [401, "Authentication required", "Debes iniciar sesión para continuar."],
    [401, "Invalid username or password", "Usuario o contraseña incorrectos."],
    [403, "Permission denied", "No tienes permiso para realizar esta acción."],
    [403, "Invalid CSRF token", "Sesión desactualizada. Recarga la página e inténtalo de nuevo."],
    [404, "Staging record not found", "Registro no encontrado."],
    [409, "Username already exists", "Ya existe un usuario con ese nombre."],
    [409, "VirtualPOS writes are disabled", "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."],
    [400, "Invalid RUT", "El RUT no es válido."],
    [400, "date_from must be earlier than date_to", "La fecha inicial debe ser anterior a la fecha final."],
    [502, "VirtualPOS rejected the plan", "VirtualPOS rechazó el plan."],
  ])("el detalle %i «%s» se muestra traducido", async (status, detail, expected) => {
    const error = await failure(status, { detail });
    expect(error.message).toBe(expected);
    // El detalle crudo se conserva para quien decida por él (p. ej. «Invalid RUT» marca el campo).
    expect(error.detail).toBe(detail);
    expect(apiDetailIs(error, detail)).toBe(true);
  });

  it("un detalle con datos variables se traduce por patrón", async () => {
    expect((await failure(400, { detail: "date_to must use YYYY-MM-DD" })).message).toBe("El parámetro date_to debe tener el formato AAAA-MM-DD.");
    expect((await failure(400, { detail: "Unknown channel: zz. Valid: a, b" })).message).toBe("Canal desconocido: zz.");
  });

  it("un detalle que el catálogo no conoce se muestra tal cual (texto libre del backend, casi siempre en español)", async () => {
    expect((await failure(404, { detail: "Suscripción no encontrada" })).message).toBe("Suscripción no encontrada");
  });

  it("sin detalle usa el texto genérico del estado HTTP", async () => {
    expect((await failure(500, {})).message).toBe("Error interno del servidor. Inténtalo de nuevo en unos momentos.");
    expect((await failure(404, null)).message).toBe("El recurso solicitado no fue encontrado.");
  });

  it("un detalle estructurado {code, message} expone el código y no muestra el mensaje crudo", async () => {
    const error = await failure(409, { detail: { code: "subscription_busy", message: "raw english message" } });
    expect(error.code).toBe("subscription_busy");
    expect(error.message).toBe("La operación entra en conflicto con el estado actual. Actualiza e inténtalo de nuevo.");
    expect(error.message).not.toContain("raw english");
    expect(error.detail).toEqual({ code: "subscription_busy", message: "raw english message" });
  });

  it("errores de validación (422): campo en español y motivo traducido por tipo", async () => {
    const error = await failure(422, {
      detail: [
        { loc: ["body", "amount"], msg: "Field required", type: "missing" },
        { loc: ["body", "phone_number"], msg: "String should have at least 5 characters", type: "string_too_short" },
        { loc: ["body", "frequency_type"], msg: "Input should be a valid integer", type: "int_parsing" },
        { loc: ["query", "zz_campo"], msg: "Something new", type: "algo_nuevo" },
      ],
    });
    expect(error.message).toBe("Monto: es obligatorio; Teléfono: es demasiado corto; Frecuencia: debe ser un número entero; query → zz_campo: valor no válido");
    expect(error.message).not.toMatch(/required|should|valid integer/i);
  });

  it("un error de validación con mensaje propio en español lo conserva", async () => {
    const error = await failure(422, { detail: [{ loc: ["body", "social_id"], msg: "Value error, El RUT no es válido.", type: "value_error" }] });
    expect(error.message).toBe("RUT documento: El RUT no es válido.");
  });

  it("friendlyError sigue devolviendo el mensaje y el texto de reserva", () => {
    expect(friendlyError(new ApiError("hola", 400, null))).toBe("hola");
    expect(friendlyError(new TypeError("Failed to fetch"))).toBe("No se pudo conectar con el servidor. Verifica tu conexión.");
    expect(friendlyError("zz", "reserva")).toBe("reserva");
  });

  it("una respuesta que no es JSON válido no muestra el mensaje en inglés del navegador", () => {
    expect(friendlyError(new SyntaxError("Unexpected token < in JSON at position 0"))).toBe("La respuesta del servidor no tiene el formato esperado.");
  });

  it("también aplica a las escrituras (POST)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond(403, { detail: "Permission denied" })));
    await expect(postJson("/x", { a: 1 })).rejects.toMatchObject({ message: "No tienes permiso para realizar esta acción.", status: 403 });
  });
});
