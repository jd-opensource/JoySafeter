from fastapi import APIRouter, Depends, Response

from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.schemas.joysafeter_llm import LlmCatalogResponse
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, get_joysafeter_auth_context

router = APIRouter(tags=["joysafeter-llm"])


@router.get("/catalog", response_model=LlmCatalogResponse)
async def get_catalog(
    response: Response,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> LlmCatalogResponse:
    catalog = get_llm_catalog()
    response.headers["ETag"] = f'"{catalog.version}"'
    response.headers["Cache-Control"] = "private, max-age=300"
    return LlmCatalogResponse.model_validate(catalog.model_dump())
