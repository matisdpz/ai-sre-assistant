from typing import Literal

from pydantic import BaseModel


class LiveResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, Literal["ok", "error"]]
