from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .bom_extractor import BOMExtractorConfig
from .material_aggregator import MaterialAggregatorConfig
from .output_exporter import OutputExporterConfig
from .pdf_validator import PdfValidatorConfig
from .title_block_extractor import TitleBlockExtractorConfig


@dataclass(frozen=True)
class ApplicationConfig:
    """Central immutable configuration for every adjustable pipeline stage."""

    pdf_validator: PdfValidatorConfig = field(default_factory=PdfValidatorConfig)
    title_block: TitleBlockExtractorConfig = field(
        default_factory=TitleBlockExtractorConfig
    )
    bom: BOMExtractorConfig = field(default_factory=BOMExtractorConfig)
    materials: MaterialAggregatorConfig = field(
        default_factory=MaterialAggregatorConfig
    )
    output: OutputExporterConfig = field(default_factory=OutputExporterConfig)

    def with_output_directory(self, directory: str | Path) -> ApplicationConfig:
        """Return a copy that writes JSON and CSV beneath one base directory."""
        base_directory = Path(directory)
        output = replace(
            self.output,
            json_directory=base_directory / "json",
            csv_directory=base_directory / "csv",
        )
        return replace(self, output=output)
