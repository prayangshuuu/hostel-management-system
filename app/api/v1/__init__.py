"""API v1 router definitions."""

from fastapi import APIRouter

from app.api.v1.allocations import router as allocations_router
from app.api.v1.attendance import router as attendance_router
from app.api.v1.auth import router as auth_router
from app.api.v1.billing import router as billing_router
from app.api.v1.blocks import router as blocks_router
from app.api.v1.health import router as health_router
from app.api.v1.hostels import router as hostels_router
from app.api.v1.rooms import router as rooms_router
from app.api.v1.students import router as students_router
from app.api.v1.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(hostels_router)
api_router.include_router(blocks_router)
api_router.include_router(rooms_router)
api_router.include_router(students_router)
api_router.include_router(allocations_router)
api_router.include_router(billing_router)
api_router.include_router(attendance_router)

__all__ = ["api_router"]
