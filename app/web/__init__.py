"""Web portal router aggregating authentication, admin, and student portals."""

from fastapi import APIRouter

from app.web.admin.allocations import router as admin_allocations_router
from app.web.admin.attendance import router as admin_attendance_router
from app.web.admin.audit import router as admin_audit_router
from app.web.admin.billing import router as admin_billing_router
from app.web.admin.complaints import router as admin_complaints_router
from app.web.admin.leaves import router as admin_leaves_router
from app.web.admin.mess import router as admin_mess_router
from app.web.admin.notices import router as admin_notices_router
from app.web.admin.reports import router as admin_reports_router
from app.web.admin.rooms import router as admin_rooms_router
from app.web.admin.students import router as admin_students_router
from app.web.admin.visitors import router as admin_visitors_router
from app.web.auth import router as auth_router

web_router = APIRouter()

web_router.include_router(auth_router)
web_router.include_router(admin_students_router)
web_router.include_router(admin_allocations_router)
web_router.include_router(admin_billing_router)
web_router.include_router(admin_rooms_router)
web_router.include_router(admin_attendance_router)
web_router.include_router(admin_leaves_router)
web_router.include_router(admin_visitors_router)
web_router.include_router(admin_complaints_router)
web_router.include_router(admin_mess_router)
web_router.include_router(admin_notices_router)
web_router.include_router(admin_audit_router)
web_router.include_router(admin_reports_router)
