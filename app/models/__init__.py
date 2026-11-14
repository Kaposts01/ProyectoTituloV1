

def load_all_models() -> None:
    """Importa todos los modulos de `app.models` para que el metadata resuelva cualquier ForeignKey.

    Los scripts sueltos (no la app) solo importan los modelos que usan; sin esto el flush falla con
    NoReferencedTableError en FKs como `uploaded_by_user_id` o `etl_run_id`.
    """
    import importlib
    import pkgutil

    for module in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{module.name}")


# Cualquier `import app.models.<x>` registra todos los modelos: los scripts sueltos y los servicios importados fuera de
# la app (sin app.main) resuelven asi todas las ForeignKey del metadata.
load_all_models()
