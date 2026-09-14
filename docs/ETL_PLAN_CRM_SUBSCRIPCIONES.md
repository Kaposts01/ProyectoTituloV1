# Plan ETL - CRM Gestión de Suscripciones (Mandatos Físicos)

**Fecha de análisis:** 2026-09-12  
**Datos analizados:** 29 reportes mensuales (2017-2026)  
**Última actualización:** 20260831 TCH IG GESTION AGOSTO 2026

---

## 📋 Resumen Ejecutivo

Se propone un ETL para centralizar los datos de suscripciones de mandatos físicos desde reportes Excel mensuales a una base de datos relacional SQL. El modelo propuesto incluye **9 tablas principales** que normalizarán la información de 104 columnas en 5,644+ suscripciones activas + transacciones históricas.

**Volumen de datos (Agosto 2026):**
- Suscripciones vigentes: **5,644**
- Suscripciones eliminadas: **684**
- Cargos aceptados: **5,645**
- Cargos rechazados: **2,180**
- Total histórico (29 meses): **~150,000+ registros**

---

## 📊 Estructura Actual de Datos

### 1. **VIGENTES** (Datos Maestros)
Contiene todas las suscripciones activas con 104 columnas organizadas en secciones:

#### Bloque 1: Información de Centro de Costo y Captación (Col 1-7)
- Centro Costo
- Estrategia
- Origen / Campaña
- Lugar Captación
- Captador
- Ficha DUES
- Mandato DUES

#### Bloque 2: Datos del Socio (Col 8-17)
- Folio
- Socio RUT
- Referencia (Socio)
- Nombre
- Apellido
- Fecha Nacimiento
- Profesión
- Tipo Socio
- Ley
- Reajuste

#### Bloque 3: Datos del Titular de Cuenta (Col 18-22)
- Personalidad (Persona Natural/Jurídica)
- RUT (Titular)
- Referencia (Titular)
- Nombre (Titular)
- Apellidos (Titular)

#### Bloque 4: Antecedentes del Mandato (Col 23-104)
- Firma
- Tipo Mandato (PAC/PAS/DEC, etc.)
- Banco/Institución
- Tipo Cuenta
- Número Cuenta
- Ingreso
- Entrega Banco
- Fecha Activación
- ... y 76 columnas adicionales de transacciones históricas

### 2. **CARGOS ACEPTADOS** (Transacciones exitosas)
Detalle de cargos procesados correctamente:

```
Número Ficha | Número Mandato | Tipo Mandato | Entidad Recaudadora | Centro Costo
Origen | Captador | Ley | RUT | Nombre | Apellido | Transacción (1/2)
Numero Pagos del Mandato | Periodo | N° Cuota | Monto | Fecha Cargo | Estado
```

**Campos por fila:**
- (1) Número Ficha: Identificador único de la suscripción
- (2) Número Mandato: Identificador del mandato
- (3) Tipo Mandato: PAC, PAS, DEC
- (4) Entidad Recaudadora: Banco/Tarjeta que procesa el cargo
- (12) Transacción: Tipo (Reintento, Vencimiento, etc.)
- (13) Numero Pagos: Total de cuotas del mandato
- (14) Periodo: Mes de facturación (YYYY-MM)
- (15+) Monto, Fecha, Estado...

### 3. **CARGOS RECHAZADOS** (Transacciones fallidas)
Misma estructura que Cargos Aceptados pero con registros de fallos:
- Razón de rechazo
- Códigos de error bancarios
- Motivo (fondos insuficientes, tarjeta vencida, etc.)

### 4. **ELIMINADOS** (Histórico de bajas)
Suscripciones canceladas con:
- Fecha de eliminación
- Razón de baja
- Información completa del mandato al momento de la cancelación

### 5. **TABLAS** (Datos de Referencia)
Catalogos y dimensiones:
- **ENTIDADES:** Bancos y tarjetas (24 registros)
  - Nombre, Código Interno, Tipo, Código Grupo
  - Grupos: Bancos (1), Tarjetas (2), etc.

---

## 🗄️ Modelo de Datos Propuesto

### Diagrama Entidad-Relación (ER)

```
┌─────────────────────┐
│   clientes          │  (SOCIOS + Titulares de Cuenta)
├─────────────────────┤
│ id_cliente (PK)     │
│ rut                 │ (UNIQUE INDEX)
│ nombre              │
│ apellido            │
│ fecha_nacimiento    │
│ profesion           │
│ tipo_persona        │ (Natural/Jurídica)
│ created_at          │
└──────────┬──────────┘
           │
           │ 1:N
           │
┌──────────▼──────────────┐
│   suscripciones         │ (VIGENTES + ELIMINADOS)
├─────────────────────────┤
│ id_suscripcion (PK)     │
│ numero_ficha            │ (UNIQUE)
│ numero_mandato          │ (UNIQUE)
│ id_cliente (FK)         │
│ id_cliente_titular (FK) │
│ tipo_mandato            │ (PAC/PAS/DEC)
│ id_banco (FK)           │
│ tipo_cuenta             │
│ numero_cuenta           │
│ estado                  │ (VIGENTE/ELIMINADA)
│ fecha_activacion        │
│ fecha_eliminacion       │
│ razon_baja              │
│ id_origen (FK)          │
│ id_centro_costo (FK)    │
│ captador                │
│ ley                     │
│ reajuste                │
│ created_at              │
│ updated_at              │
└──────────┬──────────────┘
           │
           │ 1:N
           │
┌──────────▼──────────────────┐
│   transacciones_mensuales    │
├─────────────────────────────┤
│ id_transaccion (PK)         │
│ id_suscripcion (FK)         │
│ periodo                     │ (YYYY-MM)
│ numero_cuota                │
│ total_cuotas                │
│ monto                       │
│ fecha_cargo                 │
│ estado                      │ (ACEPTADA/RECHAZADA)
│ tipo_transaccion            │ (Cargo/Reintento/Venc)
│ fecha_creacion              │
└─────────────────────────────┘
           │
           │ 1:N
           │
┌──────────▼────────────────────┐
│   transacciones_detalles      │
├───────────────────────────────┤
│ id_detalle (PK)               │
│ id_transaccion (FK)           │
│ estado_detalle                │ (ACEPTADA/RECHAZADA)
│ codigo_respuesta              │ (Respuesta bancaria)
│ razon_rechazo                 │
│ entidad_recaudadora (FK)      │
│ fecha_procesamiento           │
└───────────────────────────────┘

┌─────────────────────┐
│   bancos            │
├─────────────────────┤
│ id_banco (PK)       │
│ nombre              │
│ codigo_interno      │
│ codigo_grupo        │
│ activo              │
└─────────────────────┘

┌─────────────────────┐
│   origenes          │
├─────────────────────┤
│ id_origen (PK)      │
│ nombre              │
└─────────────────────┘

┌──────────────────────┐
│   centros_costo      │
├──────────────────────┤
│ id_centro (PK)       │
│ nombre               │
│ estrategia           │
└──────────────────────┘
```

### 9 Tablas Principales

| Tabla | Propósito | Volumen | Actualización |
|-------|-----------|---------|--------------|
| `clientes` | Datos de socios y titulares | 10K+ | Incremental |
| `suscripciones` | Maestro de mandatos | 6K+ | Incremental |
| `transacciones_mensuales` | Detalles de cargos | 150K+ | Mensual |
| `transacciones_detalles` | Respuesta bancaria | 150K+ | Mensual |
| `bancos` | Catálogo de instituciones | 24 | Estático |
| `origenes` | Estrategias de captación | 20+ | Semi-estático |
| `centros_costo` | Centros de operación | 10+ | Semi-estático |
| `estados_suscripcion` | Valores posibles (VIGENTE/ELIMINADA) | 3-5 | Estático |
| `tipos_mandato` | Tipos: PAC, PAS, DEC, etc. | 5-10 | Estático |

---

## 🔄 Plan ETL

### Fase 1: Extracción

**Fuente:** Archivos Excel mensuales  
**Archivo patrón:** `YYYYMMDD TCH IG [GESTION] [MES] AAAA.XLSX`

**Archivos a procesar:**
```
Histórico completo: 29 archivos (2017-2026)
├─ 2017: 1 archivo (diciembre)
├─ 2018: 1 archivo (diciembre)
├─ 2019: 1 archivo (diciembre)
├─ 2020: 1 archivo (diciembre)
├─ 2021: 1 archivo (diciembre)
├─ 2022: 1 archivo (diciembre)
├─ 2023: 1 archivo (diciembre)
├─ 2024: 1 archivo (diciembre)
└─ 2025-2026: 17 archivos (enero - agosto 2026)
```

**Hojas a extraer:**
1. **VIGENTES** → Tabla `suscripciones` (estado='VIGENTE')
2. **ELIMINADOS** → Tabla `suscripciones` (estado='ELIMINADA')
3. **CARGOS ACEPTADOS** → Tabla `transacciones_mensuales` + `transacciones_detalles`
4. **CARGOS RECHAZADOS** → Tabla `transacciones_mensuales` + `transacciones_detalles`
5. **TABLAS** → Tablas de referencia (bancos, etc.)

### Fase 2: Transformación

**Operaciones principales:**
- Normalización de RUT (formato: `X.XXX.XXX-K`)
- Conversión de tipos de datos (fechas, montos)
- Validación de campos requeridos
- Deduplicación (mismo número de ficha/mandato en meses diferentes)
- Desagregación de columnas de transacciones (104 columnas → tabla mensual)
- Mapeo de valores (SOCIOS → Centro Costo, etc.)

**Campos clave a normalizar:**
```python
# RUT
rut_original = "7138947-2"  → "7.138.947-2"

# Fechas
fecha = "31/08/2026"  → "2026-08-31"

# Montos
monto = 50000  → Decimal(50000.00)

# Estados
estado_excel = "VIGENTE"  → estado = 1 / ENUM

# Periodos
periodo = "AGOSTO 2026"  → "2026-08"
```

### Fase 3: Carga

**Base de datos:** PostgreSQL / MySQL

**Estrategia:**
1. **Inicial (First Load):** Carga completa del histórico (29 archivos)
   - Desactivar constraints temporalmente
   - Inserción en batch (10K registros/lote)
   - Recalcular índices al finalizar
   - Validación de integridad referencial

2. **Incremental (Monthly Load):** Nuevo mes
   - Detectar duplicados por `numero_ficha` + `periodo`
   - UPDATE si existe, INSERT si es nuevo
   - Actualizar estado de suscripciones eliminadas

**Pseudocódigo:**
```sql
-- Transacción para mes nuevo
BEGIN;

-- 1. Cargar suscripciones nuevas
INSERT INTO suscripciones (...) 
SELECT ... FROM staging_vigentes 
WHERE numero_ficha NOT IN (SELECT numero_ficha FROM suscripciones);

-- 2. Actualizar suscripciones eliminadas
UPDATE suscripciones SET estado='ELIMINADA', fecha_eliminacion=NOW()
WHERE numero_ficha IN (SELECT numero_ficha FROM staging_eliminados);

-- 3. Cargar transacciones
INSERT INTO transacciones_mensuales (...)
SELECT ... FROM staging_cargos_aceptados
WHERE (id_suscripcion, periodo) NOT IN (
  SELECT id_suscripcion, periodo FROM transacciones_mensuales
);

-- 4. Validar integridad
SELECT COUNT(*) FROM transacciones_mensuales WHERE id_suscripcion IS NULL; -- Debe ser 0

COMMIT;
```

---

## 📝 Script SQL - Creación de Tablas

```sql
-- Tabla: clientes
CREATE TABLE clientes (
    id_cliente INT PRIMARY KEY AUTO_INCREMENT,
    rut VARCHAR(15) UNIQUE NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    fecha_nacimiento DATE,
    profesion VARCHAR(100),
    tipo_persona ENUM('Natural', 'Jurídica') DEFAULT 'Natural',
    tipo_socio VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_rut (rut),
    INDEX idx_nombre_apellido (nombre, apellido)
);

-- Tabla: bancos
CREATE TABLE bancos (
    id_banco INT PRIMARY KEY AUTO_INCREMENT,
    nombre VARCHAR(100) UNIQUE NOT NULL,
    codigo_interno INT,
    codigo_grupo INT,  -- 1=Bancos, 2=Tarjetas
    activo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla: tipos_mandato
CREATE TABLE tipos_mandato (
    id_tipo INT PRIMARY KEY AUTO_INCREMENT,
    codigo VARCHAR(10) UNIQUE NOT NULL,  -- PAC, PAS, DEC
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT
);

-- Tabla: origenes
CREATE TABLE origenes (
    id_origen INT PRIMARY KEY AUTO_INCREMENT,
    nombre VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla: centros_costo
CREATE TABLE centros_costo (
    id_centro INT PRIMARY KEY AUTO_INCREMENT,
    nombre VARCHAR(100) UNIQUE NOT NULL,
    estrategia VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla: suscripciones (CENTRAL - contiene VIGENTES + ELIMINADOS)
CREATE TABLE suscripciones (
    id_suscripcion INT PRIMARY KEY AUTO_INCREMENT,
    numero_ficha INT UNIQUE NOT NULL,
    numero_mandato INT UNIQUE NOT NULL,
    id_cliente INT NOT NULL,
    id_cliente_titular INT,  -- En caso de ser diferente
    id_tipo_mandato INT NOT NULL,
    id_banco INT NOT NULL,
    tipo_cuenta VARCHAR(50),  -- Checking, Savings, Credit Card, etc.
    numero_cuenta VARCHAR(50),
    
    -- Datos de captación
    id_origen INT,
    id_centro_costo INT,
    captador VARCHAR(100),
    
    -- Mandato info
    ley VARCHAR(50),
    reajuste BOOLEAN,
    firma_presente BOOLEAN,
    
    -- Fechas
    fecha_activacion DATE,
    fecha_ingreso DATE,
    fecha_entrega_banco DATE,
    fecha_eliminacion DATE,
    razon_baja VARCHAR(255),
    
    -- Estado
    estado ENUM('VIGENTE', 'ELIMINADA', 'SUSPENDIDA') DEFAULT 'VIGENTE',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Índices
    INDEX idx_numero_ficha (numero_ficha),
    INDEX idx_numero_mandato (numero_mandato),
    INDEX idx_cliente (id_cliente),
    INDEX idx_banco (id_banco),
    INDEX idx_estado (estado),
    INDEX idx_fecha_activacion (fecha_activacion),
    
    -- Foreign Keys
    CONSTRAINT fk_cliente FOREIGN KEY (id_cliente) REFERENCES clientes(id_cliente),
    CONSTRAINT fk_cliente_titular FOREIGN KEY (id_cliente_titular) REFERENCES clientes(id_cliente),
    CONSTRAINT fk_tipo_mandato FOREIGN KEY (id_tipo_mandato) REFERENCES tipos_mandato(id_tipo),
    CONSTRAINT fk_banco FOREIGN KEY (id_banco) REFERENCES bancos(id_banco),
    CONSTRAINT fk_origen FOREIGN KEY (id_origen) REFERENCES origenes(id_origen),
    CONSTRAINT fk_centro_costo FOREIGN KEY (id_centro_costo) REFERENCES centros_costo(id_centro)
);

-- Tabla: transacciones_mensuales (cargos por período)
CREATE TABLE transacciones_mensuales (
    id_transaccion INT PRIMARY KEY AUTO_INCREMENT,
    id_suscripcion INT NOT NULL,
    periodo VARCHAR(7) NOT NULL,  -- YYYY-MM format
    numero_cuota INT,
    total_cuotas INT,
    monto DECIMAL(10, 2),
    fecha_cargo DATE,
    
    -- Tipos de transacción: Cargo Normal, Reintento, Vencimiento, etc.
    tipo_transaccion VARCHAR(50),
    
    -- Resultado consolidado
    estado_consolidado ENUM('ACEPTADA', 'RECHAZADA', 'PARCIAL') DEFAULT 'ACEPTADA',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_suscripcion (id_suscripcion),
    INDEX idx_periodo (periodo),
    INDEX idx_fecha_cargo (fecha_cargo),
    INDEX idx_estado (estado_consolidado),
    
    CONSTRAINT fk_suscripcion FOREIGN KEY (id_suscripcion) REFERENCES suscripciones(id_suscripcion),
    UNIQUE KEY unique_suscripcion_periodo (id_suscripcion, periodo)
);

-- Tabla: transacciones_detalles (respuesta de banco)
CREATE TABLE transacciones_detalles (
    id_detalle INT PRIMARY KEY AUTO_INCREMENT,
    id_transaccion INT NOT NULL,
    id_banco_procesador INT,  -- Banco que procesa (puede ser diferente)
    
    estado_detalle ENUM('ACEPTADA', 'RECHAZADA', 'PENDIENTE') DEFAULT 'ACEPTADA',
    codigo_respuesta VARCHAR(20),  -- Código del banco (0 = OK, etc.)
    razon_rechazo VARCHAR(255),
    
    fecha_procesamiento TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_transaccion (id_transaccion),
    INDEX idx_estado (estado_detalle),
    
    CONSTRAINT fk_transaccion FOREIGN KEY (id_transaccion) 
        REFERENCES transacciones_mensuales(id_transaccion),
    CONSTRAINT fk_banco_procesador FOREIGN KEY (id_banco_procesador) 
        REFERENCES bancos(id_banco)
);

-- Tabla: datos_auditoria (para tracking de imports)
CREATE TABLE datos_auditoria (
    id_auditoria INT PRIMARY KEY AUTO_INCREMENT,
    tipo_import VARCHAR(50),  -- 'FULL_LOAD', 'MONTHLY'
    archivo_origen VARCHAR(255),
    fecha_import TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    registros_procesados INT,
    registros_insertados INT,
    registros_actualizados INT,
    registros_error INT,
    estado ENUM('EXITOSO', 'ERROR_PARCIAL', 'FALLIDO') DEFAULT 'EXITOSO',
    detalle_error TEXT
);
```

---

## 🚀 Implementación por Fase

### Fase 1: Setup Inicial (Semana 1)
- [ ] Crear base de datos PostgreSQL/MySQL
- [ ] Ejecutar script de creación de tablas
- [ ] Crear índices y constraints
- [ ] Configurar backups automáticos

### Fase 2: ETL de Carga Histórica (Semana 2-3)
- [ ] Desarrollar Python/Node script de lectura Excel
- [ ] Implementar transformaciones de datos
- [ ] Cargar catálogos (bancos, tipos_mandato)
- [ ] Carga inicial (29 archivos históricos)
- [ ] Validación de integridad

### Fase 3: ETL Mensual Automatizado (Semana 4)
- [ ] Script de carga mensual
- [ ] Detección de duplicados y updates
- [ ] Generación de reportes de import
- [ ] Alertas en caso de error
- [ ] Scheduling (cron/task scheduler)

### Fase 4: Integración con CRM (Semana 5+)
- [ ] APIs REST para leer datos
- [ ] Dashboards de monitoreo
- [ ] Alertas para reintentos de cobro
- [ ] Modelo de IA para predicción

---

## 📊 Queries Útiles para Validación

```sql
-- Ver suscripciones más recientes
SELECT * FROM suscripciones ORDER BY created_at DESC LIMIT 10;

-- Transacciones por mes
SELECT periodo, estado_consolidado, COUNT(*) as cantidad, SUM(monto) as total
FROM transacciones_mensuales
GROUP BY periodo, estado_consolidado
ORDER BY periodo DESC;

-- Tasa de rechazo por banco
SELECT b.nombre, 
       COUNT(*) as total_cargos,
       SUM(CASE WHEN td.estado_detalle = 'RECHAZADA' THEN 1 ELSE 0 END) as rechazados,
       ROUND(100.0 * SUM(CASE WHEN td.estado_detalle = 'RECHAZADA' THEN 1 ELSE 0 END) / COUNT(*), 2) as tasa_rechazo
FROM transacciones_detalles td
JOIN bancos b ON td.id_banco_procesador = b.id_banco
GROUP BY b.id_banco, b.nombre
ORDER BY tasa_rechazo DESC;

-- Clientes con múltiples mandatos
SELECT c.nombre, c.apellido, COUNT(*) as mandatos_activos
FROM clientes c
JOIN suscripciones s ON c.id_cliente = s.id_cliente
WHERE s.estado = 'VIGENTE'
GROUP BY c.id_cliente
HAVING COUNT(*) > 1
ORDER BY mandatos_activos DESC;
```

---

## 🔒 Consideraciones de Seguridad y Privacidad

- **Encriptación:** RUT y datos sensibles en tránsito y en reposo
- **Acceso:** Control de roles (admin, analyst, viewer)
- **Auditoría:** Log de todo acceso a datos de clientes
- **Retención:** Política de retención de datos (cumplir PDPA Chile)
- **Validación:** Validar integridad de imports antes de producción

---

## 📈 Roadmap Futuro

1. **Machine Learning para Reintentos:** Predicción de cargos rechazados
2. **Alertas Automáticas:** Notificaciones para tarjetas vencidas
3. **Analytics Avanzado:** Dashboard de KPIs por estrategia
4. **Integración Multi-Canal:** Incluir donaciones web, SMS, etc.
5. **Reconciliación Automática:** Validar montos con reportes bancarios

---

**Preparado por:** Esteban (Techo Chile)  
**Próximos pasos:** Validar modelo de datos y comenzar implementación de BD
