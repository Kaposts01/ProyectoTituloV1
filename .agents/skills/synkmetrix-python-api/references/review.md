# Casos de revision de backend

| Solicitud | Evidencia esperada | Regresion que detectar |
| --- | --- | --- |
| Corregir que `/etl/core/all` devuelva proveedor desconocido | Peticion al literal resuelve el handler colectivo; un proveedor valido sigue funcionando | Captura por ruta dinamica, perdida de permisos/CSRF |
| Extraer logica de un endpoint largo | Mismas entradas, respuestas y efectos; error valida rollback y cierre de sesion | Commit adicional o error convertido en exito |
| Editar un cliente con telefono null | Contrato distingue omision de borrado y valor vacio segun comportamiento existente | Sobrescribir campos que el usuario no envio |

Ejemplos de activacion: agregar filtro API, refactorizar validacion, corregir permiso backend. No activar como unica skill para optimizar un indice o cambiar colores.
