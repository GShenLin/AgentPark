"""Validated schedule contracts; all stored deadlines are UTC timestamps."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AtSchedule(Contract):
    kind: Literal["at"]
    at: str

    @field_validator("at")
    @classmethod
    def validate_at(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("at must include a timezone offset")
        return parsed.astimezone(timezone.utc).isoformat()


class EverySchedule(Contract):
    kind: Literal["every"]
    seconds: int = Field(ge=60, le=31536000)


class CronSchedule(Contract):
    kind: Literal["cron"]
    expression: str
    timezone: str

    @field_validator("expression")
    @classmethod
    def validate_expression(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value.split()) != 5 or not croniter.is_valid(value):
            raise ValueError("expression must be a valid five-field cron expression")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value


Schedule = Annotated[AtSchedule | EverySchedule | CronSchedule, Field(discriminator="kind")]
schedule_adapter = TypeAdapter(Schedule)


def next_deadline(schedule: Schedule, now: float, previous: float | None = None) -> float | None:
    if isinstance(schedule, AtSchedule):
        return datetime.fromisoformat(schedule.at).timestamp() if previous is None else None
    if isinstance(schedule, EverySchedule):
        if previous is None:
            return now + schedule.seconds
        return previous + (int((now - previous) // schedule.seconds) + 1) * schedule.seconds
    base = datetime.fromtimestamp(now, ZoneInfo(schedule.timezone))
    return croniter(schedule.expression, base, max_years_between_matches=8).get_next(datetime).timestamp()


class CreateJob(Contract):
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    prompt: str = Field(min_length=1, max_length=32000, pattern=r"\S")
    schedule: Schedule


class UpdateJob(Contract):
    job_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"\S")
    prompt: str | None = Field(default=None, min_length=1, max_length=32000, pattern=r"\S")
    schedule: Schedule | None = None
    enabled: bool | None = None


class DeleteJob(Contract):
    job_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
