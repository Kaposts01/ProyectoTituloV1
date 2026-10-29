# Casos de revision de frontend

| Solicitud | Evidencia esperada | Regresion que detectar |
| --- | --- | --- |
| Extraer listado de suscripciones de App.tsx | Misma pagina/filtros, ruta directa e historial, permisos y feedback | Reset de paginacion o solicitud duplicada |
| Cambiar rapidamente de VP1 a VP2 | Respuesta tardia de VP1 no reemplaza VP2; cache distingue cuentas | Race de fetch o clave incompleta |
| Cerrar sesion mientras carga un dashboard | La cache previa no reaparece al resolver la promesa | Invalidar el Map sin controlar respuesta en vuelo |

La compilacion prueba tipos y empaquetado, pero no demuestra accesibilidad ni comportamiento. Registra por separado lo comprobado con navegador y lo inferido del codigo.
