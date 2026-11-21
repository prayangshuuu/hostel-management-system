"""Unit tests for common schemas and pagination."""

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.schemas.common import Page, PaginationParams


def test_pagination_params_defaults() -> None:
    """Verify default pagination parameter values."""
    params = PaginationParams()
    assert params.page == 1
    assert params.size == 20
    assert params.offset == 0
    assert params.limit == 20


def test_pagination_params_custom() -> None:
    """Verify custom pagination parameter values and offset/limit calculation."""
    params = PaginationParams(page=3, size=15)
    assert params.page == 3
    assert params.size == 15
    assert params.offset == 30
    assert params.limit == 15


def test_page_schema_calculation() -> None:
    """Verify total pages calculation in Page.create."""
    params = PaginationParams(page=1, size=10)

    # Empty
    page_zero: Page[str] = Page.create(items=[], total=0, params=params)
    assert page_zero.pages == 0
    assert page_zero.items == []
    assert page_zero.total == 0

    # Exact division
    page_exact = Page.create(items=["a", "b"], total=20, params=params)
    assert page_exact.pages == 2

    # Division with remainder
    page_remainder = Page.create(items=["a"], total=21, params=params)
    assert page_remainder.pages == 3


@pytest.mark.asyncio
async def test_pagination_fastapi_dependency_validation() -> None:
    """Verify FastAPI query validation constraints for PaginationParams."""
    app = FastAPI()

    @app.get("/test-pagination")
    async def get_paginated(
        params: Annotated[PaginationParams, Depends(PaginationParams)],
    ) -> dict[str, int]:
        return {
            "page": params.page,
            "size": params.size,
            "offset": params.offset,
            "limit": params.limit,
        }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Valid custom params
        resp = await ac.get("/test-pagination?page=2&size=50")
        assert resp.status_code == 200
        assert resp.json() == {"page": 2, "size": 50, "offset": 50, "limit": 50}

        # Page < 1 validation error
        resp = await ac.get("/test-pagination?page=0")
        assert resp.status_code == 422

        # Size < 1 validation error
        resp = await ac.get("/test-pagination?size=0")
        assert resp.status_code == 422

        # Size > 100 validation error
        resp = await ac.get("/test-pagination?size=101")
        assert resp.status_code == 422
