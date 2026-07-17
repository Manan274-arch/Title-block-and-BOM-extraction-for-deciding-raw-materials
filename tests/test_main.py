from pathlib import Path
from unittest.mock import Mock

from main import main
from src.output_exporter import OutputExportError, OutputExportResult
from src.pipeline import PipelineRunResult
from src.schemas import DrawingResult, DrawingStatus


def test_cli_runs_pipeline_and_prints_output_paths(capsys: object) -> None:
    pipeline = Mock()
    pipeline.run.return_value = PipelineRunResult(
        drawing=DrawingResult(
            status=DrawingStatus.SUCCESS,
            source_file="drawing.pdf",
        ),
        export=OutputExportResult.succeeded(
            json_path=Path("outputs/json/drawing.json"),
            csv_path=Path("outputs/csv/drawing.csv"),
        ),
    )

    exit_code = main(["drawing.pdf"], pipeline=pipeline)

    assert exit_code == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "status: success" in output
    assert str(Path("outputs/json/drawing.json")) in output
    pipeline.run.assert_called_once_with(
        Path("drawing.pdf"),
        export_outputs=True,
        output_name=None,
    )


def test_cli_prints_json_in_no_export_mode(capsys: object) -> None:
    pipeline = Mock()
    pipeline.run.return_value = PipelineRunResult(
        drawing=DrawingResult(
            status=DrawingStatus.PARTIAL,
            source_file="drawing.pdf",
        )
    )

    exit_code = main(["drawing.pdf", "--no-export"], pipeline=pipeline)

    assert exit_code == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert '"status": "partial"' in output
    assert '"source_file": "drawing.pdf"' in output


def test_cli_returns_two_for_rejected_drawing(capsys: object) -> None:
    pipeline = Mock()
    pipeline.run.return_value = PipelineRunResult(
        drawing=DrawingResult(
            status=DrawingStatus.REJECTED,
            rejection_reason="Document is scanned.",
            source_file="scan.pdf",
        )
    )

    exit_code = main(["scan.pdf", "--no-export"], pipeline=pipeline)

    assert exit_code == 2
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "rejection: Document is scanned." in output


def test_cli_returns_three_when_export_fails(capsys: object) -> None:
    pipeline = Mock()
    pipeline.run.return_value = PipelineRunResult(
        drawing=DrawingResult(
            status=DrawingStatus.SUCCESS,
            source_file="drawing.pdf",
        ),
        export=OutputExportResult.failed(
            code=OutputExportError.WRITE_ERROR,
            reason="Disk full.",
        ),
    )

    exit_code = main(["drawing.pdf"], pipeline=pipeline)

    assert exit_code == 3
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "export_error: Disk full." in output


def test_cli_passes_output_name_to_pipeline() -> None:
    pipeline = Mock()
    pipeline.run.return_value = PipelineRunResult(
        drawing=DrawingResult(
            status=DrawingStatus.SUCCESS,
            source_file="drawing.pdf",
        )
    )

    main(["drawing.pdf", "--no-export", "--output-name", "assembly"], pipeline=pipeline)

    pipeline.run.assert_called_once_with(
        Path("drawing.pdf"),
        export_outputs=False,
        output_name="assembly",
    )
