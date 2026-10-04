#!/usr/bin/env python3
"""
ETL Script - Carga de reportes TCH a Base de Datos
Para: Proyecto Título - CRM Suscripciones (Techo Chile)

Uso:
    python3 etl_script.py --file "20260831 TCH IG GESTION AGOSTO 2026.XLSX" --mode full
    python3 etl_script.py --file "latest" --mode incremental
"""

import pandas as pd
import openpyxl
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
import logging
import sys
import re
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json

# ====== CONFIGURACIÓN ======

DB_CONFIG = {
    'host': 'localhost',
    'user': 'etl_user',
    'password': 'secure_password',
    'database': 'techo_crm_db',
    'autocommit': False,
    'use_pure': True
}

EXCEL_DIR = Path('/home/usuario/reportes_tch')
LOG_FILE = 'etl_import.log'
AUDIT_TABLE = 'datos_auditoria'

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ====== NORMALIZACIÓN DE DATOS ======

class DataNormalizer:
    """Limpieza y normalización de datos"""

    @staticmethod
    def normalize_rut(rut: str) -> str:
        """
        Normalizar RUT: "7138947-2" -> "7.138.947-2"
        """
        if not rut or pd.isna(rut):
            return None

        rut = str(rut).strip().upper()

        # Eliminar caracteres no válidos
        rut = re.sub(r'[^\dK-]', '', rut)

        # Si no tiene guión, agregar
        if '-' not in rut:
            rut = rut[:-1] + '-' + rut[-1]

        # Agregar puntos
        numero, dv = rut.split('-')
        numero = int(numero)
        rut_formateado = f"{numero:,}".replace(',', '.')

        return f"{rut_formateado}-{dv}"

    @staticmethod
    def parse_date(date_val) -> Optional[str]:
        """
        Convertir fechas a formato ISO (YYYY-MM-DD)
        Maneja múltiples formatos: "31/08/2026", "2026-08-31", datetime
        """
        if pd.isna(date_val) or date_val is None:
            return None

        try:
            if isinstance(date_val, str):
                # Intentar formato DD/MM/YYYY
                if '/' in date_val:
                    parts = date_val.split('/')
                    if len(parts) == 3:
                        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                        return f"{year:04d}-{month:02d}-{day:02d}"
                # Intentar formato YYYY-MM-DD
                elif '-' in date_val:
                    return date_val[:10]

            # Si es datetime
            elif hasattr(date_val, 'date'):
                return date_val.date().isoformat()

        except Exception as e:
            logger.warning(f"No se pudo parsear fecha: {date_val} ({e})")

        return None

    @staticmethod
    def parse_currency(amount) -> Optional[float]:
        """Convertir moneda a decimal"""
        if pd.isna(amount) or amount is None:
            return None

        try:
            if isinstance(amount, str):
                amount = amount.replace('$', '').replace('.', '').replace(',', '.')
            return float(amount)
        except:
            return None

    @staticmethod
    def normalize_string(text: str, max_len: int = None) -> Optional[str]:
        """Normalizar strings: trim, strip diacritics"""
        if pd.isna(text) or text is None:
            return None

        text = str(text).strip()
        if max_len:
            text = text[:max_len]

        return text if text else None

# ====== LECTURA DE EXCEL ======

class ExcelReader:
    """Lee y parsea archivos Excel TCH"""

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.wb = openpyxl.load_workbook(filepath, data_only=True)
        self.metadata = self._extract_metadata()

    def _extract_metadata(self) -> Dict:
        """Extraer información de la fecha del reporte"""
        filename = self.filepath.stem

        # Patrón: "20260831 TCH IG GESTION AGOSTO 2026"
        match = re.search(r'(\d{8})', filename)
        if match:
            date_str = match.group(1)
            fecha = datetime.strptime(date_str, '%Y%m%d')
            return {
                'fecha_reporte': fecha,
                'periodo': fecha.strftime('%Y-%m'),
                'fecha_archivo': filename
            }

        logger.warning(f"No se pudo extraer fecha de {filename}")
        return {}

    def read_vigentes(self) -> pd.DataFrame:
        """Leer hoja VIGENTES (suscripciones activas)"""
        ws = self.wb['VIGENTES']

        # Los encabezados están en filas 6-7
        df = pd.read_excel(
            self.filepath,
            sheet_name='VIGENTES',
            header=[5, 6],  # Filas 6-7 como encabezados
            skiprows=8      # Saltar hasta fila 9 (datos)
        )

        return df

    def read_cargos_aceptados(self) -> pd.DataFrame:
        """Leer hoja CARGOS ACEPTADOS"""
        df = pd.read_excel(
            self.filepath,
            sheet_name='CARGOS ACEPTADOS',
            header=[5, 6],  # Rows 6-7
            skiprows=7
        )

        return df

    def read_cargos_rechazados(self) -> pd.DataFrame:
        """Leer hoja CARGOS RECHAZADOS"""
        df = pd.read_excel(
            self.filepath,
            sheet_name='CARGOS RECHAZADOS',
            header=[5, 6],
            skiprows=7
        )

        return df

    def read_eliminados(self) -> pd.DataFrame:
        """Leer hoja ELIMINADOS (suscripciones canceladas)"""
        df = pd.read_excel(
            self.filepath,
            sheet_name='ELIMINADOS',
            header=[5, 6],
            skiprows=8
        )

        return df

    def read_tablas(self) -> Dict[str, pd.DataFrame]:
        """Leer catálogos de la hoja TABLAS"""
        ws = self.wb['TABLAS']

        # Buscar secciones en TABLAS (ej: "ENTIDADES")
        tablas = {}

        # ENTIDADES
        df_entidades = pd.read_excel(
            self.filepath,
            sheet_name='TABLAS',
            header=2,  # Fila 3 es encabezado
            nrows=25   # ~25 instituciones
        )
        tablas['entidades'] = df_entidades

        return tablas

# ====== TRANSFORMACIÓN ======

class DataTransformer:
    """Transforma datos crudos a formato de BD"""

    def __init__(self, normalizer: DataNormalizer):
        self.normalizer = normalizer

    def transform_vigentes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transformar datos de VIGENTES para tabla suscripciones"""

        df_out = pd.DataFrame()

        # Mappear columnas importantes
        # Nota: nombres de columnas pueden variar, adaptar según estructura real

        df_out['numero_ficha'] = df[('SOCIO', 'Folio')] if ('SOCIO', 'Folio') in df.columns else df[('TCH', 'Folio')]
        df_out['numero_mandato'] = df[('MANDATO', 'MANDATO DUES')]
        df_out['rut_socio'] = df[('SOCIO', 'Rut')].apply(self.normalizer.normalize_rut)
        df_out['nombre_socio'] = df[('SOCIO', 'Nombre')].apply(self.normalizer.normalize_string)
        df_out['apellido_socio'] = df[('SOCIO', 'Apellido')].apply(self.normalizer.normalize_string)
        df_out['tipo_mandato'] = df[('ANTECEDENTES Y ESTADO MANDATOS', 'Tipo Mandato')]
        df_out['banco'] = df[('ANTECEDENTES Y ESTADO MANDATOS', 'Banco/Institucion')]
        df_out['tipo_cuenta'] = df[('ANTECEDENTES Y ESTADO MANDATOS', 'Tipo Cuenta')]
        df_out['numero_cuenta'] = df[('ANTECEDENTES Y ESTADO MANDATOS', 'Numero Cuenta')]
        df_out['fecha_activacion'] = df[('ANTECEDENTES Y ESTADO MANDATOS', 'Fecha Activacón')].apply(
            self.normalizer.parse_date
        )
        df_out['estado'] = 'VIGENTE'
        df_out['fecha_import'] = datetime.now()

        # Limpiar NaNs
        df_out = df_out.dropna(subset=['numero_ficha', 'rut_socio'])

        logger.info(f"Transformadas {len(df_out)} suscripciones vigentes")

        return df_out

    def transform_cargos(self, df: pd.DataFrame, estado: str) -> pd.DataFrame:
        """Transformar CARGOS ACEPTADOS o RECHAZADOS para transacciones"""

        df_out = pd.DataFrame()

        df_out['numero_ficha'] = df[('Número Ficha',)]
        df_out['numero_mandato'] = df[('Número Mandato',)]
        df_out['periodo'] = pd.to_datetime(df[('DETALLE DEL PAGO', 'Periodo')]).dt.strftime('%Y-%m')
        df_out['numero_cuota'] = df[('N° Cuota',)]
        df_out['monto'] = df[('Monto',)].apply(self.normalizer.parse_currency)
        df_out['fecha_cargo'] = df[('Fecha Cargo',)].apply(self.normalizer.parse_date)
        df_out['tipo_transaccion'] = df[('Transacción',)]
        df_out['entidad_recaudadora'] = df[('Entidad Recaudadora',)]
        df_out['estado'] = 'ACEPTADA' if estado == 'aceptados' else 'RECHAZADA'
        df_out['codigo_respuesta'] = df[('Código Respuesta',)] if ('Código Respuesta',) in df.columns else None
        df_out['razon_rechazo'] = df[('Razón Rechazo',)] if ('Razón Rechazo',) in df.columns else None

        df_out = df_out.dropna(subset=['numero_ficha', 'numero_mandato', 'periodo'])

        logger.info(f"Transformadas {len(df_out)} transacciones ({estado})")

        return df_out

    def transform_bancos(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transformar tabla ENTIDADES a bancos"""

        df_out = pd.DataFrame()
        df_out['nombre'] = df[('NOMBRE',)].apply(lambda x: self.normalizer.normalize_string(x))
        df_out['codigo_interno'] = df[('COD INTERNO',)]
        df_out['codigo_grupo'] = df[('COD GRUPO',)]
        df_out['activo'] = True

        df_out = df_out.dropna(subset=['nombre'])

        return df_out

# ====== BASE DE DATOS ======

class DatabaseManager:
    """Gestiona la conexión y operaciones en BD"""

    def __init__(self, config: Dict):
        self.config = config
        self.connection = None
        self.cursor = None

    def connect(self):
        """Conectarse a la BD"""
        try:
            self.connection = mysql.connector.connect(**self.config)
            self.cursor = self.connection.cursor()
            logger.info("Conectado a la BD")
        except Error as e:
            logger.error(f"Error de conexión a BD: {e}")
            sys.exit(1)

    def disconnect(self):
        """Desconectarse de la BD"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
            logger.info("Desconectado de la BD")

    def get_banco_id(self, nombre_banco: str) -> Optional[int]:
        """Obtener ID de banco, o insertarlo si no existe"""

        # Buscar
        query = "SELECT id_banco FROM bancos WHERE nombre = %s"
        self.cursor.execute(query, (nombre_banco,))
        result = self.cursor.fetchone()

        if result:
            return result[0]

        # Insertar nuevo
        insert_query = "INSERT INTO bancos (nombre, codigo_interno, codigo_grupo, activo) VALUES (%s, %s, %s, %s)"
        self.cursor.execute(insert_query, (nombre_banco, None, 1, True))

        return self.cursor.lastrowid

    def get_cliente_id(self, rut: str, nombre: str, apellido: str) -> int:
        """Obtener ID de cliente, o insertarlo si no existe"""

        # Buscar por RUT
        query = "SELECT id_cliente FROM clientes WHERE rut = %s"
        self.cursor.execute(query, (rut,))
        result = self.cursor.fetchone()

        if result:
            return result[0]

        # Insertar nuevo
        insert_query = """
            INSERT INTO clientes (rut, nombre, apellido, tipo_persona, tipo_socio)
            VALUES (%s, %s, %s, %s, %s)
        """
        self.cursor.execute(insert_query, (rut, nombre, apellido, 'Natural', 'SOCIO'))

        return self.cursor.lastrowid

    def load_suscripciones(self, df: pd.DataFrame) -> Tuple[int, int, int]:
        """Cargar suscripciones (vigentes + eliminadas)"""

        inserted = 0
        updated = 0
        errors = 0

        for idx, row in df.iterrows():
            try:
                # Obtener/crear cliente
                cliente_id = self.get_cliente_id(row['rut_socio'], row['nombre_socio'], row['apellido_socio'])

                # Obtener/crear banco
                banco_id = self.get_banco_id(row['banco'])

                # Mapear tipo mandato
                tipo_mandato_map = {'PAC': 1, 'PAS': 2, 'DEC': 3}
                id_tipo_mandato = tipo_mandato_map.get(row['tipo_mandato'], 1)

                # Verificar si ya existe
                check_query = "SELECT id_suscripcion FROM suscripciones WHERE numero_ficha = %s"
                self.cursor.execute(check_query, (row['numero_ficha'],))
                existing = self.cursor.fetchone()

                if existing:
                    # UPDATE si ya existe
                    update_query = """
                        UPDATE suscripciones SET
                            estado = %s,
                            fecha_eliminacion = %s,
                            razon_baja = %s,
                            updated_at = NOW()
                        WHERE numero_ficha = %s
                    """
                    self.cursor.execute(update_query, (
                        row['estado'],
                        None if row['estado'] == 'VIGENTE' else datetime.now().date(),
                        None if row['estado'] == 'VIGENTE' else 'Actualización mensual',
                        row['numero_ficha']
                    ))
                    updated += 1
                else:
                    # INSERT nuevo
                    insert_query = """
                        INSERT INTO suscripciones (
                            numero_ficha, numero_mandato, id_cliente, id_tipo_mandato, id_banco,
                            tipo_cuenta, numero_cuenta, fecha_activacion, estado, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """
                    self.cursor.execute(insert_query, (
                        row['numero_ficha'],
                        row['numero_mandato'],
                        cliente_id,
                        id_tipo_mandato,
                        banco_id,
                        row['tipo_cuenta'],
                        row['numero_cuenta'],
                        row['fecha_activacion'],
                        row['estado']
                    ))
                    inserted += 1

            except Exception as e:
                logger.error(f"Error procesando fila {idx}: {e}")
                errors += 1

        logger.info(f"Suscripciones: {inserted} insertadas, {updated} actualizadas, {errors} errores")
        return inserted, updated, errors

    def load_transacciones(self, df: pd.DataFrame) -> Tuple[int, int]:
        """Cargar transacciones mensuales"""

        inserted = 0
        errors = 0

        for idx, row in df.iterrows():
            try:
                # Obtener ID de suscripción
                query = "SELECT id_suscripcion FROM suscripciones WHERE numero_ficha = %s"
                self.cursor.execute(query, (row['numero_ficha'],))
                result = self.cursor.fetchone()

                if not result:
                    logger.warning(f"No se encontró suscripción para ficha {row['numero_ficha']}")
                    continue

                id_suscripcion = result[0]

                # Verificar si ya existe
                check_query = """
                    SELECT id_transaccion FROM transacciones_mensuales
                    WHERE id_suscripcion = %s AND periodo = %s
                """
                self.cursor.execute(check_query, (id_suscripcion, row['periodo']))
                existing = self.cursor.fetchone()

                if not existing:
                    # INSERT
                    insert_query = """
                        INSERT INTO transacciones_mensuales (
                            id_suscripcion, periodo, numero_cuota, total_cuotas,
                            monto, fecha_cargo, tipo_transaccion, estado_consolidado, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """
                    self.cursor.execute(insert_query, (
                        id_suscripcion,
                        row['periodo'],
                        row['numero_cuota'],
                        row.get('total_cuotas'),
                        row['monto'],
                        row['fecha_cargo'],
                        row['tipo_transaccion'],
                        row['estado']
                    ))

                    # Insertar detalle
                    id_transaccion = self.cursor.lastrowid

                    detalle_query = """
                        INSERT INTO transacciones_detalles (
                            id_transaccion, estado_detalle, codigo_respuesta, razon_rechazo, created_at
                        ) VALUES (%s, %s, %s, %s, NOW())
                    """
                    self.cursor.execute(detalle_query, (
                        id_transaccion,
                        row['estado'],
                        row.get('codigo_respuesta'),
                        row.get('razon_rechazo')
                    ))

                    inserted += 1

            except Exception as e:
                logger.error(f"Error procesando transacción fila {idx}: {e}")
                errors += 1

        logger.info(f"Transacciones: {inserted} insertadas, {errors} errores")
        return inserted, errors

    def register_import(self, tipo_import: str, archivo: str, resultados: Dict):
        """Registrar el import en datos_auditoria"""

        insert_query = """
            INSERT INTO datos_auditoria (
                tipo_import, archivo_origen, registros_procesados, registros_insertados,
                registros_actualizados, registros_error, estado
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """

        self.cursor.execute(insert_query, (
            tipo_import,
            archivo,
            resultados.get('procesados', 0),
            resultados.get('insertados', 0),
            resultados.get('actualizados', 0),
            resultados.get('errores', 0),
            'EXITOSO' if resultados.get('errores', 0) == 0 else 'ERROR_PARCIAL'
        ))

        logger.info(f"Import registrado en auditoría")

# ====== ORQUESTACIÓN ======

class ETLOrchestrator:
    """Orquesta todo el proceso ETL"""

    def __init__(self, excel_path: str, mode: str = 'full'):
        self.excel_path = excel_path
        self.mode = mode
        self.reader = ExcelReader(excel_path)
        self.transformer = DataTransformer(DataNormalizer())
        self.db = DatabaseManager(DB_CONFIG)

    def run(self):
        """Ejecutar el ETL completo"""

        logger.info(f"Iniciando ETL en modo {self.mode}")
        logger.info(f"Archivo: {self.excel_path}")

        try:
            self.db.connect()

            # === LEER ===
            logger.info("--- FASE 1: EXTRACCIÓN ---")
            df_vigentes = self.reader.read_vigentes()
            df_cargos_aceptados = self.reader.read_cargos_aceptados()
            df_cargos_rechazados = self.reader.read_cargos_rechazados()
            df_tablas = self.reader.read_tablas()

            # === TRANSFORMAR ===
            logger.info("--- FASE 2: TRANSFORMACIÓN ---")
            df_suscripciones = self.transformer.transform_vigentes(df_vigentes)
            df_transacciones_aceptadas = self.transformer.transform_cargos(
                df_cargos_aceptados, 'aceptados'
            )
            df_transacciones_rechazadas = self.transformer.transform_cargos(
                df_cargos_rechazados, 'rechazados'
            )
            df_transacciones = pd.concat([
                df_transacciones_aceptadas,
                df_transacciones_rechazadas
            ], ignore_index=True)

            # === CARGAR ===
            logger.info("--- FASE 3: CARGA ---")

            resultados = {}

            # Cargar suscripciones
            ins_sus, upd_sus, err_sus = self.db.load_suscripciones(df_suscripciones)
            resultados['suscripciones_insertadas'] = ins_sus
            resultados['suscripciones_actualizadas'] = upd_sus

            # Cargar transacciones
            ins_trans, err_trans = self.db.load_transacciones(df_transacciones)
            resultados['transacciones_insertadas'] = ins_trans

            resultados['procesados'] = len(df_suscripciones) + len(df_transacciones)
            resultados['insertados'] = ins_sus + ins_trans
            resultados['actualizados'] = upd_sus
            resultados['errores'] = err_sus + err_trans

            # Registrar en auditoría
            self.db.register_import(
                'INCREMENTAL' if self.mode == 'incremental' else 'FULL_LOAD',
                self.reader.filepath.name,
                resultados
            )

            # Commit
            self.db.connection.commit()

            logger.info("--- RESUMEN ---")
            logger.info(f"Procesados: {resultados['procesados']}")
            logger.info(f"Insertados: {resultados['insertados']}")
            logger.info(f"Actualizados: {resultados['actualizados']}")
            logger.info(f"Errores: {resultados['errores']}")

            if resultados['errores'] == 0:
                logger.info("✅ ETL COMPLETADO EXITOSAMENTE")
            else:
                logger.warning("⚠️ ETL COMPLETADO CON ERRORES")

            return True

        except Exception as e:
            logger.error(f"❌ Error en ETL: {e}", exc_info=True)
            self.db.connection.rollback()
            return False

        finally:
            self.db.disconnect()

# ====== MAIN ======

def main():
    parser = argparse.ArgumentParser(description='ETL para reportes TCH')
    parser.add_argument('--file', required=True, help='Archivo Excel a procesar')
    parser.add_argument('--mode', choices=['full', 'incremental'], default='incremental',
                        help='Modo de carga')

    args = parser.parse_args()

    # Obtener archivo
    if args.file == 'latest':
        # Buscar el archivo más reciente
        files = sorted(EXCEL_DIR.glob('*.XLSX'), key=lambda x: x.stat().st_mtime, reverse=True)
        if not files:
            logger.error("No se encontraron archivos Excel")
            sys.exit(1)
        excel_file = str(files[0])
    else:
        excel_file = str(EXCEL_DIR / args.file)

    # Verificar que existe
    if not Path(excel_file).exists():
        logger.error(f"Archivo no encontrado: {excel_file}")
        sys.exit(1)

    # Ejecutar
    etl = ETLOrchestrator(excel_file, args.mode)
    success = etl.run()

    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
