from pathlib import Path

from src.bom_extractor import BOMExtractorConfig
from src.config import ApplicationConfig
from src.material_aggregator import MaterialAggregatorConfig
from src.output_exporter import OutputExporterConfig
from src.pdf_validator import PdfValidatorConfig
from src.pipeline import DrawingPipeline
from src.title_block_extractor import TitleBlockExtractorConfig


def test_application_config_composes_stage_defaults() -> None:
    config = ApplicationConfig()

    assert isinstance(config.pdf_validator, PdfValidatorConfig)
    assert isinstance(config.title_block, TitleBlockExtractorConfig)
    assert isinstance(config.bom, BOMExtractorConfig)
    assert isinstance(config.materials, MaterialAggregatorConfig)
    assert isinstance(config.output, OutputExporterConfig)


def test_output_directory_override_returns_a_new_config() -> None:
    original = ApplicationConfig()

    changed = original.with_output_directory(Path("results"))

    assert changed is not original
    assert changed.output.json_directory == Path("results/json")
    assert changed.output.csv_directory == Path("results/csv")
    assert original.output.json_directory == Path("outputs/json")


def test_pipeline_from_config_wires_each_custom_setting() -> None:
    config = ApplicationConfig(
        pdf_validator=PdfValidatorConfig(minimum_text_density=3.5),
        title_block=TitleBlockExtractorConfig(region_top_ratio=0.70),
        bom=BOMExtractorConfig(row_tolerance=6.0),
        materials=MaterialAggregatorConfig(aliases=(("AL", "ALUMINIUM"),)),
        output=OutputExporterConfig(json_indent=4),
    )

    pipeline = DrawingPipeline.from_config(config)

    assert pipeline.validator.config.minimum_text_density == 3.5
    assert pipeline.title_block_extractor.config.region_top_ratio == 0.70
    assert pipeline.bom_extractor.config.row_tolerance == 6.0
    assert pipeline.material_aggregator.config.aliases == (("AL", "ALUMINIUM"),)
    assert pipeline.output_exporter.config.json_indent == 4
