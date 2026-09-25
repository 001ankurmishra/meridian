from fastapi import APIRouter

from meridian.api.cases import router as cases_router

api_router = APIRouter()
api_router.include_router(cases_router, prefix="/cases", tags=["cases"])
