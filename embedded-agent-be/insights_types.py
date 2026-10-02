"""Bounded contracts for the optional assistant; legacy models stay unchanged."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Exchange(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=12000)


class SuppliedNumber(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float = Field(ge=0, le=1e10, allow_inf_nan=False)
    quote: str = Field(min_length=1, max_length=300)


class Scenario(BaseModel):
    kind: Literal["none", "emi", "principal"] = "none"
    principal: SuppliedNumber | None = None
    annual_rate_min: SuppliedNumber | None = None
    annual_rate_max: SuppliedNumber | None = None
    months: SuppliedNumber | None = None
    budget_min: SuppliedNumber | None = None
    budget_max: SuppliedNumber | None = None


class RouteDecision(BaseModel):
    route: Literal["direct", "insights"]
    scope: Literal["displayed", "history"]
    resolved_question: str = Field(min_length=1, max_length=2000)
    start_date: date | None = None
    end_date: date | None = None
    scenario: Scenario = Field(default_factory=Scenario)

    @model_validator(mode="after")
    def valid_scope(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Reversed date range")
        if self.route == "direct" and self.scope != "displayed":
            raise ValueError("Direct answers cannot expand the page boundary")
        return self


class InsightOutput(BaseModel):
    observations: list[str] = Field(default_factory=list, max_length=6)
    suggestions: list[str] = Field(default_factory=list, max_length=6)
    limitations: list[str] = Field(default_factory=list, max_length=5)
    follow_up: str = Field(default="", max_length=1500)
