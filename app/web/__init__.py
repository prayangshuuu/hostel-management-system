"""Web portal router aggregating authentication, admin, and student portals."""

from fastapi import APIRouter

from app.web.admin.allocations import router as admin_allocations_router
from app.web.admin.billing import router as admin_billing_router
from app.web.admin.rooms import router as admin_rooms_router
from app.web.admin.students import router as admin_students_router
from app.web.auth import router as auth_router

web_router = APIRouter()

web_router.include_router(auth_router)
web_router.include_router(admin_students_router)
web_router.include_router(admin_allocations_router)
web_router.include_router(admin_billing_router)
web_router.include_router(admin_rooms_router)
