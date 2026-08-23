"""外部副作用を持たないadapter契約。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..model import Observation


@dataclass(frozen=True, slots=True)
class ScanContext:
    root: Path
    subject: str


class Adapter(Protocol):
    adapter_id: str
    adapter_version: str

    def observe(self, context: ScanContext) -> Observation: ...
