from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_db, require_permissions
from app.models.core import DataCatalogMapping, QaScenario

router = APIRouter()


@router.get("/mappings", dependencies=[Depends(require_permissions("roles.manage"))], tags=["Data catalog"])
def list_mappings(db: Session = Depends(get_db)) -> list[dict]:  # noqa: B008
    mappings = db.scalars(select(DataCatalogMapping).order_by(DataCatalogMapping.source, DataCatalogMapping.core_entity)).all()
    return [
        {
            "id": str(mapping.id), "source": mapping.source, "source_resource": mapping.source_resource,
            "source_field": mapping.source_field, "staging_table": mapping.staging_table,
            "core_entity": mapping.core_entity, "core_field": mapping.core_field,
            "transformation": mapping.transformation, "verification_status": mapping.verification_status,
            "limitation": mapping.limitation,
        }
        for mapping in mappings
    ]


@router.get("/qa-scenarios", dependencies=[Depends(require_permissions("roles.manage"))], tags=["Data catalog"])
def list_qa_scenarios(db: Session = Depends(get_db)) -> list[dict]:  # noqa: B008
    scenarios = db.scalars(select(QaScenario).order_by(QaScenario.source, QaScenario.code)).all()
    return [
        {
            "id": str(scenario.id), "code": scenario.code, "source": scenario.source,
            "description": scenario.description, "expected_result": scenario.expected_result,
            "coverage_status": scenario.coverage_status,
        }
        for scenario in scenarios
    ]
