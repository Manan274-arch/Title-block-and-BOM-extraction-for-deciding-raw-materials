from pathlib import Path
from unittest.mock import Mock

from src.layout_extractor import LayoutExtractionError, LayoutExtractionResult, PageLayout
from src.output_exporter import OutputExportResult
from src.pdf_validator import PdfRejectionCode, PdfValidationResult
from src.pipeline import DrawingPipeline
from src.schemas import (
    BOMRow,
    DrawingStatus,
    ExtractedField,
    ExtractionStatus,
    RawMaterialItem,
    TitleBlock,
)


def field(
    value: str | None,
    status: ExtractionStatus = ExtractionStatus.MATCHED,
) -> ExtractedField:
    return ExtractedField(value=value, status=status)


def complete_title(material: str = "AS PER BOM") -> TitleBlock:
    return TitleBlock(
        drawing_number=field("SBA-001"),
        drawing_title=field("SUPPORT BRACKET ASSEMBLY"),
        revision=field("A"),
        material=field(material),
        scale=field("1:1"),
        drawn_by=field("R. KUMAR"),
        checked_by=field("S. NAIR"),
        approved_by=field("P. MENON"),
        drawing_date=field("15-05-2024"),
    )


def complete_bom_row() -> BOMRow:
    return BOMRow(
        item_number=field("1"),
        part_number=field(None, ExtractionStatus.MISSING),
        description=field("HEX BOLT M10 x 25"),
        material=field("MILD STEEL"),
        quantity=field("1"),
    )


def dependencies() -> dict[str, Mock]:
    return {
        "validator": Mock(),
        "layout_extractor": Mock(),
        "title_block_extractor": Mock(),
        "bom_extractor": Mock(),
        "material_aggregator": Mock(),
        "output_exporter": Mock(),
    }


def valid_layout() -> LayoutExtractionResult:
    return LayoutExtractionResult.succeeded(
        source_file="drawing.pdf",
        page=PageLayout(page_number=1, width=100, height=100, rotation=0),
    )


def test_validation_rejection_stops_later_stages() -> None:
    deps = dependencies()
    deps["validator"].validate.return_value = PdfValidationResult.rejected(
        source_file="missing.pdf",
        code=PdfRejectionCode.FILE_NOT_FOUND,
        reason="PDF file does not exist.",
    )
    pipeline = DrawingPipeline(**deps)

    result = pipeline.run("missing.pdf", export_outputs=False)

    assert result.drawing.status is DrawingStatus.REJECTED
    assert result.drawing.rejection_reason == "PDF file does not exist."
    deps["layout_extractor"].extract.assert_not_called()
    deps["output_exporter"].export.assert_not_called()


def test_layout_failure_stops_extractors() -> None:
    deps = dependencies()
    deps["validator"].validate.return_value = PdfValidationResult.accepted(
        source_file="drawing.pdf", page_count=1, pages=[]
    )
    deps["layout_extractor"].extract.return_value = LayoutExtractionResult.failed(
        source_file="drawing.pdf",
        code=LayoutExtractionError.EXTRACTION_ERROR,
        reason="Layout failed.",
    )
    pipeline = DrawingPipeline(**deps)

    result = pipeline.run(Path("drawing.pdf"), export_outputs=False)

    assert result.drawing.status is DrawingStatus.REJECTED
    deps["title_block_extractor"].extract.assert_not_called()
    deps["bom_extractor"].extract.assert_not_called()


def test_successful_run_passes_one_layout_through_all_stages() -> None:
    deps = dependencies()
    layout = valid_layout()
    title = complete_title()
    bom = [complete_bom_row()]
    materials = [
        RawMaterialItem(material="MILD STEEL", quantity=1, source_bom_rows=[1])
    ]
    deps["validator"].validate.return_value = PdfValidationResult.accepted(
        source_file="drawing.pdf", page_count=1, pages=[]
    )
    deps["layout_extractor"].extract.return_value = layout
    deps["title_block_extractor"].extract.return_value = title
    deps["bom_extractor"].extract.return_value = bom
    deps["material_aggregator"].aggregate.return_value = materials
    deps["output_exporter"].export.return_value = OutputExportResult.succeeded(
        json_path=Path("drawing.json"), csv_path=Path("drawing.csv")
    )
    pipeline = DrawingPipeline(**deps)

    result = pipeline.run("drawing.pdf")

    assert result.drawing.status is DrawingStatus.SUCCESS
    assert result.drawing.bom == bom
    assert result.drawing.raw_material_list == materials
    assert result.export is not None and result.export.is_successful
    deps["title_block_extractor"].extract.assert_called_once_with(layout)
    deps["bom_extractor"].extract.assert_called_once_with(layout)
    deps["material_aggregator"].aggregate.assert_called_once_with(bom, title)


def test_missing_required_title_field_marks_result_partial() -> None:
    deps = dependencies()
    title = complete_title(material="MILD STEEL")
    title.revision = field(None, ExtractionStatus.MISSING)
    deps["validator"].validate.return_value = PdfValidationResult.accepted(
        source_file="drawing.pdf", page_count=1, pages=[]
    )
    deps["layout_extractor"].extract.return_value = valid_layout()
    deps["title_block_extractor"].extract.return_value = title
    deps["bom_extractor"].extract.return_value = []
    deps["material_aggregator"].aggregate.return_value = [
        RawMaterialItem(material="MILD STEEL")
    ]
    pipeline = DrawingPipeline(**deps)

    result = pipeline.run("drawing.pdf", export_outputs=False)

    assert result.drawing.status is DrawingStatus.PARTIAL


def test_export_failure_does_not_discard_extraction_result() -> None:
    deps = dependencies()
    deps["validator"].validate.return_value = PdfValidationResult.accepted(
        source_file="drawing.pdf", page_count=1, pages=[]
    )
    deps["layout_extractor"].extract.return_value = valid_layout()
    deps["title_block_extractor"].extract.return_value = complete_title("MILD STEEL")
    deps["bom_extractor"].extract.return_value = []
    deps["material_aggregator"].aggregate.return_value = [
        RawMaterialItem(material="MILD STEEL")
    ]
    deps["output_exporter"].export.return_value = OutputExportResult.failed(
        code="write_error", reason="Disk full."
    )
    pipeline = DrawingPipeline(**deps)

    result = pipeline.run("drawing.pdf")

    assert result.drawing.status is DrawingStatus.SUCCESS
    assert result.export is not None and not result.export.is_successful
