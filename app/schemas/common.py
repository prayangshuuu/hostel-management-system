"""Common reusable schemas and parameters."""

import math

from fastapi import Query
from pydantic import BaseModel
from pydantic.fields import FieldInfo


class PaginationParams:
    """Pagination query parameters dependency."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number (1-indexed)"),
        size: int = Query(20, ge=1, le=100, description="Items per page"),
    ) -> None:
        self.page = 1 if isinstance(page, FieldInfo) else page
        self.size = 20 if isinstance(size, FieldInfo) else size

    @property
    def offset(self) -> int:
        """Offset for SQL queries."""
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        """Limit for SQL queries."""
        return self.size


class Page[T](BaseModel):
    """Generic pagination response wrapper."""

    items: list[T]
    total: int
    page: int
    size: int
    pages: int

    @classmethod
    def create(
        cls,
        items: list[T],
        total: int,
        params: PaginationParams,
    ) -> "Page[T]":
        """Factory method to construct a Page instance with computed total pages."""
        pages = math.ceil(total / params.size) if params.size > 0 else 0
        return cls(
            items=items,
            total=total,
            page=params.page,
            size=params.size,
            pages=pages,
        )
