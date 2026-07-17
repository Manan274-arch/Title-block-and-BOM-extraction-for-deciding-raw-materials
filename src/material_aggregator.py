from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Sequence

from .schemas import (
    BOMRow,
    ExtractedField,
    ExtractionStatus,
    RawMaterialItem,
    TitleBlock,
)


@dataclass(frozen=True)
class MaterialAggregatorConfig:
    """Deterministic material normalization rules."""

    aliases: tuple[tuple[str, str], ...] = (
        ("M S", "MILD STEEL"),
        ("MS", "MILD STEEL"),
    )
    bom_reference_values: tuple[str, ...] = (
        "AS PER BOM",
        "PER BOM",
        "SEE BOM",
    )
    ignored_values: tuple[str, ...] = (
        "-",
        "N A",
        "NA",
        "NONE",
        "NOT APPLICABLE",
    )

    def __post_init__(self) -> None:
        normalized_aliases = [_normalize_material(source) for source, _ in self.aliases]
        if len(normalized_aliases) != len(set(normalized_aliases)):
            raise ValueError("Material aliases must have unique normalized keys.")
        if any(not target.strip() for _, target in self.aliases):
            raise ValueError("Material alias targets cannot be blank.")


@dataclass
class _MaterialGroup:
    material: str
    quantities: list[float | None]
    source_rows: list[int]


class MaterialAggregator:
    """Build a deterministic raw-material summary from validated extraction data."""

    def __init__(self, config: MaterialAggregatorConfig | None = None) -> None:
        self.config = config or MaterialAggregatorConfig()
        self._aliases = {
            _normalize_material(source): _normalize_material(target)
            for source, target in self.config.aliases
        }
        self._bom_references = {
            _normalize_material(value) for value in self.config.bom_reference_values
        }
        self._ignored_values = {
            _normalize_material(value) for value in self.config.ignored_values
        }

    def aggregate(
        self,
        bom: Sequence[BOMRow],
        title_block: TitleBlock | None = None,
    ) -> list[RawMaterialItem]:
        """Aggregate BOM materials, falling back to a concrete title material."""
        if bom:
            return self._aggregate_bom(bom)

        title_material = self._usable_material(
            title_block.material if title_block is not None else None
        )
        if title_material is None:
            return []
        return [
            RawMaterialItem(
                material=title_material,
                quantity=None,
                source_bom_rows=[],
            )
        ]

    def _aggregate_bom(self, bom: Sequence[BOMRow]) -> list[RawMaterialItem]:
        """Group usable BOM material cells while retaining source row positions."""
        groups: dict[str, _MaterialGroup] = {}

        for row_number, row in enumerate(bom, start=1):
            material = self._usable_material(row.material)
            if material is None:
                continue

            group = groups.setdefault(
                material,
                _MaterialGroup(material=material, quantities=[], source_rows=[]),
            )
            group.quantities.append(_parse_quantity(row.quantity))
            group.source_rows.append(row_number)

        return [
            RawMaterialItem(
                material=group.material,
                quantity=_complete_total(group.quantities),
                source_bom_rows=group.source_rows,
            )
            for group in sorted(groups.values(), key=lambda item: item.material)
        ]

    def _usable_material(self, field: ExtractedField | None) -> str | None:
        """Return a canonical material only from a successfully extracted field."""
        if field is None or field.status not in {
            ExtractionStatus.MATCHED,
            ExtractionStatus.FALLBACK_MATCHED,
        }:
            return None
        if field.value is None:
            return None

        material = _normalize_material(field.value)
        material = self._aliases.get(material, material)
        if (
            not material
            or material in self._bom_references
            or material in self._ignored_values
        ):
            return None
        return material


def _normalize_material(value: str) -> str:
    """Normalize case, punctuation, and whitespace without inferring a material."""
    normalized = value.strip().upper()
    normalized = re.sub(r"[._]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _parse_quantity(field: ExtractedField) -> float | None:
    """Parse one finite, non-negative quantity from a matched BOM cell."""
    if field.status not in {
        ExtractionStatus.MATCHED,
        ExtractionStatus.FALLBACK_MATCHED,
    }:
        return None
    if field.value is None:
        return None

    text = field.value.strip().replace(",", "")
    if not re.fullmatch(r"(?:\d+(?:\.\d+)?|\.\d+)", text):
        return None

    quantity = float(text)
    if not math.isfinite(quantity) or quantity < 0:
        return None
    return quantity


def _complete_total(quantities: Sequence[float | None]) -> float | None:
    """Return a total only when every contributing quantity is known."""
    if not quantities or any(quantity is None for quantity in quantities):
        return None
    return sum(quantity for quantity in quantities if quantity is not None)
