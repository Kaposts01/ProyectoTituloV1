import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiErrorCodeIs, friendlyError, getJson, postJson } from "./api";

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
    // El detalle crudo se conserva para quien lo necesite.
    expect(error.detail).toBe(detail);
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

  it("un detalle {code, message} con código conocido muestra el texto del catálogo, no el message del servidor", async () => {
    const error = await failure(422, { detail: { code: "invalid_rut", message: "texto del servidor distinto" } });
    expect(error.message).toBe("El RUT no es válido.");
    expect(error.code).toBe("invalid_rut");
    expect(error.status).toBe(422);
    expect(error.detail).toEqual({ code: "invalid_rut", message: "texto del servidor distinto" });
    expect(apiErrorCodeIs(error, "invalid_rut")).toBe(true);
    expect(apiErrorCodeIs(error, "invalid_session")).toBe(false);
  });

  it("un código conocido de bajas (cancellationError) también se traduce por catálogo", async () => {
    const error = await failure(409, { detail: { code: "open_request_exists", message: "x" } });
    expect(error.message).toBe("Ya existe una solicitud de baja abierta para esta suscripción. Resuélvala o retírela antes de crear otra.");
  });

  it("un código desconocido con message muestra el message (ya viene en español)", async () => {
    const error = await failure(409, { detail: { code: "codigo_nuevo_del_backend", message: "Mensaje fijo en español." } });
    expect(error.message).toBe("Mensaje fijo en español.");
    expect(error.code).toBe("codigo_nuevo_del_backend");
  });

  it("un código desconocido sin message (o con message vacío o no texto) usa el texto genérico del estado HTTP", async () => {
    expect((await failure(409, { detail: { code: "codigo_nuevo_del_backend" } })).message).toBe("La operación entra en conflicto con el estado actual. Actualiza e inténtalo de nuevo.");
    expect((await failure(503, { detail: { code: "codigo_nuevo_del_backend", message: "   " } })).message).toBe("El servicio no está disponible temporalmente. Inténtalo más tarde.");
    expect((await failure(500, { detail: { code: "codigo_nuevo_del_backend", message: 5 } })).message).toBe("Error interno del servidor. Inténtalo de nuevo en unos momentos.");
    expect((await failure(404, { detail: {} })).message).toBe("El recurso solicitado no fue encontrado.");
  });

  it("apiErrorCodeIs solo acepta un ApiError con ese código (un detail string no tiene código)", async () => {
    expect(apiErrorCodeIs(new Error("x"), "invalid_rut")).toBe(false);
    expect(apiErrorCodeIs(null, "invalid_rut")).toBe(false);
    expect(apiErrorCodeIs(await failure(400, { detail: "Invalid RUT" }), "invalid_rut")).toBe(false);
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
