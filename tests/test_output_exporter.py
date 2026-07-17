import csv
import json
from pathlib import Path

from src.output_exporter import OutputExporter, OutputExporterConfig
from src.schemas import DrawingResult, DrawingStatus, RawMaterialItem


def exporter(tmp_path: Path) -> OutputExporter:
    return OutputExporter(
        OutputExporterConfig(
            json_directory=tmp_path / "json",
            csv_directory=tmp_path / "csv",
        )
    )


def test_writes_canonical_json_and_material_csv(tmp_path: Path) -> None:
    result = DrawingResult(
        status=DrawingStatus.SUCCESS,
        source_file="SBA-001.pdf",
        raw_material_list=[
            RawMaterialItem(
                material="MILD STEEL",
                quantity=5.0,
                source_bom_rows=[1, 2, 4],
            )
        ],
    )

    exported = exporter(tmp_path).export(result)

    assert exported.is_successful
    assert exported.json_path is not None
    assert exported.csv_path is not None
    payload = json.loads(exported.json_path.read_text(encoding="utf-8"))
    assert payload == result.model_dump(mode="json")
    with exported.csv_path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows == [
        {
            "material": "MILD STEEL",
            "quantity": "5.0",
            "source_bom_rows": "1;2;4",
        }
    ]


def test_material_free_result_produces_header_only_csv(tmp_path: Path) -> None:
    result = DrawingResult(
        status=DrawingStatus.REJECTED,
        rejection_reason="Invalid PDF",
        source_file="invalid.pdf",
    )

    exported = exporter(tmp_path).export(result)

    assert exported.is_successful
    assert exported.csv_path is not None
    assert exported.csv_path.read_text(encoding="utf-8") == (
        "material,quantity,source_bom_rows\n"
    )


def test_sanitizes_override_without_allowing_directory_escape(tmp_path: Path) -> None:
    result = DrawingResult(status=DrawingStatus.SUCCESS, source_file="drawing.pdf")

    exported = exporter(tmp_path).export(result, "../../Assembly A.pdf")

    assert exported.is_successful
    assert exported.json_path == tmp_path / "json" / "Assembly_A.json"
    assert exported.csv_path == tmp_path / "csv" / "Assembly_A.csv"


def test_rejects_an_output_name_without_a_usable_stem(tmp_path: Path) -> None:
    result = DrawingResult(status=DrawingStatus.SUCCESS, source_file="drawing.pdf")

    exported = exporter(tmp_path).export(result, "...")

    assert not exported.is_successful
    assert exported.json_path is None
    assert exported.csv_path is None
