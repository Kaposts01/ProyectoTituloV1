# Desarrollo local y validacion con los datos del socio

ML-11 (2026-11-25): [API sintetica apagada y matriz de permisos](ML-11-API-PERMISOS.md),569 pruebas aprobadas incluidas39 nuevas. El socio revisara capacidad ML+cuenta+recurso, actores independientes, privacidad/contexto de glosas y custodia de archivos/clave. Doce permisos nuevos sin grants de migracion; el sembrador explicito de admin conserva su acceso al catalogo completo, soporte/ejecutivo no heredan ML por .view. 0086 solo en base descartable; no habilitar sobre datos restaurados/operativos renombrando la base o marcando synthetic=true. No hay inferencia/entrenamiento/activacion real o uploads; modelos, evaluacion, cargador e interfaz piloto requieren sus siguientes autorizaciones.

ML-10 (2026-11-25): [guia de lotes durables](ML-10-LOTES-SOMBRA.md). Preparacion probada solo con fixtures en crm_ml_registry_test y bandera apagada; 518 pruebas pasan. No ejecutar sobre una base con datos reales cambiando simplemente synthetic=true o su nombre. El socio debe auditar fronteras de commit de los ETL (incluido TCH), persistencia/custodia de snapshots al corte, enumeracion de candidatos, conciliacion/cobertura y entorno destino antes de conectar un flujo operativo. No hay hooks automaticos o inferencia real. Resultados, errores y reanudacion se mantienen separados de sync/write/etl runs; 0085 no se aplico a QA/original. ML-11/activacion requieren solicitud posterior.

ML-09 (2026-11-25): [guia del motor en sombra](ML-09-MOTOR-POLITICA.md). El socio debe auditar estados por cuenta/recurso, glosas/enlaces, relojes/cobertura y conciliacion de pagos completos/parciales/reversos; no convertir updated_at en cobertura o estado activo en mandato vigente. Lector actual no certifica conciliacion y bloquea sugerencias de gestion. Motor sin modelos usa reglas/revision, con ejecucion prohibida y probabilidad real nula; solo fixtures permiten probar P1/P2 simulados. 388 pruebas funcionales pasan, sin datos/modelos reales ni activacion. Identidad logica reproducible no equivale a almacenamiento durable; lotes/persistencia/API/inferencia confiable requieren sus siguientes entregas.

Contexto confirmado por el usuario, 2026-11-24: este equipo tiene una parte de los datos; su socio conserva practicamente todos los datos de los distintos proveedores y realizara las pruebas con ellos. El usuario participa en UX, modelos y otras partes del proyecto. No se inspecciono el entorno del socio ni se certifico su cobertura.

## Responsabilidades y significado de terminado

| Trabajo | Donde y quien | Evidencia necesaria |
|---|---|---|
| Definiciones, diseño y codigo de pipelines/modelos | Usuario con asistencia en este checkout | Contratos revisados y codigo probado; no implica ajuste estadistico real. |
| Pruebas funcionales, negativas, privacidad y seguridad | Aqui antes de la entrega; repetibles por el socio | Fixtures sinteticos, fallos recuperables, permisos, idempotencia y compatibilidad. No deben esperar a que el socio descubra errores basicos. |
| Auditoria de cobertura y etiquetas reales | Socio, en copia controlada de su entorno | Conteos por fuente, fechas, enlaces rechazo/pago, madurez de resultados y calidad de etiquetas. Tener muchos datos no garantiza que sirvan para P2. |
| Entrenamiento, calibracion y comparacion con datos completos | Socio, cuando corresponda y este autorizado | Particiones cronologicas de desarrollo, configuracion reproducible, metricas y artefactos trazables. Sin entrenar en este paso actual. |
| Test reservado e integracion con datos representativos | Socio, despues del ajuste | Informe fuera de muestra por canal y clase, calibracion, tiempos/recursos, permisos y discrepancias. |
| Aceptacion y activacion | Revision conjunta de evidencia; responsable de negocio cuando aplique | Resultado documentado contra criterios previos, riesgos y rollback. Un test funcional verde no autoriza activar. |

Cada entrega distingue: **implementado**, **probado funcionalmente**, **entrenado**, **evaluado con datos reales** y **autorizado para activar**. No cerrar ML-07 por terminar el runner ni mostrar una probabilidad validada por usar un modelo ajustado con fixtures. P1 puede avanzar sin P2 y cada canal conserva su propia condicion de cobertura.

ML-04 (2026-11-25) entrega [diccionario de variables, contratos y politica temporal experimental](ML-04-DATASET-TEMPORAL.md), con pruebas funcionales sinteticas. El socio debe validar relojes, enlaces y cobertura; revisar la politica de primera deteccion/un episodio por obligacion, monedas y exclusiones antes del dataset real. No hay aun adaptador SQL, exportador ni runner de entrenamiento; las pruebas puras se pueden repetir sin datos o conexiones. ML-05/06 implementaran las siguientes piezas tras solicitud; no extraer datos ni entrenar por haber completado ML-04.

ML-05 (2026-11-25) añade [exportador offline y comandos reales](ML-05-EXPORTACION.md), con snapshot JSON estricto, manifiesto y almacenamiento privado. Ya se pueden probar/exportar contratos ML-04 verificados sin entrenar. Sigue pendiente el mapeo SQL desde los datos completos del socio: auditar disponibilidad historica, vinculos y cobertura antes de producir snapshots reales. El socio conserva consultas/originales/clave y paquetes en su entorno; devuelve solo agregados saneados. El manifiesto firmado verifica integridad, no certifica la calidad de las fuentes ni autoriza ML-06/07 automaticamente.

ML-06 (2026-11-25) prepara [protocolo y planificador aislado](ML-06-EVALUACION.md), sin ajustar modelos. El socio puede autenticar un paquete ML-05 y generar particiones privadas con purga temporal, criterios preinscritos y grupos; no se interpretan etiquetas del test ni se calculan metricas de modelos. Cuatro etapas separan entrenamiento, calibracion, seleccion y test. Debe acordar criterios/soporte/potencia, auditar disponibilidad real de etiquetas y designar custodia antes de ML-07. Un preflight verde no valida estadisticamente ni abre permiso de entrenamiento/activacion. Runners de entrenamiento y benchmark reales aun pendientes; no comunicar probabilidades o ganadores a partir de fixtures.

ML-07 (2026-11-25) entrega [evaluador offline y comandos](ML-07-EVALUAR-MODELOS.md) para predicciones ya emitidas por pipelines externos congelados; no contiene entrenadores ni carga pesos. El socio debera producir/auditar predicciones reales, hashes de modelos/preprocesamiento/calibrador/politica y filas de ajuste. Solo entonces podra evaluar seleccion, registrar aprobacion/congelacion y abrir el test una vez. El registro se consume incluso ante fallo posterior; no borrarlo para repetir. Informes privados con metricas, soporte, cobertura e intervalos no autorizan activar: compartir agregados saneados y mantener decision conjunta. Pruebas locales solo con predicciones ficticias manuales, sin modelos entrenados o cargados.

ML-08 (2026-11-25) añade [pipelines construibles sin ajustar y registro preparado](ML-08-PIPELINES-ARTEFACTOS.md). El socio puede repetir construccion en el entorno experimental fijado y preparar/verificar manifiestos privados, sin ajustar. Debe respetar feature_matrix, cortes ML-04/06 y procedencia/evaluacion ML-07 de pesos/predicciones reales. Registro SQL/auditoria solo probados en base descartable: no migrar QA/original ni activar por ejecutar el CLI de archivos. Promocion real, cargador y permisos pendientes de ML-09/11. Datos, entrenamiento/calibracion externos, entorno destino y calidad estadistica requieren su validacion.

## Paquete de entrega futuro

1. Commit o version de codigo y entorno de dependencias bloqueado; compatibilidad de Python/OS verificada en el entorno receptor.
2. Contrato de entrada, lista blanca, definiciones del objetivo, episodios, corte, monedas, nulos, exclusiones y versiones de normalizacion/taxonomia.
3. Procedimiento de preflight y comandos reales para auditoria, pruebas, preparacion, entrenamiento, calibracion y evaluacion. Esos runners aun no estan implementados; no inventar instrucciones ejecutables que apunten a archivos inexistentes.
4. Prueba de humo sintetica separada del experimento real; configuracion sin secretos, limites CPU/memoria y banderas apagadas.
5. Protocolo y criterios fijados antes de evaluar: particiones, purga temporal a 30 dias, grupos de obligaciones, metricas por canal/clase, incertidumbre y abstencion. El test reservado no ajusta vocabulario, hiperparametros, calibracion o umbrales; si se usa para corregir, deja de ser test reservado.
6. Formato de informe saneado y checklist de activacion/rollback, sin habilitar llamadas a proveedores para comprobar el modelo.

El auditor actual `scripts/ml/audit_readiness.py` admite explicitamente QA local en loopback:5433 con nombre `crm_qa_*`. No asumir que el socio tiene esa configuracion ni pedirle renombrar una base operativa para superar la guarda. La adaptacion del runner a su copia aislada requiere conocer y verificar su destino sin exponer credenciales, manteniendo transacciones de solo lectura en auditorias y pruebas fuera de datos operativos.

## Evidencia que debe devolver

- Version de codigo, Python/librerias, esquema de variables, reglas, modelo y configuracion; identificador interno no personal del dataset y fecha de corte. Sin URL de conexion o paths con nombres personales.
- Conteos por proveedor, eventos/obligaciones independientes, etiquetas por clase, ventanas observables, exclusiones y desconocidos. Explicar diferencias entre el dataset del socio y la QA parcial auditada.
- Rangos de entrenamiento/calibracion/test y numero de resultados maduros; trazabilidad de pago de la misma obligacion, sin IDs o glosas individuales en el informe compartido.
- P1: baseline de reglas, F1 macro, precision/recall por clase, cobertura y abstencion, glosas no vistas. P2: baseline, Brier/calibracion, discriminacion y metricas por canal con incertidumbre.
- Fallos saneados, tiempos, memoria/CPU y prueba de fallback sin artefacto o con entrada incompleta. Resultados limitados a los canales realmente evaluados.
- Conclusion: cumple/no cumple cada criterio acordado, limitaciones y correcciones requeridas. No declarar mejora causal de recuperacion por un benchmark retrospectivo.

Los datos completos, ejemplos sensibles y artefactos no revisados se quedan bajo control del socio. Compartir solo resultados revisados; agrupar o suprimir celdas pequeñas cuando puedan identificar casos. No hacen falta credenciales del socio ni copiar su base para desarrollar la implementacion local. Ninguna comunicacion o publicacion se ejecuta automaticamente.
