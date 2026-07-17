from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .schemas import DrawingResult


class OutputExportError(str, Enum):
    """Machine-readable reasons output generation failed."""

    INVALID_OUTPUT_NAME = "invalid_output_name"
    DIRECTORY_ERROR = "directory_error"
    WRITE_ERROR = "write_error"


@dataclass(frozen=True)
class OutputExporterConfig:
    """Destination and formatting settings for canonical outputs."""

    json_directory: Path = Path("outputs/json")
    csv_directory: Path = Path("outputs/csv")
    json_indent: int = 2

    def __post_init__(self) -> None:
        if self.json_indent < 0:
            raise ValueError("json_indent cannot be negative.")


@dataclass(frozen=True)
class OutputExportResult:
    """Controlled result of writing canonical JSON and summary CSV."""

    is_successful: bool
    json_path: Path | None = None
    csv_path: Path | None = None
    error_code: OutputExportError | None = None
    error_reason: str | None = None

    @classmethod
    def succeeded(cls, *, json_path: Path, csv_path: Path) -> OutputExportResult:
        """Create a successful export result."""
        return cls(is_successful=True, json_path=json_path, csv_path=csv_path)

    @classmethod
    def failed(
        cls,
        *,
        code: OutputExportError,
        reason: str,
    ) -> OutputExportResult:
        """Create a controlled failed export result."""
        return cls(is_successful=False, error_code=code, error_reason=reason)


class OutputExporter:
    """Write canonical JSON and derive a raw-material CSV from that payload."""

    def __init__(self, config: OutputExporterConfig | None = None) -> None:
        self.config = config or OutputExporterConfig()

    def export(
        self,
        result: DrawingResult,
        output_name: str | None = None,
    ) -> OutputExportResult:
        """Atomically write both representations of a validated drawing result."""
        stem = _safe_output_stem(output_name or result.source_file)
        if stem is None:
            return OutputExportResult.failed(
                code=OutputExportError.INVALID_OUTPUT_NAME,
                reason="The output name does not contain a usable filename.",
            )

        json_path = self.config.json_directory / f"{stem}.json"
        csv_path = self.config.csv_directory / f"{stem}.csv"

        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return OutputExportResult.failed(
                code=OutputExportError.DIRECTORY_ERROR,
                reason=f"Could not prepare output directories: {exc}",
            )

        payload = result.model_dump(mode="json")
        json_text = json.dumps(
            payload,
            indent=self.config.json_indent,
            ensure_ascii=False,
        ) + "\n"
        csv_text = _raw_material_csv(payload)

        try:
            _atomic_write_text(json_path, json_text)
            _atomic_write_text(csv_path, csv_text)
        except OSError as exc:
            return OutputExportResult.failed(
                code=OutputExportError.WRITE_ERROR,
                reason=f"Could not write output files: {exc}",
            )

        return OutputExportResult.succeeded(json_path=json_path, csv_path=csv_path)


def _safe_output_stem(value: str) -> str | None:
    """Create a portable filename stem without allowing path traversal."""
    stem = Path(value).stem.strip()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)
    stem = stem.strip("._-")
    return stem or None


def _raw_material_csv(payload: Mapping[str, Any]) -> str:
    """Generate the convenience CSV only from canonical JSON-compatible data."""
    stream = io.StringIO(newline="")
    field_names = ("material", "quantity", "source_bom_rows")
    writer = csv.DictWriter(stream, fieldnames=field_names, lineterminator="\n")
    writer.writeheader()

    materials = payload.get("raw_material_list", [])
    if not isinstance(materials, Sequence) or isinstance(materials, (str, bytes)):
        return stream.getvalue()

    for material in materials:
        if not isinstance(material, Mapping):
            continue
        source_rows = material.get("source_bom_rows", [])
        if not isinstance(source_rows, Sequence) or isinstance(source_rows, (str, bytes)):
            source_rows = []
        writer.writerow(
            {
                "material": material.get("material", ""),
                "quantity": _csv_quantity(material.get("quantity")),
                "source_bom_rows": ";".join(str(row) for row in source_rows),
            }
        )

    return stream.getvalue()


def _csv_quantity(value: Any) -> str:
    """Represent an optional numeric quantity without inventing a zero."""
    return "" if value is None else str(value)


def _atomic_write_text(path: Path, content: str) -> None:
    """Replace one output only after its complete content reaches disk."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
