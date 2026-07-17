from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .bom_extractor import BOMExtractor
from .config import ApplicationConfig
from .layout_extractor import LayoutExtractor
from .material_aggregator import MaterialAggregator
from .output_exporter import OutputExportResult, OutputExporter
from .pdf_validator import PdfValidator
from .schemas import (
    BOMRow,
    DrawingResult,
    DrawingStatus,
    ExtractionStatus,
    TitleBlock,
)
from .title_block_extractor import TitleBlockExtractor


@dataclass(frozen=True)
class PipelineRunResult:
    """Canonical extraction result plus its optional export outcome."""

    drawing: DrawingResult
    export: OutputExportResult | None = None


class DrawingPipeline:
    """Coordinate deterministic drawing extraction from validation to output."""

    def __init__(
        self,
        *,
        validator: PdfValidator | None = None,
        layout_extractor: LayoutExtractor | None = None,
        title_block_extractor: TitleBlockExtractor | None = None,
        bom_extractor: BOMExtractor | None = None,
        material_aggregator: MaterialAggregator | None = None,
        output_exporter: OutputExporter | None = None,
    ) -> None:
        self.validator = validator or PdfValidator()
        self.layout_extractor = layout_extractor or LayoutExtractor()
        self.title_block_extractor = title_block_extractor or TitleBlockExtractor()
        self.bom_extractor = bom_extractor or BOMExtractor()
        self.material_aggregator = material_aggregator or MaterialAggregator()
        self.output_exporter = output_exporter or OutputExporter()

    @classmethod
    def from_config(cls, config: ApplicationConfig) -> DrawingPipeline:
        """Construct every configurable stage from one application configuration."""
        return cls(
            validator=PdfValidator(config.pdf_validator),
            title_block_extractor=TitleBlockExtractor(config.title_block),
            bom_extractor=BOMExtractor(config.bom),
            material_aggregator=MaterialAggregator(config.materials),
            output_exporter=OutputExporter(config.output),
        )

    def run(
        self,
        pdf_path: str | Path,
        *,
        export_outputs: bool = True,
        output_name: str | None = None,
    ) -> PipelineRunResult:
        """Run each stage once, stopping when validation or layout fails."""
        path = Path(pdf_path)
        source_file = path.name

        validation = self.validator.validate(path)
        source_file = validation.source_file or source_file
        if not validation.is_valid:
            drawing = _rejected_result(
                source_file=source_file,
                reason=validation.rejection_reason or "PDF validation failed.",
            )
            return self._finish(drawing, export_outputs, output_name)

        layout = self.layout_extractor.extract(path)
        if not layout.is_successful or layout.page is None:
            drawing = _rejected_result(
                source_file=source_file,
                reason=layout.error_reason or "Page layout extraction failed.",
            )
            return self._finish(drawing, export_outputs, output_name)

        try:
            title_block = self.title_block_extractor.extract(layout)
            bom = self.bom_extractor.extract(layout)
            materials = self.material_aggregator.aggregate(bom, title_block)
            drawing = DrawingResult(
                status=_drawing_status(title_block, bom, bool(materials)),
                rejection_reason=None,
                source_file=source_file,
                title_block=title_block,
                bom=bom,
                raw_material_list=materials,
            )
        except Exception as exc:
            drawing = _rejected_result(
                source_file=source_file,
                reason=(
                    "An unexpected error occurred during deterministic extraction: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        return self._finish(drawing, export_outputs, output_name)

    def _finish(
        self,
        drawing: DrawingResult,
        export_outputs: bool,
        output_name: str | None,
    ) -> PipelineRunResult:
        """Optionally export without changing the extraction result's status."""
        if not export_outputs:
            return PipelineRunResult(drawing=drawing)
        exported = self.output_exporter.export(drawing, output_name)
        return PipelineRunResult(drawing=drawing, export=exported)


def _rejected_result(*, source_file: str, reason: str) -> DrawingResult:
    """Build the canonical result for a stopped pipeline."""
    return DrawingResult(
        status=DrawingStatus.REJECTED,
        rejection_reason=reason,
        source_file=source_file,
    )


def _drawing_status(
    title_block: TitleBlock,
    bom: list[BOMRow],
    has_material_summary: bool,
) -> DrawingStatus:
    """Classify completed extraction as success or explicitly partial."""
    title_fields = (
        title_block.drawing_number,
        title_block.drawing_title,
        title_block.revision,
        title_block.material,
        title_block.scale,
        title_block.drawn_by,
        title_block.checked_by,
        title_block.approved_by,
        title_block.drawing_date,
    )
    if any(field.status is ExtractionStatus.MISSING for field in title_fields):
        return DrawingStatus.PARTIAL

    required_bom_fields = (
        "item_number",
        "description",
        "material",
        "quantity",
    )
    if any(
        getattr(row, field_name).status is ExtractionStatus.MISSING
        for row in bom
        for field_name in required_bom_fields
    ):
        return DrawingStatus.PARTIAL

    material_value = (title_block.material.value or "").strip().upper()
    title_refers_to_bom = material_value in {"AS PER BOM", "PER BOM", "SEE BOM"}
    if title_refers_to_bom and not bom:
        return DrawingStatus.PARTIAL
    if (bom or title_block.material.value) and not has_material_summary:
        return DrawingStatus.PARTIAL
    return DrawingStatus.SUCCESS
