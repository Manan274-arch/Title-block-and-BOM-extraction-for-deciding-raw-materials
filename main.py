from src.schemas import (
    BoundingBox,
    Citation,
    DrawingResult,
    DrawingStatus,
    ExtractedField,
    ExtractionStatus,
    TitleBlock,
)


def missing_field() -> ExtractedField:
    return ExtractedField(
        value=None,
        status=ExtractionStatus.MISSING,
        citation=None,
    )


material_field = ExtractedField(
    value="AISI 304",
    status=ExtractionStatus.MATCHED,
    citation=Citation(
        page=1,
        bbox=BoundingBox(
            x0=420,
            top=690,
            x1=480,
            bottom=710,
        ),
    ),
)

title_block = TitleBlock(
    drawing_number=missing_field(),
    drawing_title=missing_field(),
    revision=missing_field(),
    material=material_field,
    scale=missing_field(),
    drawn_by=missing_field(),
    checked_by=missing_field(),
    approved_by=missing_field(),
    drawing_date=missing_field(),
)

result = DrawingResult(
    status=DrawingStatus.PARTIAL,
    source_file="sample_drawing.pdf",
    title_block=title_block,
)

print(result.model_dump_json(indent=2))