from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from src.config import ApplicationConfig
from src.pipeline import DrawingPipeline
from src.schemas import DrawingStatus


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line interface for processing one drawing PDF."""
    parser = argparse.ArgumentParser(
        description=(
            "Extract traceable title-block, BOM, and raw-material data from "
            "a digital-native engineering drawing PDF."
        )
    )
    parser.add_argument("pdf", type=Path, help="Path to a single-page drawing PDF.")
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Print canonical JSON without writing JSON or CSV files.",
    )
    parser.add_argument(
        "--output-name",
        help="Filename stem for generated outputs; defaults to the PDF filename.",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        help="Base directory for json/ and csv/ outputs; defaults to outputs/.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    pipeline: DrawingPipeline | None = None,
) -> int:
    """Run the drawing pipeline and return a process-friendly exit code."""
    args = build_parser().parse_args(argv)
    active_pipeline = pipeline or _pipeline_for_output_directory(args.output_directory)
    run = active_pipeline.run(
        args.pdf,
        export_outputs=not args.no_export,
        output_name=args.output_name,
    )

    if args.no_export:
        print(run.drawing.model_dump_json(indent=2))
    else:
        print(f"status: {run.drawing.status.value}")
        print(f"source: {run.drawing.source_file}")
        if run.export is not None and run.export.is_successful:
            print(f"json: {run.export.json_path}")
            print(f"csv: {run.export.csv_path}")

    if run.drawing.status is DrawingStatus.REJECTED:
        print(f"rejection: {run.drawing.rejection_reason or 'Unknown reason.'}")
        return 2

    if run.export is not None and not run.export.is_successful:
        print(f"export_error: {run.export.error_reason or 'Unknown export error.'}")
        return 3

    return 0


def _pipeline_for_output_directory(output_directory: Path | None) -> DrawingPipeline:
    """Build the default pipeline with optional output-directory overrides."""
    config = ApplicationConfig()
    if output_directory is not None:
        config = config.with_output_directory(output_directory)
    return DrawingPipeline.from_config(config)


if __name__ == "__main__":
    raise SystemExit(main())
