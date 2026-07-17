from src.material_aggregator import MaterialAggregator
from src.schemas import (
    BOMRow,
    ExtractedField,
    ExtractionStatus,
    TitleBlock,
)


def field(value: str | None, status: ExtractionStatus = ExtractionStatus.MATCHED) -> ExtractedField:
    return ExtractedField(value=value, status=status)


def bom_row(material: str | None, quantity: str | None) -> BOMRow:
    missing = field(None, ExtractionStatus.MISSING)
    return BOMRow(
        item_number=field("1"),
        part_number=missing,
        description=field("PART"),
        material=(field(material) if material is not None else missing),
        quantity=(field(quantity) if quantity is not None else missing),
    )


def title_block(material: str | None) -> TitleBlock:
    missing = field(None, ExtractionStatus.MISSING)
    return TitleBlock(
        drawing_number=missing,
        drawing_title=missing,
        revision=missing,
        material=(field(material) if material is not None else missing),
        scale=missing,
        drawn_by=missing,
        checked_by=missing,
        approved_by=missing,
        drawing_date=missing,
    )


def test_groups_materials_and_sums_complete_quantities() -> None:
    result = MaterialAggregator().aggregate(
        [
            bom_row("Mild Steel", "2"),
            bom_row("M.S.", "3"),
            bom_row("Cast Iron", "1"),
        ]
    )

    assert [item.material for item in result] == ["CAST IRON", "MILD STEEL"]
    assert result[0].quantity == 1.0
    assert result[0].source_bom_rows == [3]
    assert result[1].quantity == 5.0
    assert result[1].source_bom_rows == [1, 2]


def test_incomplete_group_quantity_is_not_understated() -> None:
    result = MaterialAggregator().aggregate(
        [bom_row("MILD STEEL", "2"), bom_row("MILD STEEL", None)]
    )

    assert result[0].quantity is None
    assert result[0].source_bom_rows == [1, 2]


def test_ignores_missing_and_bom_reference_materials() -> None:
    result = MaterialAggregator().aggregate(
        [bom_row(None, "1"), bom_row("AS PER BOM", "1"), bom_row("-", "1")]
    )

    assert result == []


def test_uses_concrete_title_material_only_when_bom_is_empty() -> None:
    aggregator = MaterialAggregator()

    result = aggregator.aggregate([], title_block("Aluminium 6061"))

    assert result[0].material == "ALUMINIUM 6061"
    assert result[0].quantity is None
    assert result[0].source_bom_rows == []
    assert aggregator.aggregate([], title_block("AS PER BOM")) == []


def test_bom_takes_precedence_over_title_material() -> None:
    result = MaterialAggregator().aggregate(
        [bom_row("CAST IRON", "1")],
        title_block("MILD STEEL"),
    )

    assert [item.material for item in result] == ["CAST IRON"]
