"""Limit/offset pagination shared by every list endpoint."""
from __future__ import annotations

from typing import TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class PageParams(BaseModel):
    limit: int
    offset: int


def page_params(limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0)) -> PageParams:
    return PageParams(limit=limit, offset=offset)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
