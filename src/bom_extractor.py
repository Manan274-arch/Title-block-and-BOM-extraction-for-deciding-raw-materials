from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from .layout_extractor import (
    LayoutExtractionResult,
    LayoutWord,
    PageLayout,
    VectorDrawing,
)
from .schemas import BOMRow, BoundingBox, Citation, ExtractedField, ExtractionStatus


@dataclass(frozen=True)
class BOMExtractorConfig:
    """Geometry limits for deterministic BOM table extraction."""

    header_tolerance: float = 5.0
    row_tolerance: float = 4.0
    maximum_table_height_ratio: float = 0.55
    column_margin_ratio: float = 0.02

    def __post_init__(self) -> None:
        if self.header_tolerance < 0 or self.row_tolerance < 0:
            raise ValueError("BOM tolerances cannot be negative.")
        if not 0.0 < self.maximum_table_height_ratio <= 1.0:
            raise ValueError("maximum_table_height_ratio must be in (0.0, 1.0].")
        if not 0.0 <= self.column_margin_ratio <= 0.25:
            raise ValueError("column_margin_ratio must be between 0.0 and 0.25.")


@dataclass(frozen=True)
class _HeaderSpec:
    field_name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class _HeaderMatch:
    field_name: str
    words: tuple[LayoutWord, ...]
    bbox: BoundingBox


@dataclass(frozen=True)
class _Column:
    field_name: str
    left: float
    right: float


_HEADER_SPECS = (
    _HeaderSpec("item_number", ("ITEM NUMBER", "ITEM NO", "ITEM")),
    _HeaderSpec("part_number", ("PART NUMBER", "PART NO")),
    _HeaderSpec(
        "description",
        ("PART DESCRIPTION", "PART NAME", "DESCRIPTION"),
    ),
    _HeaderSpec("quantity", ("QUANTITY", "QTY")),
    _HeaderSpec("material", ("MATERIAL",)),
)
_BOUNDARY_HEADERS = ("REMARKS", "REMARK", "NOTES")
_ITEM_PATTERN = re.compile(r"^\d+[A-Z]?(?:[-.][A-Z0-9]+)?$", re.IGNORECASE)
_QUANTITY_PATTERN = re.compile(r"^\d+(?:\.\d+)?$")


class BOMExtractor:
    """Extract schema-defined BOM rows from deterministic page layout."""

    def __init__(self, config: BOMExtractorConfig | None = None) -> None:
        self.config = config or BOMExtractorConfig()

    def extract(
        self,
        layout: PageLayout | LayoutExtractionResult,
    ) -> list[BOMRow]:
        """Return deterministic BOM rows without reopening or parsing the PDF."""
        page = self._resolve_page(layout)
        if page is None or page.width <= 0 or page.height <= 0:
            return []

        words = _valid_words(page)
        header = self._find_header(words)
        if not header:
            return []

        columns = self._build_columns(header, page.width)
        if "item_number" not in columns:
            return []

        header_bottom = max(match.bbox.bottom for match in header)
        table_left = min(column.left for column in columns.values())
        table_right = max(column.right for column in columns.values())
        maximum_bottom = min(
            page.height,
            header_bottom + page.height * self.config.maximum_table_height_ratio,
        )
        table_bottom = self._table_bottom_from_vectors(
            drawings=page.vector_drawings,
            left=table_left,
            right=table_right,
            header_bottom=header_bottom,
            maximum_bottom=maximum_bottom,
        )

        header_word_ids = {id(word) for match in header for word in match.words}
        table_words = [
            word
            for word in words
            if id(word) not in header_word_ids
            and word.bbox.top > header_bottom
            and word.bbox.bottom <= table_bottom
            and table_left <= _center_x(word.bbox) < table_right
        ]

        rows: list[tuple[float, BOMRow]] = []
        for line in _group_geometric_lines(table_words, self.config.row_tolerance):
            cells = self._assign_cells(line, columns)
            item_words = cells.get("item_number", ())
            item_value = _join_words(item_words).replace(" ", "")
            if not _ITEM_PATTERN.fullmatch(item_value):
                continue

            quantity_words = cells.get("quantity", ())
            quantity_value = _join_words(quantity_words).replace(" ", "")
            if quantity_words and not _QUANTITY_PATTERN.fullmatch(quantity_value):
                continue

            rows.append(
                (
                    min(word.bbox.top for word in line),
                    self._build_row(cells, page.page_number),
                )
            )

        rows.sort(key=lambda item: (item[0], _item_sort_key(item[1])))
        return [row for _, row in rows]

    @staticmethod
    def _resolve_page(
        layout: PageLayout | LayoutExtractionResult,
    ) -> PageLayout | None:
        """Unwrap only successful layout extraction results."""
        if isinstance(layout, PageLayout):
            return layout
        if layout.is_successful:
            return layout.page
        return None

    def _find_header(
        self,
        words: Sequence[LayoutWord],
    ) -> tuple[_HeaderMatch, ...]:
        """Find the strongest aligned cluster of normalized BOM header labels."""
        matches: list[_HeaderMatch] = []
        aliases = [
            (spec.field_name, alias)
            for spec in _HEADER_SPECS
            for alias in spec.aliases
        ]
        aliases.extend(("", alias) for alias in _BOUNDARY_HEADERS)
        aliases.sort(key=lambda item: len(_label_tokens(item[1])), reverse=True)

        for line in _group_by_source_line(words):
            tokens = [_normalize_token(word.text) for word in line]
            claimed: set[int] = set()
            for field_name, alias in aliases:
                alias_tokens = _label_tokens(alias)
                length = len(alias_tokens)
                for start in range(len(tokens) - length + 1):
                    indexes = set(range(start, start + length))
                    if indexes & claimed:
                        continue
                    if tuple(tokens[start : start + length]) != alias_tokens:
                        continue
                    label_words = tuple(line[start : start + length])
                    matches.append(
                        _HeaderMatch(
                            field_name=field_name,
                            words=label_words,
                            bbox=_combined_bbox(label_words),
                        )
                    )
                    claimed.update(indexes)

        clusters: list[list[_HeaderMatch]] = []
        for match in sorted(matches, key=lambda item: (item.bbox.top, item.bbox.x0)):
            cluster = next(
                (
                    current
                    for current in clusters
                    if abs(current[0].bbox.top - match.bbox.top)
                    <= self.config.header_tolerance
                ),
                None,
            )
            if cluster is None:
                clusters.append([match])
            else:
                cluster.append(match)

        valid_clusters = [cluster for cluster in clusters if _is_bom_header(cluster)]
        if not valid_clusters:
            return ()
        best = max(
            valid_clusters,
            key=lambda cluster: (
                len({match.field_name for match in cluster if match.field_name}),
                -min(match.bbox.top for match in cluster),
            ),
        )
        return tuple(sorted(best, key=lambda match: match.bbox.x0))

    def _build_columns(
        self,
        header: Sequence[_HeaderMatch],
        page_width: float,
    ) -> dict[str, _Column]:
        """Derive deterministic column boundaries from ordered header centers."""
        ordered = sorted(header, key=lambda match: _center_x(match.bbox))
        centers = [_center_x(match.bbox) for match in ordered]
        margin = page_width * self.config.column_margin_ratio
        columns: dict[str, _Column] = {}

        for index, match in enumerate(ordered):
            left = (
                (centers[index - 1] + centers[index]) / 2.0
                if index > 0
                else max(0.0, match.bbox.x0 - margin)
            )
            right = (
                (centers[index] + centers[index + 1]) / 2.0
                if index + 1 < len(ordered)
                else min(page_width, match.bbox.x1 + margin)
            )
            if match.field_name:
                columns[match.field_name] = _Column(match.field_name, left, right)

        return columns

    @staticmethod
    def _table_bottom_from_vectors(
        *,
        drawings: Sequence[VectorDrawing],
        left: float,
        right: float,
        header_bottom: float,
        maximum_bottom: float,
    ) -> float:
        """Use broad horizontal table rules to tighten the table's lower edge."""
        table_width = right - left
        horizontal_rules: list[float] = []

        for drawing in drawings:
            for command in drawing.commands:
                if len(command.points) < 2:
                    continue
                for start, end in zip(command.points, command.points[1:]):
                    if abs(start[1] - end[1]) > 1.0:
                        continue
                    overlap = max(
                        0.0,
                        min(max(start[0], end[0]), right)
                        - max(min(start[0], end[0]), left),
                    )
                    y_coordinate = (start[1] + end[1]) / 2.0
                    if (
                        overlap >= table_width * 0.60
                        and header_bottom < y_coordinate <= maximum_bottom
                    ):
                        horizontal_rules.append(y_coordinate)

        return max(horizontal_rules, default=maximum_bottom)

    @staticmethod
    def _assign_cells(
        words: Sequence[LayoutWord],
        columns: dict[str, _Column],
    ) -> dict[str, tuple[LayoutWord, ...]]:
        """Assign row words to header-derived columns by horizontal center."""
        assigned: dict[str, list[LayoutWord]] = {name: [] for name in columns}
        for word in words:
            center = _center_x(word.bbox)
            matching = [
                column
                for column in columns.values()
                if column.left <= center < column.right
            ]
            if len(matching) == 1:
                assigned[matching[0].field_name].append(word)
        return {
            name: tuple(sorted(cell_words, key=lambda word: word.bbox.x0))
            for name, cell_words in assigned.items()
        }

    @staticmethod
    def _build_row(
        cells: dict[str, tuple[LayoutWord, ...]],
        page_number: int,
    ) -> BOMRow:
        """Construct one canonical row with explicit missing cells."""
        return BOMRow(
            item_number=_field_from_words(cells.get("item_number", ()), page_number),
            part_number=_field_from_words(cells.get("part_number", ()), page_number),
            description=_field_from_words(cells.get("description", ()), page_number),
            material=_field_from_words(cells.get("material", ()), page_number),
            quantity=_field_from_words(cells.get("quantity", ()), page_number),
        )


def _valid_words(page: PageLayout) -> tuple[LayoutWord, ...]:
    """Return finite, on-page words in stable reading order."""
    words: list[LayoutWord] = []
    for word in page.words:
        try:
            bbox = word.bbox
            if (
                word.text.strip()
                and 0 <= bbox.x0 < bbox.x1 <= page.width
                and 0 <= bbox.top < bbox.bottom <= page.height
            ):
                words.append(word)
        except (AttributeError, TypeError, ValueError):
            continue
    return tuple(
        sorted(
            words,
            key=lambda word: (
                word.bbox.top,
                word.bbox.x0,
                word.block_number,
                word.line_number,
                word.word_number,
            ),
        )
    )


def _is_bom_header(cluster: Sequence[_HeaderMatch]) -> bool:
    fields = {match.field_name for match in cluster if match.field_name}
    descriptive = bool(fields & {"description", "part_number", "material"})
    return "item_number" in fields and "quantity" in fields and descriptive


def _field_from_words(
    words: Sequence[LayoutWord],
    page_number: int,
) -> ExtractedField:
    if not words:
        return ExtractedField(
            value=None,
            status=ExtractionStatus.MISSING,
            citation=None,
        )
    return ExtractedField(
        value=_join_words(words),
        status=ExtractionStatus.MATCHED,
        citation=Citation(page=page_number, bbox=_combined_bbox(words)),
    )


def _group_by_source_line(
    words: Sequence[LayoutWord],
) -> tuple[tuple[LayoutWord, ...], ...]:
    grouped: dict[tuple[int, int], list[LayoutWord]] = {}
    for word in words:
        grouped.setdefault((word.block_number, word.line_number), []).append(word)
    lines = [tuple(sorted(line, key=lambda word: word.bbox.x0)) for line in grouped.values()]
    return tuple(sorted(lines, key=lambda line: (line[0].bbox.top, line[0].bbox.x0)))


def _group_geometric_lines(
    words: Sequence[LayoutWord],
    tolerance: float,
) -> tuple[tuple[LayoutWord, ...], ...]:
    lines: list[list[LayoutWord]] = []
    for word in sorted(words, key=lambda item: (item.bbox.top, item.bbox.x0)):
        line = next(
            (current for current in lines if abs(current[0].bbox.top - word.bbox.top) <= tolerance),
            None,
        )
        if line is None:
            lines.append([word])
        else:
            line.append(word)
    return tuple(tuple(sorted(line, key=lambda word: word.bbox.x0)) for line in lines)


def _normalize_token(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", text.upper())


def _label_tokens(label: str) -> tuple[str, ...]:
    return tuple(_normalize_token(token) for token in label.split())


def _join_words(words: Iterable[LayoutWord]) -> str:
    return " ".join(word.text.strip() for word in words if word.text.strip()).strip()


def _combined_bbox(words: Sequence[LayoutWord]) -> BoundingBox:
    return BoundingBox(
        x0=min(word.bbox.x0 for word in words),
        top=min(word.bbox.top for word in words),
        x1=max(word.bbox.x1 for word in words),
        bottom=max(word.bbox.bottom for word in words),
    )


def _center_x(bbox: BoundingBox) -> float:
    return (bbox.x0 + bbox.x1) / 2.0


def _item_sort_key(row: BOMRow) -> tuple[int, str]:
    value = row.item_number.value or ""
    match = re.match(r"^(\d+)", value)
    return (int(match.group(1)) if match else 2**31 - 1, value)
