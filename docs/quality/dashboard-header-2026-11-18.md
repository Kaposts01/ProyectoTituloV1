# Cabecera del Dashboard — 2026-11-18

- Un solo titulo Dashboard, sin repetirlo en una ruta visual. Subtitulo con el mes mostrado.
- Mes y canales en una fila de filtros independiente, con etiquetas legibles y casillas sin chips decorativos. Conserva seleccion, permisos y contratos existentes.
- Aviso breve de mes en curso: datos parciales y comparaciones de flujo disponibles al cierre. El boton existente permite ver el ultimo mes cerrado.
- Actualizacion de datos en un desplegable cerrado inicialmente. Su resumen informa cuantos canales requieren revision; al abrir se ve el estado por canal y la fecha TCH existente. El momento de generar la vista queda dentro, explicado como distinto de la actualizacion de canales. No anuncia todos al dia cuando faltan estados.
- Teclado nativo en el desplegable, foco visible, temas claro/oscuro y reserva de espacio para el menu movil. Sin cambios de KPIs, formulas, API, datos ni dependencias.
- Validacion: 40 pruebas de Dashboard, alertas, detalle/contexto y orientacion; lint y TypeScript/build sin errores, con avisos React previos. Chrome local autenticado comprueba filtros, mes cerrado/actual, teclado, estado desplegable, titulo unico y vistas de 1366, 390 y 320px sin desbordamiento tras completar el ajuste de Recharts. API limitada a GET tras login.
- Capturas locales ignoradas .local/dashboard-header-*.png, solo controles y datos agregados. Skills personales intactas y excluidas; entrega local, sin push.
