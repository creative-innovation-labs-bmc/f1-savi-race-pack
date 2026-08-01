from __future__ import annotations

import re
from dataclasses import dataclass


ROUND_HEADER_RE = re.compile(r"^(?P<race>.+?)\s*-\s*Race\s*(?P<round>\d+)\s*$", re.IGNORECASE)


IDENTITY_HEADER = "Team | Manager"


class RacePackError(RuntimeError):
    """Raised when an input or output fails a hard validation rule."""


@dataclass(frozen=True)
class Competitor:
    team: str
    manager: str
    values: tuple[int, ...]

    @property
    def identity(self) -> str:
        return f"{self.team} | {self.manager}"

    @property
    def key(self) -> tuple[str, str]:
        return (self.team.casefold(), self.manager.casefold())


@dataclass(frozen=True)
class Dataset:
    headers: tuple[str, ...]
    competitors: tuple[Competitor, ...]
    source: str

    @property
    def race_headers(self) -> tuple[str, ...]:
        return self.headers[1:]


@dataclass(frozen=True)
class RankedEntry:
    rank: int
    team: str
    manager: str
    points: int


@dataclass(frozen=True)
class MovementEntry:
    team: str
    manager: str
    previous_rank: int
    current_rank: int
    movement: int
    points: int


@dataclass(frozen=True)
class PodiumTallyEntry:
    team: str
    manager: str
    first: int
    first_change: int
    second: int
    second_change: int
    third: int
    third_change: int
    total: int
    total_change: int


@dataclass(frozen=True)
class AdjustmentEntry:
    race: str
    round: int
    team: str
    manager: str
    race_points: int
    cumulative_delta: int
    adjustment: int


@dataclass(frozen=True)
class RoundMetadata:
    header: str
    race: str
    round: int


@dataclass
class ValidationReport:
    errors: list[str]
    warnings: list[str]
    checks: dict[str, object]

    @property
    def status(self) -> str:
        return "pass" if not self.errors else "fail"

    def require_pass(self) -> None:
        if self.errors:
            raise RacePackError("; ".join(self.errors))
