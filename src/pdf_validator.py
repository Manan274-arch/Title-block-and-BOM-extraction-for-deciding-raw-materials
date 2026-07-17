from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import pymupdf


class PdfRejectionCode(str, Enum):
    """
    Machine-readable reasons why a PDF cannot enter the extraction pipeline.

    These codes are internal to the validation stage. Later, pipeline.py can
    translate them into DrawingResult.rejection_reason.
    """

    FILE_NOT_FOUND = "file_not_found"
    NOT_A_FILE = "not_a_file"
    INVALID_PDF = "invalid_pdf"
    ENCRYPTED_PDF = "encrypted_pdf"
    EMPTY_PDF = "empty_pdf"
    MULTI_PAGE_PDF = "multi_page_pdf"
    EMPTY_PAGE = "empty_page"
    NO_EXTRACTABLE_TEXT = "no_extractable_text"
    LIKELY_SCANNED_PDF = "likely_scanned_pdf"
    VALIDATION_ERROR = "validation_error"


@dataclass(frozen=True)
class PdfValidatorConfig:
    """
    Configuration for deciding whether a PDF is digital-native.

    PDF coordinates are measured in points:
        72 points = 1 inch

    text_density is measured as:
        non-whitespace characters / page area in square inches

    image_coverage_ratio is measured as:
        total image rectangle area / page area
    """

    maximum_pages: int = 1

    # A drawing below this density is considered text-sparse.
    minimum_text_density: float = 2.0

    # If a text-sparse page has image coverage above this threshold,
    # it is likely to be a scanned drawing.
    maximum_image_coverage_ratio: float = 0.80

    # Reject a page when PyMuPDF extracts no meaningful characters.
    minimum_text_characters: int = 1

    def __post_init__(self) -> None:
        if self.maximum_pages < 1:
            raise ValueError("maximum_pages must be at least 1.")

        if self.minimum_text_density < 0:
            raise ValueError("minimum_text_density cannot be negative.")

        if not 0.0 <= self.maximum_image_coverage_ratio <= 1.0:
            raise ValueError(
                "maximum_image_coverage_ratio must be between 0.0 and 1.0."
            )

        if self.minimum_text_characters < 0:
            raise ValueError("minimum_text_characters cannot be negative.")


@dataclass(frozen=True)
class PageValidationMetrics:
    """
    Measurements collected from one PDF page.

    These values are useful for:
    - debugging
    - threshold calibration
    - evaluation tests
    - understanding why a document was rejected
    """

    page_number: int
    width_points: float
    height_points: float
    area_square_inches: float
    extracted_text_characters: int
    text_density: float
    image_count: int
    image_coverage_ratio: float


@dataclass(frozen=True)
class PdfValidationResult:
    """
    Result returned by PdfValidator.validate().

    The validator does not raise exceptions for ordinary invalid inputs.
    Instead, it returns an explicit rejection code and explanation.
    """

    is_valid: bool
    source_file: str
    rejection_code: PdfRejectionCode | None = None
    rejection_reason: str | None = None
    page_count: int | None = None
    pages: list[PageValidationMetrics] = field(default_factory=list)

    @classmethod
    def accepted(
        cls,
        *,
        source_file: str,
        page_count: int,
        pages: list[PageValidationMetrics],
    ) -> PdfValidationResult:
        return cls(
            is_valid=True,
            source_file=source_file,
            rejection_code=None,
            rejection_reason=None,
            page_count=page_count,
            pages=pages,
        )

    @classmethod
    def rejected(
        cls,
        *,
        source_file: str,
        code: PdfRejectionCode,
        reason: str,
        page_count: int | None = None,
        pages: list[PageValidationMetrics] | None = None,
    ) -> PdfValidationResult:
        return cls(
            is_valid=False,
            source_file=source_file,
            rejection_code=code,
            rejection_reason=reason,
            page_count=page_count,
            pages=pages or [],
        )


class PdfValidator:
    """
    Validates whether a PDF is suitable for deterministic layout extraction.

    Responsibilities:
    - verify that the file exists
    - verify that PyMuPDF can open it
    - reject encrypted documents
    - reject empty or multi-page documents
    - measure text density
    - measure image dominance
    - reject likely scanned PDFs

    Non-responsibilities:
    - OCR
    - title-block extraction
    - BOM extraction
    - semantic interpretation
    """

    def __init__(self, config: PdfValidatorConfig | None = None) -> None:
        self.config = config or PdfValidatorConfig()

    def validate(self, pdf_path: str | Path) -> PdfValidationResult:
        """
        Validate a PDF and return an explicit validation result.

        Expected validation failures are represented in PdfValidationResult.
        Unexpected implementation or library failures are also converted into
        controlled rejection results so the pipeline does not crash.
        """

        path = Path(pdf_path)
        source_file = path.name

        if not path.exists():
            return PdfValidationResult.rejected(
                source_file=source_file,
                code=PdfRejectionCode.FILE_NOT_FOUND,
                reason=f"PDF file does not exist: {path}",
            )

        if not path.is_file():
            return PdfValidationResult.rejected(
                source_file=source_file,
                code=PdfRejectionCode.NOT_A_FILE,
                reason=f"Path is not a regular file: {path}",
            )

        document: pymupdf.Document | None = None

        try:
            document = pymupdf.open(path)

            if not document.is_pdf:
                return PdfValidationResult.rejected(
                    source_file=source_file,
                    code=PdfRejectionCode.INVALID_PDF,
                    reason="The supplied file is not a valid PDF document.",
                )

            if document.needs_pass:
                return PdfValidationResult.rejected(
                    source_file=source_file,
                    code=PdfRejectionCode.ENCRYPTED_PDF,
                    reason="Password-protected PDFs are not supported.",
                    page_count=document.page_count,
                )

            page_count = document.page_count

            if page_count == 0:
                return PdfValidationResult.rejected(
                    source_file=source_file,
                    code=PdfRejectionCode.EMPTY_PDF,
                    reason="The PDF contains no pages.",
                    page_count=0,
                )

            if page_count > self.config.maximum_pages:
                return PdfValidationResult.rejected(
                    source_file=source_file,
                    code=PdfRejectionCode.MULTI_PAGE_PDF,
                    reason=(
                        f"The PDF contains {page_count} pages. "
                        f"Only PDFs with at most "
                        f"{self.config.maximum_pages} page are supported."
                    ),
                    page_count=page_count,
                )

            page_metrics: list[PageValidationMetrics] = []

            for page_index in range(page_count):
                page = document.load_page(page_index)
                metrics = self._measure_page(page, page_index)
                page_metrics.append(metrics)

                page_rejection = self._evaluate_page(metrics)

                if page_rejection is not None:
                    code, reason = page_rejection

                    return PdfValidationResult.rejected(
                        source_file=source_file,
                        code=code,
                        reason=reason,
                        page_count=page_count,
                        pages=page_metrics,
                    )

            return PdfValidationResult.accepted(
                source_file=source_file,
                page_count=page_count,
                pages=page_metrics,
            )

        except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
            return PdfValidationResult.rejected(
                source_file=source_file,
                code=PdfRejectionCode.INVALID_PDF,
                reason=f"PyMuPDF could not open the file as a valid PDF: {exc}",
            )

        except Exception as exc:
            return PdfValidationResult.rejected(
                source_file=source_file,
                code=PdfRejectionCode.VALIDATION_ERROR,
                reason=(
                    "An unexpected error occurred during PDF validation: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        finally:
            if document is not None:
                document.close()

    def _measure_page(
        self,
        page: pymupdf.Page,
        page_index: int,
    ) -> PageValidationMetrics:
        """
        Collect objective measurements from one page.

        This method only measures the page. It does not decide whether the page
        is valid. Keeping measurement and decision logic separate makes testing
        and future threshold tuning easier.
        """

        page_rect = page.rect
        width_points = float(page_rect.width)
        height_points = float(page_rect.height)
        page_area_points = width_points * height_points

        if page_area_points <= 0:
            return PageValidationMetrics(
                page_number=page_index + 1,
                width_points=width_points,
                height_points=height_points,
                area_square_inches=0.0,
                extracted_text_characters=0,
                text_density=0.0,
                image_count=0,
                image_coverage_ratio=0.0,
            )

        page_area_square_inches = page_area_points / (72.0 * 72.0)

        text = page.get_text("text")
        non_whitespace_character_count = sum(
            1 for character in text if not character.isspace()
        )

        if page_area_square_inches > 0:
            text_density = (
                non_whitespace_character_count / page_area_square_inches
            )
        else:
            text_density = 0.0

        image_count, image_coverage_ratio = self._measure_image_coverage(
            page=page,
            page_area_points=page_area_points,
        )

        return PageValidationMetrics(
            page_number=page_index + 1,
            width_points=round(width_points, 4),
            height_points=round(height_points, 4),
            area_square_inches=round(page_area_square_inches, 4),
            extracted_text_characters=non_whitespace_character_count,
            text_density=round(text_density, 4),
            image_count=image_count,
            image_coverage_ratio=round(image_coverage_ratio, 4),
        )

    @staticmethod
    def _measure_image_coverage(
        *,
        page: pymupdf.Page,
        page_area_points: float,
    ) -> tuple[int, float]:
        """
        Estimate how much of the page is occupied by raster images.

        One image object can appear multiple times on a page, so we inspect its
        displayed rectangles rather than only its underlying pixel dimensions.
        """

        if page_area_points <= 0:
            return 0, 0.0

        image_rectangles: list[pymupdf.Rect] = []

        for image_info in page.get_images(full=True):
            xref = image_info[0]

            try:
                rectangles = page.get_image_rects(xref)
            except ValueError:
                # A malformed or unusual image reference should not cause the
                # entire validation stage to crash.
                continue

            image_rectangles.extend(rectangles)

        image_area_points = sum(
            max(0.0, rectangle.width) * max(0.0, rectangle.height)
            for rectangle in image_rectangles
        )

        # Overlapping image rectangles can make the approximate sum larger than
        # the page itself. Capping it at 1.0 keeps the metric meaningful.
        image_coverage_ratio = min(
            image_area_points / page_area_points,
            1.0,
        )

        return len(image_rectangles), image_coverage_ratio

    def _evaluate_page(
        self,
        metrics: PageValidationMetrics,
    ) -> tuple[PdfRejectionCode, str] | None:
        """
        Apply validation rules to previously measured page metrics.

        Returning None means the page passed validation.
        """

        if metrics.width_points <= 0 or metrics.height_points <= 0:
            return (
                PdfRejectionCode.EMPTY_PAGE,
                f"Page {metrics.page_number} has invalid or zero dimensions.",
            )

        if (
            metrics.extracted_text_characters
            < self.config.minimum_text_characters
        ):
            return (
                PdfRejectionCode.NO_EXTRACTABLE_TEXT,
                (
                    f"Page {metrics.page_number} contains no meaningful "
                    "extractable text. It may be scanned or empty."
                ),
            )

        is_text_sparse = (
            metrics.text_density < self.config.minimum_text_density
        )

        is_image_dominated = (
            metrics.image_coverage_ratio
            >= self.config.maximum_image_coverage_ratio
        )

        if is_text_sparse and is_image_dominated:
            return (
                PdfRejectionCode.LIKELY_SCANNED_PDF,
                (
                    f"Page {metrics.page_number} is likely scanned: "
                    f"text density is {metrics.text_density:.4f} characters "
                    f"per square inch and image coverage is "
                    f"{metrics.image_coverage_ratio:.2%}."
                ),
            )

        return None
