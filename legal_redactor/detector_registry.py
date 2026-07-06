"""Pluggable detector registry for candidate discovery.

Defines a Detector protocol and thin adapters so the existing ``detect_*``
functions can be treated uniformly, and a future judgment layer (HanLP / LLM)
can register an additional detector without rewriting LinearRuleEngine's
collection loop.

This module only provides the extension point and a default registry of the
existing rule-based detectors. LinearRuleEngine.collect_candidates still
drives discovery itself — the registry is not yet wired into the engine's
hot path (that migration is intentionally incremental and gated by parity
tests). The value today is a stable, tested place to add new detectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from .models import Candidate


@runtime_checkable
class Detector(Protocol):
    """A named candidate discoverer applied to a text segment."""

    name: str

    def discover(self, text: str) -> list[Candidate]:
        ...


@dataclass
class FunctionDetector:
    """Adapter for detect_* functions returning ``list[Candidate]``."""

    name: str
    discover_fn: Callable[[str], list[Candidate]]

    def discover(self, text: str) -> list[Candidate]:
        return self.discover_fn(text)


@dataclass
class PartyLineDetector:
    """Adapter for detect_party_candidates, which returns
    ``(candidates, party_lines)``; only the candidates flow into the registry.
    Mirrors LinearRuleEngine.collect_candidates, which also discards the
    party_lines tuple element.
    """

    name: str
    discover_fn: Callable[[str], tuple[list[Candidate], list]]

    def discover(self, text: str) -> list[Candidate]:
        candidates, _party_lines = self.discover_fn(text)
        return candidates


@dataclass
class DetectorRegistry:
    """Ordered registry of detectors; discover_all concatenates results."""

    detectors: list[Detector] = field(default_factory=list)

    def register(self, detector: Detector) -> None:
        self.detectors.append(detector)

    def discover_all(self, text: str) -> list[Candidate]:
        candidates: list[Candidate] = []
        for detector in self.detectors:
            candidates.extend(detector.discover(text))
        return candidates


def build_default_registry() -> DetectorRegistry:
    """Registry of the existing rule-based detectors used by the linear path.

    Order follows LinearRuleEngine.collect_candidates' direct text-level
    discovery order (title, inline party list, fallback people, china admin,
    party). Per-segment and conditionally-gated detectors (semantic rules,
    hanlp gating, llm discovery) remain owned by the engine and are not
    registered here.
    """
    from .china_admin_rules import detect_china_admin_rule_candidates
    from .detectors import (
        detect_fallback_person_candidates,
        detect_inline_party_person_list_candidates,
        detect_party_candidates,
        detect_title_candidates,
    )

    registry = DetectorRegistry()
    registry.register(FunctionDetector("title", detect_title_candidates))
    registry.register(
        FunctionDetector("inline_party_person_list", detect_inline_party_person_list_candidates)
    )
    registry.register(
        FunctionDetector("fallback_person", detect_fallback_person_candidates)
    )
    registry.register(
        FunctionDetector("china_admin_rule", detect_china_admin_rule_candidates)
    )
    registry.register(
        PartyLineDetector("party", detect_party_candidates)
    )
    return registry