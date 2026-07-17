from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from .layout_extractor import LayoutExtractionResult, LayoutWord, PageLayout
from .schemas import (
    BoundingBox,
    Citation,
    ExtractedField,
    ExtractionStatus,
    TitleBlock,
)


@dataclass(frozen=True)
class TitleBlockExtractorConfig:
    """Geometry limits for deterministic title-block matching."""

    region_top_ratio: float = 0.62
    same_line_tolerance: float = 4.0
    maximum_vertical_gap_ratio: float = 0.10
    maximum_inline_gap_ratio: float = 0.12

    def __post_init__(self) -> None:
        if not 0.0 <= self.region_top_ratio < 1.0:
            raise ValueError("region_top_ratio must be between 0.0 and 1.0.")
        if self.same_line_tolerance < 0:
            raise ValueError("same_line_tolerance cannot be negative.")
        if not 0.0 < self.maximum_vertical_gap_ratio <= 1.0:
            raise ValueError("maximum_vertical_gap_ratio must be in (0.0, 1.0].")
        if not 0.0 < self.maximum_inline_gap_ratio <= 1.0:
            raise ValueError("maximum_inline_gap_ratio must be in (0.0, 1.0].")


@dataclass(frozen=True)
class _LabelSpec:
    field_name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class _LabelMatch:
    field_name: str
    words: tuple[LayoutWord, ...]
    bbox: BoundingBox


@dataclass(frozen=True)
class _Candidate:
    words: tuple[LayoutWord, ...]
    score: tuple[float, float, float]


_FIELD_SPECS = (
    _LabelSpec("drawing_number", ("DRAWING NUMBER", "DRAWING NO", "DWG NO")),
    _LabelSpec("drawing_title", ("DRAWING TITLE", "TITLE")),
    _LabelSpec("revision", ("REVISION", "REV")),
    _LabelSpec("material", ("MATERIAL",)),
    _LabelSpec("scale", ("SCALE",)),
    _LabelSpec("drawn_by", ("DRAWN BY", "DRAWN")),
    _LabelSpec("checked_by", ("CHECKED BY", "CHECKED")),
    _LabelSpec("approved_by", ("APPROVED BY", "APPROVED")),
    _LabelSpec("drawing_date", ("DRAWING DATE", "DATE")),
)

# These labels are not schema fields, but they delimit cells in common title blocks.
_BOUNDARY_ALIASES = (
    "FINISH",
    "SHEET",
    "SHEET NO",
    "UNIT",
    "UNITS",
    "PROJECTION",
    "TOLERANCE",
)

_DATE_PATTERN = re.compile(r"^(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}-\d{2}-\d{2})$")
_DRAWING_NUMBER_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}(?:[-/][A-Z0-9]{1,12})+$")
_SCALE_PATTERN = re.compile(r"^\d+(?:\.\d+)?:\d+(?:\.\d+)?$")


class TitleBlockExtractor:
    """Extract schema-defined title-block fields from deterministic page layout."""

    def __init__(self, config: TitleBlockExtractorConfig | None = None) -> None:
        self.config = config or TitleBlockExtractorConfig()

    def extract(
        self,
        layout: PageLayout | LayoutExtractionResult,
    ) -> TitleBlock:
        """Return a title block from layout data, never by reopening the PDF."""
        page = self._resolve_page(layout)
        if page is None or page.width <= 0 or page.height <= 0:
            return _missing_title_block()

        words = self._title_block_words(page)
        if not words:
            return _missing_title_block()

        label_matches = self._find_labels(words)
        occupied_word_ids = {
            id(word)
            for label in label_matches
            for word in label.words
        }

        extracted: dict[str, ExtractedField] = {}
        for spec in _FIELD_SPECS:
            matches = [
                match for match in label_matches if match.field_name == spec.field_name
            ]
            extracted[spec.field_name] = self._extract_labeled_value(
                field_name=spec.field_name,
                matches=matches,
                all_labels=label_matches,
                words=words,
                occupied_word_ids=occupied_word_ids,
                page=page,
            )

        self._apply_conservative_fallbacks(extracted, words, label_matches, page)

        return TitleBlock(
            drawing_number=extracted["drawing_number"],
            drawing_title=extracted["drawing_title"],
            revision=extracted["revision"],
            material=extracted["material"],
            scale=extracted["scale"],
            drawn_by=extracted["drawn_by"],
            checked_by=extracted["checked_by"],
            approved_by=extracted["approved_by"],
            drawing_date=extracted["drawing_date"],
        )

    @staticmethod
    def _resolve_page(
        layout: PageLayout | LayoutExtractionResult,
    ) -> PageLayout | None:
        """Unwrap only successful layout results."""
        if isinstance(layout, PageLayout):
            return layout
        if layout.is_successful:
            return layout.page
        return None

    def _title_block_words(self, page: PageLayout) -> tuple[LayoutWord, ...]:
        """Keep valid words in the configured lower-page search region."""
        region_top = page.height * self.config.region_top_ratio
        valid_words: list[LayoutWord] = []

        for word in page.words:
            try:
                bbox = word.bbox
                if (
                    word.text.strip()
                    and bbox.bottom >= region_top
                    and 0 <= bbox.x0 < bbox.x1 <= page.width
                    and 0 <= bbox.top < bbox.bottom <= page.height
                ):
                    valid_words.append(word)
            except (AttributeError, TypeError, ValueError):
                continue

        return tuple(
            sorted(
                valid_words,
                key=lambda word: (
                    word.bbox.top,
                    word.bbox.x0,
                    word.block_number,
                    word.line_number,
                    word.word_number,
                ),
            )
        )

    def _find_labels(self, words: Sequence[LayoutWord]) -> tuple[_LabelMatch, ...]:
        """Find exact normalized label sequences and cell-boundary labels."""
        lines = _group_by_source_line(words)
        matches: list[_LabelMatch] = []
        aliases = [
            (spec.field_name, alias)
            for spec in _FIELD_SPECS
            for alias in spec.aliases
        ]
        aliases.extend(("", alias) for alias in _BOUNDARY_ALIASES)
        aliases.sort(key=lambda item: len(_label_tokens(item[1])), reverse=True)

        for line_words in lines:
            tokens = [_normalize_token(word.text) for word in line_words]
            claimed_indexes: set[int] = set()

            for field_name, alias in aliases:
                alias_tokens = _label_tokens(alias)
                token_count = len(alias_tokens)
                for start in range(len(tokens) - token_count + 1):
                    indexes = set(range(start, start + token_count))
                    if indexes & claimed_indexes:
                        continue
                    if tuple(tokens[start : start + token_count]) != alias_tokens:
                        continue
                    matched_words = tuple(line_words[start : start + token_count])
                    matches.append(
                        _LabelMatch(
                            field_name=field_name,
                            words=matched_words,
                            bbox=_combined_bbox(matched_words),
                        )
                    )
                    claimed_indexes.update(indexes)

        return tuple(sorted(matches, key=lambda match: (match.bbox.top, match.bbox.x0)))

    def _extract_labeled_value(
        self,
        *,
        field_name: str,
        matches: Sequence[_LabelMatch],
        all_labels: Sequence[_LabelMatch],
        words: Sequence[LayoutWord],
        occupied_word_ids: set[int],
        page: PageLayout,
    ) -> ExtractedField:
        """Resolve one unambiguous nearby value for a recognized label."""
        resolved: list[tuple[str, BoundingBox, tuple[float, float, float]]] = []

        for label in matches:
            candidate = self._best_candidate(
                field_name=field_name,
                label=label,
                all_labels=all_labels,
                words=words,
                occupied_word_ids=occupied_word_ids,
                page=page,
            )
            if candidate is None:
                continue
            value = _join_words(candidate.words)
            if _valid_value(field_name, value):
                resolved.append((value, _combined_bbox(candidate.words), candidate.score))

        if not resolved:
            return _missing_field()

        resolved.sort(key=lambda item: item[2])
        best = resolved[0]
        if len(resolved) > 1 and resolved[1][0] != best[0] and resolved[1][2] == best[2]:
            return _missing_field()

        return _matched_field(best[0], best[1], page.page_number)

    def _best_candidate(
        self,
        *,
        field_name: str,
        label: _LabelMatch,
        all_labels: Sequence[_LabelMatch],
        words: Sequence[LayoutWord],
        occupied_word_ids: set[int],
        page: PageLayout,
    ) -> _Candidate | None:
        """Choose the closest aligned text line inside the label's likely cell."""
        right_edge = _next_label_x(label, all_labels, page.width, self.config.same_line_tolerance)
        lower_edge = _next_label_y(label, all_labels, page.height)
        maximum_bottom = min(
            lower_edge,
            label.bbox.bottom + page.height * self.config.maximum_vertical_gap_ratio,
        )
        maximum_inline_x = min(
            right_edge,
            label.bbox.x1 + page.width * self.config.maximum_inline_gap_ratio,
        )
        usable = [word for word in words if id(word) not in occupied_word_ids]
        candidates: list[_Candidate] = []

        inline = [
            word
            for word in usable
            if label.bbox.x1 <= word.bbox.x0 <= maximum_inline_x
            and _vertical_overlap(label.bbox, word.bbox, self.config.same_line_tolerance)
        ]
        for group in _group_geometric_lines(inline, self.config.same_line_tolerance):
            candidates.append(
                _Candidate(
                    words=group,
                    score=(0.0, group[0].bbox.x0 - label.bbox.x1, group[0].bbox.x0),
                )
            )

        below = [
            word
            for word in usable
            if label.bbox.x0 <= _horizontal_center(word.bbox) < right_edge
            and label.bbox.bottom < word.bbox.top <= maximum_bottom
        ]
        for group in _group_geometric_lines(below, self.config.same_line_tolerance):
            group_bbox = _combined_bbox(group)
            candidates.append(
                _Candidate(
                    words=group,
                    score=(
                        1.0,
                        group_bbox.top - label.bbox.bottom,
                        abs(_horizontal_center(group_bbox) - _horizontal_center(label.bbox)),
                    ),
                )
            )

        candidates = [
            candidate
            for candidate in candidates
            if _valid_value(field_name, _join_words(candidate.words))
        ]
        return min(candidates, key=lambda candidate: candidate.score, default=None)

    def _apply_conservative_fallbacks(
        self,
        extracted: dict[str, ExtractedField],
        words: Sequence[LayoutWord],
        labels: Sequence[_LabelMatch],
        page: PageLayout,
    ) -> None:
        """Fill only uniquely matching drawing number, scale, and date values."""
        occupied_ids = {id(word) for label in labels for word in label.words}
        available = [word for word in words if id(word) not in occupied_ids]
        patterns = {
            "drawing_number": _DRAWING_NUMBER_PATTERN,
            "scale": _SCALE_PATTERN,
            "drawing_date": _DATE_PATTERN,
        }

        for field_name, pattern in patterns.items():
            if extracted[field_name].status is not ExtractionStatus.MISSING:
                continue
            matches = [word for word in available if pattern.fullmatch(word.text.strip().upper())]
            if field_name == "drawing_date":
                matches = self._dates_in_drawn_by_cell(matches, labels, page)
            if len(matches) == 1:
                extracted[field_name] = _fallback_field(
                    matches[0].text.strip(), matches[0].bbox, page.page_number
                )

    def _dates_in_drawn_by_cell(
        self,
        dates: Sequence[LayoutWord],
        labels: Sequence[_LabelMatch],
        page: PageLayout,
    ) -> list[LayoutWord]:
        """Prefer a unique date below the DRAWN BY label when DATE is absent."""
        drawn_labels = [label for label in labels if label.field_name == "drawn_by"]
        if not drawn_labels:
            return list(dates)
        label = drawn_labels[0]
        right_edge = _next_label_x(label, labels, page.width, self.config.same_line_tolerance)
        return [
            word
            for word in dates
            if label.bbox.x0 <= _horizontal_center(word.bbox) < right_edge
            and word.bbox.top > label.bbox.bottom
        ]


def _missing_title_block() -> TitleBlock:
    """Create a complete title block whose fields are explicitly missing."""
    return TitleBlock(
        drawing_number=_missing_field(),
        drawing_title=_missing_field(),
        revision=_missing_field(),
        material=_missing_field(),
        scale=_missing_field(),
        drawn_by=_missing_field(),
        checked_by=_missing_field(),
        approved_by=_missing_field(),
        drawing_date=_missing_field(),
    )


def _missing_field() -> ExtractedField:
    return ExtractedField(value=None, status=ExtractionStatus.MISSING, citation=None)


def _matched_field(value: str, bbox: BoundingBox, page_number: int) -> ExtractedField:
    return ExtractedField(
        value=value,
        status=ExtractionStatus.MATCHED,
        citation=Citation(page=page_number, bbox=bbox),
    )


def _fallback_field(value: str, bbox: BoundingBox, page_number: int) -> ExtractedField:
    return ExtractedField(
        value=value,
        status=ExtractionStatus.FALLBACK_MATCHED,
        citation=Citation(page=page_number, bbox=bbox),
    )


def _group_by_source_line(words: Sequence[LayoutWord]) -> tuple[tuple[LayoutWord, ...], ...]:
    grouped: dict[tuple[int, int], list[LayoutWord]] = {}
    for word in words:
        grouped.setdefault((word.block_number, word.line_number), []).append(word)
    lines = [tuple(sorted(line, key=lambda word: word.bbox.x0)) for line in grouped.values()]
    return tuple(sorted(lines, key=lambda line: (line[0].bbox.top, line[0].bbox.x0)))


def _group_geometric_lines(
    words: Sequence[LayoutWord], tolerance: float
) -> tuple[tuple[LayoutWord, ...], ...]:
    lines: list[list[LayoutWord]] = []
    for word in sorted(words, key=lambda item: (item.bbox.top, item.bbox.x0)):
        matching_line = next(
            (line for line in lines if abs(line[0].bbox.top - word.bbox.top) <= tolerance),
            None,
        )
        if matching_line is None:
            lines.append([word])
        else:
            matching_line.append(word)
    return tuple(tuple(sorted(line, key=lambda item: item.bbox.x0)) for line in lines)


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


def _next_label_x(
    label: _LabelMatch,
    labels: Sequence[_LabelMatch],
    page_width: float,
    tolerance: float,
) -> float:
    candidates = [
        other.bbox.x0
        for other in labels
        if other.bbox.x0 > label.bbox.x0
        and abs(other.bbox.top - label.bbox.top) <= tolerance * 2
    ]
    return min(candidates, default=page_width)


def _next_label_y(
    label: _LabelMatch, labels: Sequence[_LabelMatch], page_height: float
) -> float:
    candidates = [
        other.bbox.top
        for other in labels
        if other.bbox.top > label.bbox.bottom
        and other.bbox.x0 <= label.bbox.x0 <= other.bbox.x1
    ]
    return min(candidates, default=page_height)


def _horizontal_center(bbox: BoundingBox) -> float:
    return (bbox.x0 + bbox.x1) / 2.0


def _vertical_overlap(left: BoundingBox, right: BoundingBox, tolerance: float) -> bool:
    return right.top <= left.bottom + tolerance and right.bottom >= left.top - tolerance


def _valid_value(field_name: str, value: str) -> bool:
    normalized = value.strip()
    if not normalized or len(normalized) > 160:
        return False
    if field_name == "drawing_number":
        return bool(re.search(r"[A-Z0-9]", normalized.upper()))
    if field_name == "revision":
        return len(normalized) <= 20
    if field_name == "scale":
        return bool(_SCALE_PATTERN.fullmatch(normalized.replace(" ", "")))
    if field_name == "drawing_date":
        return bool(_DATE_PATTERN.fullmatch(normalized.replace(" ", "")))
    return bool(re.search(r"[A-Z0-9]", normalized.upper()))
