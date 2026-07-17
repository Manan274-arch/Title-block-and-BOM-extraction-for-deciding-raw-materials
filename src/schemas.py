from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ExtractionStatus(str, Enum):
    MATCHED = "matched"
    FALLBACK_MATCHED = "fallback_matched"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class DrawingStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    REJECTED = "rejected"


class BoundingBox(BaseModel):
    x0: float
    top: float
    x1: float
    bottom: float


class Citation(BaseModel):
    page: int = Field(ge=1)
    bbox: BoundingBox


class ExtractedField(BaseModel):
    value: Optional[str] = None
    status: ExtractionStatus
    citation: Optional[Citation] = None


class TitleBlock(BaseModel):
    drawing_number: ExtractedField
    drawing_title: ExtractedField
    revision: ExtractedField
    material: ExtractedField
    scale: ExtractedField
    drawn_by: ExtractedField
    checked_by: ExtractedField
    approved_by: ExtractedField
    drawing_date: ExtractedField


class BOMRow(BaseModel):
    item_number: ExtractedField
    part_number: ExtractedField
    description: ExtractedField
    material: ExtractedField
    quantity: ExtractedField


class RawMaterialItem(BaseModel):
    material: str
    quantity: Optional[float] = None
    source_bom_rows: list[int] = Field(default_factory=list)


class DrawingResult(BaseModel):
    status: DrawingStatus
    rejection_reason: Optional[str] = None
    source_file: str
    title_block: Optional[TitleBlock] = None
    bom: list[BOMRow] = Field(default_factory=list)
    raw_material_list: list[RawMaterialItem] = Field(default_factory=list)