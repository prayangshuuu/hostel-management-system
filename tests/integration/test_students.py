"""Integration tests for student management and self-service endpoints."""

from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_student_creation_and_auth_flow(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify student creation by admin/warden, password generation, and student login."""
    # 1. Student role cannot create student -> 403
    forbidden_resp = await client.post(
        "/api/v1/students",
        json={
            "email": "stu_create@example.com",
            "full_name": "New Student",
            "student_no": "STU-FORBID-01",
            "gender": "male",
            "department": "Civil",
            "year": 1,
            "guardian_name": "Guardian",
            "guardian_phone": "+1234567890",
            "emergency_contact": "+1987654321",
        },
        headers=student_headers,
    )
    assert forbidden_resp.status_code == 403

    # 2. Admin creates student with auto-generated temporary password -> 201
    admin_create_resp = await client.post(
        "/api/v1/students",
        json={
            "email": "auto_pw@example.com",
            "full_name": "Auto Password Student",
            "phone": "+1234567890",
            "student_no": "STU-AUTO-01",
            "gender": "female",
            "department": "Computer Science",
            "year": 2,
            "guardian_name": "Guardian Auto",
            "guardian_phone": "+1111111111",
            "emergency_contact": "+1222222222",
        },
        headers=admin_headers,
    )
    assert admin_create_resp.status_code == 201
    data1 = admin_create_resp.json()
    assert data1["email"] == "auto_pw@example.com"
    assert data1["full_name"] == "Auto Password Student"
    assert data1["student_no"] == "STU-AUTO-01"
    assert data1["temporary_password"] is not None
    assert len(data1["temporary_password"]) >= 8
    temp_pw = data1["temporary_password"]

    # Student can log in with generated temporary password
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "auto_pw@example.com", "password": temp_pw},
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()

    # 3. Warden creates student with explicit password -> 201, temporary_password is None
    warden_create_resp = await client.post(
        "/api/v1/students",
        json={
            "email": "custom_pw@example.com",
            "full_name": "Custom Password Student",
            "student_no": "STU-CUSTOM-02",
            "gender": "male",
            "department": "Electrical",
            "year": 3,
            "guardian_name": "Guardian Custom",
            "guardian_phone": "+1333333333",
            "emergency_contact": "+1444444444",
            "password": "CustomSecret123",
        },
        headers=warden_headers,
    )
    assert warden_create_resp.status_code == 201
    data2 = warden_create_resp.json()
    assert data2["temporary_password"] is None

    # Student logs in with custom password
    login_custom = await client.post(
        "/api/v1/auth/login",
        json={"email": "custom_pw@example.com", "password": "CustomSecret123"},
    )
    assert login_custom.status_code == 200


@pytest.mark.asyncio
async def test_student_creation_validation_and_conflicts(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Verify validation errors (phone regex, year, password policy) and conflict responses."""
    # Invalid phone regex
    bad_phone_resp = await client.post(
        "/api/v1/students",
        json={
            "email": "badphone@example.com",
            "full_name": "Bad Phone",
            "phone": "0123456789",  # Starts with 0
            "student_no": "STU-BADPHONE",
            "gender": "male",
            "department": "CS",
            "year": 1,
            "guardian_name": "G",
            "guardian_phone": "+1234567890",
            "emergency_contact": "+1987654321",
        },
        headers=admin_headers,
    )
    assert bad_phone_resp.status_code == 422

    # Year > 6 -> 422
    bad_year_resp = await client.post(
        "/api/v1/students",
        json={
            "email": "badyear@example.com",
            "full_name": "Bad Year",
            "student_no": "STU-BADYEAR",
            "gender": "male",
            "department": "CS",
            "year": 7,
            "guardian_name": "G",
            "guardian_phone": "+1234567890",
            "emergency_contact": "+1987654321",
        },
        headers=admin_headers,
    )
    assert bad_year_resp.status_code == 422

    # Weak password provided -> 422
    weak_pw_resp = await client.post(
        "/api/v1/students",
        json={
            "email": "weakpw@example.com",
            "full_name": "Weak PW",
            "student_no": "STU-WEAKPW",
            "gender": "male",
            "department": "CS",
            "year": 1,
            "guardian_name": "G",
            "guardian_phone": "+1234567890",
            "emergency_contact": "+1987654321",
            "password": "weak",
        },
        headers=admin_headers,
    )
    assert weak_pw_resp.status_code == 422

    # Create valid student
    valid_resp = await client.post(
        "/api/v1/students",
        json={
            "email": "unique_stu@example.com",
            "full_name": "Unique Student",
            "student_no": "STU-UNIQUE-99",
            "gender": "female",
            "department": "CS",
            "year": 2,
            "guardian_name": "G",
            "guardian_phone": "+1234567890",
            "emergency_contact": "+1987654321",
        },
        headers=admin_headers,
    )
    assert valid_resp.status_code == 201

    # Duplicate email -> 409 EMAIL_EXISTS
    dup_email_resp = await client.post(
        "/api/v1/students",
        json={
            "email": "unique_stu@example.com",
            "full_name": "Another Name",
            "student_no": "STU-ANOTHER",
            "gender": "female",
            "department": "CS",
            "year": 2,
            "guardian_name": "G",
            "guardian_phone": "+1234567890",
            "emergency_contact": "+1987654321",
        },
        headers=admin_headers,
    )
    assert dup_email_resp.status_code == 409
    assert dup_email_resp.json()["error"]["code"] == "EMAIL_EXISTS"

    # Duplicate student_no -> 409 STUDENT_NO_EXISTS
    dup_no_resp = await client.post(
        "/api/v1/students",
        json={
            "email": "different_email@example.com",
            "full_name": "Another Name",
            "student_no": "STU-UNIQUE-99",
            "gender": "male",
            "department": "CS",
            "year": 2,
            "guardian_name": "G",
            "guardian_phone": "+1234567890",
            "emergency_contact": "+1987654321",
        },
        headers=admin_headers,
    )
    assert dup_no_resp.status_code == 409
    assert dup_no_resp.json()["error"]["code"] == "STUDENT_NO_EXISTS"


@pytest.mark.asyncio
async def test_student_self_service_endpoints(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Verify GET/PATCH /api/v1/students/me and rejection of forbidden fields with 422."""
    # 1. Create a student
    create_resp = await client.post(
        "/api/v1/students",
        json={
            "email": "self_student@example.com",
            "full_name": "Self Service Student",
            "phone": "+1555555555",
            "student_no": "STU-SELF-01",
            "gender": "male",
            "department": "Information Tech",
            "year": 2,
            "guardian_name": "Self Guardian",
            "guardian_phone": "+1666666666",
            "emergency_contact": "+1777777777",
            "password": "Password123",
        },
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    student_id = create_resp.json()["id"]

    # 2. Log in as this student to obtain bearer token
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "self_student@example.com", "password": "Password123"},
    )
    token = login_resp.json()["access_token"]
    stu_headers = {"Authorization": f"Bearer {token}"}

    # 3. GET /api/v1/students/me
    me_resp = await client.get("/api/v1/students/me", headers=stu_headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["id"] == student_id
    assert me_data["email"] == "self_student@example.com"
    assert me_data["student_no"] == "STU-SELF-01"

    # 4. PATCH /api/v1/students/me with allowed contact fields
    patch_resp = await client.patch(
        "/api/v1/students/me",
        json={
            "phone": "+1999888777",
            "emergency_contact": "+1888777666",
            "guardian_phone": "+1777666555",
        },
        headers=stu_headers,
    )
    assert patch_resp.status_code == 200
    patch_data = patch_resp.json()
    assert patch_data["phone"] == "+1999888777"
    assert patch_data["emergency_contact"] == "+1888777666"
    assert patch_data["guardian_phone"] == "+1777666555"

    # 5. PATCH /api/v1/students/me with forbidden field -> 422!
    forbidden_field_resp = await client.patch(
        "/api/v1/students/me",
        json={
            "department": "Architecture",
        },
        headers=stu_headers,
    )
    assert forbidden_field_resp.status_code == 422

    forbidden_year_resp = await client.patch(
        "/api/v1/students/me",
        json={
            "year": 4,
        },
        headers=stu_headers,
    )
    assert forbidden_year_resp.status_code == 422

    # 6. Admin accessing /api/v1/students/me -> 403 (student role required)
    admin_me_resp = await client.get("/api/v1/students/me", headers=admin_headers)
    assert admin_me_resp.status_code == 403


@pytest.mark.asyncio
async def test_student_get_by_id_and_scoping(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/students/{id} access rules for admin, warden, self, and other student."""
    # Create two students
    r1 = await client.post(
        "/api/v1/students",
        json={
            "email": "student1@example.com",
            "full_name": "Student One",
            "student_no": "STU-ONE-01",
            "gender": "male",
            "department": "Math",
            "year": 1,
            "guardian_name": "G1",
            "guardian_phone": "+1000000001",
            "emergency_contact": "+1000000002",
            "password": "Password123",
        },
        headers=admin_headers,
    )
    id1 = r1.json()["id"]

    r2 = await client.post(
        "/api/v1/students",
        json={
            "email": "student2@example.com",
            "full_name": "Student Two",
            "student_no": "STU-TWO-02",
            "gender": "female",
            "department": "Physics",
            "year": 2,
            "guardian_name": "G2",
            "guardian_phone": "+2000000001",
            "emergency_contact": "+2000000002",
            "password": "Password123",
        },
        headers=admin_headers,
    )
    id2 = r2.json()["id"]

    # Student 1 logs in
    login1 = await client.post(
        "/api/v1/auth/login",
        json={"email": "student1@example.com", "password": "Password123"},
    )
    s1_headers = {"Authorization": f"Bearer {login1.json()['access_token']}"}

    # Student 1 gets own profile by ID -> 200
    s1_own = await client.get(f"/api/v1/students/{id1}", headers=s1_headers)
    assert s1_own.status_code == 200
    assert s1_own.json()["id"] == id1

    # Student 1 attempts to get Student 2 profile -> 403 FORBIDDEN
    s1_other = await client.get(f"/api/v1/students/{id2}", headers=s1_headers)
    assert s1_other.status_code == 403

    # Admin gets any student -> 200
    admin_get = await client.get(f"/api/v1/students/{id2}", headers=admin_headers)
    assert admin_get.status_code == 200
    assert admin_get.json()["id"] == id2

    # Warden gets any student -> 200
    warden_get = await client.get(f"/api/v1/students/{id1}", headers=warden_headers)
    assert warden_get.status_code == 200

    # Nonexistent ID for admin -> 404
    non_existent = str(uuid4())
    admin_404 = await client.get(f"/api/v1/students/{non_existent}", headers=admin_headers)
    assert admin_404.status_code == 404


@pytest.mark.asyncio
async def test_student_update_and_delete_lifecycle(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify PATCH and DELETE on /api/v1/students/{id} with user deactivation."""
    # 1. Create a student
    create_resp = await client.post(
        "/api/v1/students",
        json={
            "email": "lifecycle_stu@example.com",
            "full_name": "Lifecycle Student",
            "student_no": "STU-LIFE-01",
            "gender": "male",
            "department": "Civil",
            "year": 1,
            "guardian_name": "Initial Guardian",
            "guardian_phone": "+1000000001",
            "emergency_contact": "+1000000002",
            "password": "Password123",
        },
        headers=admin_headers,
    )
    student_id = create_resp.json()["id"]

    # 2. Student role cannot patch /api/v1/students/{id} -> 403
    forbidden_patch = await client.patch(
        f"/api/v1/students/{student_id}",
        json={"department": "Electronics"},
        headers=student_headers,
    )
    assert forbidden_patch.status_code == 403

    # 3. Warden patches student -> 200
    warden_patch = await client.patch(
        f"/api/v1/students/{student_id}",
        json={
            "department": "Electrical Engineering",
            "year": 2,
            "full_name": "Updated Lifecycle Student",
        },
        headers=warden_headers,
    )
    assert warden_patch.status_code == 200
    assert warden_patch.json()["department"] == "Electrical Engineering"
    assert warden_patch.json()["year"] == 2
    assert warden_patch.json()["full_name"] == "Updated Lifecycle Student"

    # 4. Student role cannot delete student -> 403
    forbidden_delete = await client.delete(
        f"/api/v1/students/{student_id}",
        headers=student_headers,
    )
    assert forbidden_delete.status_code == 403

    # 5. Admin soft-deletes student -> 204
    delete_resp = await client.delete(
        f"/api/v1/students/{student_id}",
        headers=admin_headers,
    )
    assert delete_resp.status_code == 204

    # 6. Profile is soft-deleted, so GET /api/v1/students/{id} returns 404
    get_after_delete = await client.get(
        f"/api/v1/students/{student_id}",
        headers=admin_headers,
    )
    assert get_after_delete.status_code == 404

    # Soft-deleted student is hidden from GET /api/v1/students list
    list_after_delete = await client.get(
        "/api/v1/students?search=STU-LIFE-01",
        headers=admin_headers,
    )
    assert list_after_delete.status_code == 200
    assert not any(s["id"] == student_id for s in list_after_delete.json()["items"])

    # 7. User account is deactivated, so student cannot log in
    login_after_delete = await client.post(
        "/api/v1/auth/login",
        json={"email": "lifecycle_stu@example.com", "password": "Password123"},
    )
    assert login_after_delete.status_code == 401


@pytest.mark.asyncio
async def test_student_list_pagination_and_filters(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/students pagination, filters, search, and student role rejection."""
    # Student role cannot list students -> 403
    forbidden_list = await client.get("/api/v1/students", headers=student_headers)
    assert forbidden_list.status_code == 403

    # Create students for filtering
    await client.post(
        "/api/v1/students",
        json={
            "email": "fil_stu1@example.com",
            "full_name": "Filtering Alpha",
            "student_no": "STU-FIL-01",
            "gender": "male",
            "department": "Computer Science",
            "year": 1,
            "guardian_name": "G1",
            "guardian_phone": "+1000000001",
            "emergency_contact": "+1000000002",
        },
        headers=admin_headers,
    )
    await client.post(
        "/api/v1/students",
        json={
            "email": "fil_stu2@example.com",
            "full_name": "Filtering Beta",
            "student_no": "STU-FIL-02",
            "gender": "female",
            "department": "Mechanical",
            "year": 3,
            "guardian_name": "G2",
            "guardian_phone": "+2000000001",
            "emergency_contact": "+2000000002",
        },
        headers=admin_headers,
    )

    # Admin list with department filter
    r_dept = await client.get("/api/v1/students?department=Computer Science", headers=admin_headers)
    assert r_dept.status_code == 200
    assert any(s["student_no"] == "STU-FIL-01" for s in r_dept.json()["items"])
    assert all(s["department"] == "Computer Science" for s in r_dept.json()["items"])

    # Admin list with year filter
    r_year = await client.get("/api/v1/students?year=3", headers=admin_headers)
    assert r_year.status_code == 200
    assert any(s["student_no"] == "STU-FIL-02" for s in r_year.json()["items"])

    # Admin list with gender filter
    r_gender = await client.get("/api/v1/students?gender=female", headers=admin_headers)
    assert r_gender.status_code == 200
    assert any(s["student_no"] == "STU-FIL-02" for s in r_gender.json()["items"])

    # Admin search by student_no
    r_search = await client.get("/api/v1/students?search=fil-01", headers=admin_headers)
    assert r_search.status_code == 200
    assert len(r_search.json()["items"]) == 1
    assert r_search.json()["items"][0]["student_no"] == "STU-FIL-01"

    # Warden can also list students
    warden_list = await client.get("/api/v1/students", headers=warden_headers)
    assert warden_list.status_code == 200
    assert "items" in warden_list.json()
