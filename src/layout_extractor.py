from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

import pymupdf

from .schemas import BoundingBox


class LayoutExtractionError(str, Enum):
    """Machine-readable reasons why deterministic layout extraction failed."""

    FILE_NOT_FOUND = "file_not_found"
    NOT_A_FILE = "not_a_file"
    INVALID_PDF = "invalid_pdf"
    ENCRYPTED_PDF = "encrypted_pdf"
    EXPECTED_SINGLE_PAGE = "expected_single_page"
    EXTRACTION_ERROR = "extraction_error"


@dataclass(frozen=True)
class LayoutWord:
    """One word and its position in PyMuPDF's text hierarchy."""

    text: str
    bbox: BoundingBox
    block_number: int
    line_number: int
    word_number: int


@dataclass(frozen=True)
class LayoutTextBlock:
    """A page text block preserved without semantic interpretation."""

    text: str
    bbox: BoundingBox
    block_number: int
    block_type: int


@dataclass(frozen=True)
class VectorCommand:
    """One native PDF drawing command with its coordinates preserved."""

    operator: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class VectorDrawing:
    """One vector path returned by PyMuPDF."""

    bbox: BoundingBox
    commands: tuple[VectorCommand, ...]
    stroke_color: tuple[float, ...] | None
    fill_color: tuple[float, ...] | None
    line_width: float | None
    close_path: bool


@dataclass(frozen=True)
class LayoutImage:
    """One displayed occurrence of a raster image."""

    xref: int
    bbox: BoundingBox


@dataclass(frozen=True)
class PageLayout:
    """Reusable deterministic layout data for one PDF page."""

    page_number: int
    width: float
    height: float
    rotation: int
    words: tuple[LayoutWord, ...] = field(default_factory=tuple)
    text_blocks: tuple[LayoutTextBlock, ...] = field(default_factory=tuple)
    vector_drawings: tuple[VectorDrawing, ...] = field(default_factory=tuple)
    images: tuple[LayoutImage, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LayoutExtractionResult:
    """Controlled result returned by :meth:`LayoutExtractor.extract`."""

    is_successful: bool
    source_file: str
    page: PageLayout | None = None
    error_code: LayoutExtractionError | None = None
    error_reason: str | None = None

    @classmethod
    def succeeded(
        cls, *, source_file: str, page: PageLayout
    ) -> LayoutExtractionResult:
        """Create a successful layout result."""
        return cls(is_successful=True, source_file=source_file, page=page)

    @classmethod
    def failed(
        cls,
        *,
        source_file: str,
        code: LayoutExtractionError,
        reason: str,
    ) -> LayoutExtractionResult:
        """Create a controlled failed layout result."""
        return cls(
            is_successful=False,
            source_file=source_file,
            error_code=code,
            error_reason=reason,
        )


class LayoutExtractor:
    """Extract reusable geometry from a validated single-page PDF."""

    def extract(self, pdf_path: str | Path) -> LayoutExtractionResult:
        """Open a PDF and deterministically collect its page-layout elements."""
        path = Path(pdf_path)
        source_file = path.name

        if not path.exists():
            return LayoutExtractionResult.failed(
                source_file=source_file,
                code=LayoutExtractionError.FILE_NOT_FOUND,
                reason=f"PDF file does not exist: {path}",
            )

        if not path.is_file():
            return LayoutExtractionResult.failed(
                source_file=source_file,
                code=LayoutExtractionError.NOT_A_FILE,
                reason=f"Path is not a regular file: {path}",
            )

        document: pymupdf.Document | None = None

        try:
            document = pymupdf.open(path)

            if not document.is_pdf:
                return LayoutExtractionResult.failed(
                    source_file=source_file,
                    code=LayoutExtractionError.INVALID_PDF,
                    reason="The supplied file is not a valid PDF document.",
                )

            if document.needs_pass:
                return LayoutExtractionResult.failed(
                    source_file=source_file,
                    code=LayoutExtractionError.ENCRYPTED_PDF,
                    reason="Password-protected PDFs are not supported.",
                )

            if document.page_count != 1:
                return LayoutExtractionResult.failed(
                    source_file=source_file,
                    code=LayoutExtractionError.EXPECTED_SINGLE_PAGE,
                    reason=(
                        "Layout extraction requires exactly one validated page; "
                        f"received {document.page_count}."
                    ),
                )

            page = document.load_page(0)
            layout = self._extract_page(page)
            return LayoutExtractionResult.succeeded(
                source_file=source_file,
                page=layout,
            )

        except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
            return LayoutExtractionResult.failed(
                source_file=source_file,
                code=LayoutExtractionError.INVALID_PDF,
                reason=f"PyMuPDF could not open the file as a valid PDF: {exc}",
            )
        except Exception as exc:
            return LayoutExtractionResult.failed(
                source_file=source_file,
                code=LayoutExtractionError.EXTRACTION_ERROR,
                reason=(
                    "An unexpected error occurred during layout extraction: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        finally:
            if document is not None:
                document.close()

    def _extract_page(self, page: pymupdf.Page) -> PageLayout:
        """Collect independent element groups from one page."""
        rect = page.rect
        return PageLayout(
            page_number=1,
            width=float(rect.width),
            height=float(rect.height),
            rotation=int(page.rotation),
            words=self._extract_words(page),
            text_blocks=self._extract_text_blocks(page),
            vector_drawings=self._extract_vector_drawings(page),
            images=self._extract_images(page),
        )

    @staticmethod
    def _extract_words(page: pymupdf.Page) -> tuple[LayoutWord, ...]:
        """Extract valid words and sort them top-to-bottom, then left-to-right."""
        words: list[LayoutWord] = []

        for raw_word in page.get_text("words", sort=False):
            try:
                if len(raw_word) < 8:
                    continue
                text = str(raw_word[4]).strip()
                if not text:
                    continue
                words.append(
                    LayoutWord(
                        text=text,
                        bbox=_bbox_from_values(raw_word[:4]),
                        block_number=int(raw_word[5]),
                        line_number=int(raw_word[6]),
                        word_number=int(raw_word[7]),
                    )
                )
            except (TypeError, ValueError, IndexError):
                continue

        words.sort(
            key=lambda word: (
                word.bbox.top,
                word.bbox.x0,
                word.block_number,
                word.line_number,
                word.word_number,
            )
        )
        return tuple(words)

    @staticmethod
    def _extract_text_blocks(page: pymupdf.Page) -> tuple[LayoutTextBlock, ...]:
        """Extract valid text blocks in a stable geometric reading order."""
        blocks: list[LayoutTextBlock] = []

        for raw_block in page.get_text("blocks", sort=False):
            try:
                if len(raw_block) < 7:
                    continue
                text = str(raw_block[4]).strip()
                block_type = int(raw_block[6])
                if not text or block_type != 0:
                    continue
                blocks.append(
                    LayoutTextBlock(
                        text=text,
                        bbox=_bbox_from_values(raw_block[:4]),
                        block_number=int(raw_block[5]),
                        block_type=block_type,
                    )
                )
            except (TypeError, ValueError, IndexError):
                continue

        blocks.sort(
            key=lambda block: (
                block.bbox.top,
                block.bbox.x0,
                block.block_number,
            )
        )
        return tuple(blocks)

    @staticmethod
    def _extract_vector_drawings(page: pymupdf.Page) -> tuple[VectorDrawing, ...]:
        """Extract vector paths while skipping malformed paths or commands."""
        drawings: list[VectorDrawing] = []

        for raw_drawing in page.get_drawings():
            try:
                commands = tuple(
                    command
                    for item in raw_drawing.get("items", ())
                    if (command := _vector_command(item)) is not None
                )
                drawing_rect = raw_drawing.get("rect")
                if drawing_rect is None or not commands:
                    continue
                drawings.append(
                    VectorDrawing(
                        bbox=_bbox_from_rect(drawing_rect),
                        commands=commands,
                        stroke_color=_color_tuple(raw_drawing.get("color")),
                        fill_color=_color_tuple(raw_drawing.get("fill")),
                        line_width=_optional_float(raw_drawing.get("width")),
                        close_path=bool(raw_drawing.get("closePath", False)),
                    )
                )
            except (TypeError, ValueError, KeyError, IndexError):
                continue

        drawings.sort(key=lambda drawing: (drawing.bbox.top, drawing.bbox.x0))
        return tuple(drawings)

    @staticmethod
    def _extract_images(page: pymupdf.Page) -> tuple[LayoutImage, ...]:
        """Extract each displayed raster-image rectangle."""
        images: list[LayoutImage] = []

        for image_info in page.get_images(full=True):
            try:
                xref = int(image_info[0])
                rectangles = page.get_image_rects(xref)
            except (TypeError, ValueError, IndexError):
                continue

            for rectangle in rectangles:
                try:
                    images.append(
                        LayoutImage(xref=xref, bbox=_bbox_from_rect(rectangle))
                    )
                except (TypeError, ValueError):
                    continue

        images.sort(key=lambda image: (image.bbox.top, image.bbox.x0, image.xref))
        return tuple(images)


def _bbox_from_values(values: Iterable[Any]) -> BoundingBox:
    """Create the shared bounding-box model from four coordinate values."""
    x0, top, x1, bottom = values
    coordinates = tuple(float(value) for value in (x0, top, x1, bottom))
    if not all(map(_is_finite, coordinates)):
        raise ValueError("Bounding-box coordinates must be finite.")
    return BoundingBox(
        x0=coordinates[0],
        top=coordinates[1],
        x1=coordinates[2],
        bottom=coordinates[3],
    )


def _bbox_from_rect(rectangle: Any) -> BoundingBox:
    """Create the shared bounding-box model from a PyMuPDF rectangle."""
    return _bbox_from_values(
        (rectangle.x0, rectangle.y0, rectangle.x1, rectangle.y1)
    )


def _vector_command(item: Any) -> VectorCommand | None:
    """Convert a supported PyMuPDF path item into a coordinate-only command."""
    if not isinstance(item, (tuple, list)) or not item:
        return None

    operator = str(item[0])
    points: list[tuple[float, float]] = []

    for value in item[1:]:
        if isinstance(value, pymupdf.Point):
            points.append((float(value.x), float(value.y)))
        elif isinstance(value, pymupdf.Rect):
            points.extend(
                (
                    (float(value.x0), float(value.y0)),
                    (float(value.x1), float(value.y1)),
                )
            )
        elif isinstance(value, pymupdf.Quad):
            points.extend((float(point.x), float(point.y)) for point in value)

    if not points or not all(_is_finite(coordinate) for point in points for coordinate in point):
        return None
    return VectorCommand(operator=operator, points=tuple(points))


def _color_tuple(value: Any) -> tuple[float, ...] | None:
    """Normalize an optional PyMuPDF color sequence."""
    if value is None:
        return None
    try:
        color = tuple(float(component) for component in value)
    except (TypeError, ValueError):
        return None
    return color if all(map(_is_finite, color)) else None


def _optional_float(value: Any) -> float | None:
    """Convert an optional numeric value without allowing non-finite output."""
    if value is None:
        return None
    number = float(value)
    return number if _is_finite(number) else None


def _is_finite(value: float) -> bool:
    """Return whether a number is neither infinite nor NaN."""
    return value == value and value not in (float("inf"), float("-inf"))
