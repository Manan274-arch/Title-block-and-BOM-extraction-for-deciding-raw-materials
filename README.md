# Engineering Drawing Material Extraction

Deterministic Python pipeline for extracting title-block data, Bill of Materials
(BOM) rows, and raw-material summaries from single-page, digital-native
engineering drawing PDFs. Every extracted value retains its source page and PDF
bounding box.

## Workflow

```text
Drawing PDF
    |
    v
PDF validation
    |  Rejects missing, invalid, encrypted, multi-page, empty, and scanned PDFs
    v
Layout extraction
    |  Collects words, text blocks, vector paths, page geometry, and images
    +-----------------------+
    |                       |
    v                       v
Title-block extraction   BOM extraction
    |                       |
    +-----------+-----------+
                v
        Material aggregation
                |
                v
          DrawingResult
                |
        +-------+-------+
        v               v
   Canonical JSON   Material CSV
```

1. `PdfValidator` confirms that the input is a supported digital-native PDF.
2. `LayoutExtractor` opens the validated page and preserves reusable text and
   vector coordinates without interpreting engineering content.
3. `TitleBlockExtractor` searches the lower drawing region using normalized
   labels, nearby-word geometry, and conservative regex fallbacks.
4. `BOMExtractor` detects an aligned header row, derives column boundaries, and
   returns cited BOM cells while rejecting unrelated numbered notes.
5. `MaterialAggregator` groups equivalent BOM materials, totals complete
   quantities, records contributing BOM rows, and handles `AS PER BOM`.
6. `OutputExporter` writes the full `DrawingResult` to JSON and derives a
   convenience raw-material CSV from that canonical payload.

The pipeline never performs OCR, calls an LLM, interprets dimensions, or invents
missing values. Missing fields are returned with an explicit `missing` status.

## Setup and Usage

Requires Python 3.11 or newer.

```powershell
python -m pip install -r requirements.txt
python main.py data\sample_drawings\SBA-001.pdf
```

Generated files are written to `outputs/json/` and `outputs/csv/`. Useful CLI
options include:

```powershell
python main.py drawing.pdf --no-export
python main.py drawing.pdf --output-name assembly-result
python main.py drawing.pdf --output-directory results
```

Exit code `0` means successful or partial extraction, `2` means the drawing was
rejected, and `3` means extraction succeeded but output writing failed.

## Repository Structure

```text
src/                         Validation, extraction, aggregation, and exporting
data/sample_drawings/        Five digital-native sample PDFs
data/ground_truth/           Expected values for the five samples
scripts/generate_sample_drawings.py
main.py                      Command-line entry point
requirements.txt             Runtime and sample-generation dependencies
```

Regenerate the sample PDFs and their matching ground truth with:

```powershell
python scripts\generate_sample_drawings.py
```

## Supported Scope

- Single-page, digital-native engineering drawing PDFs
- Bottom-region title blocks with common labels such as `TITLE`, `DRAWING NO.`,
  `REV.`, `MATERIAL`, `SCALE`, and approval fields
- BOM tables containing item number, part name/description, quantity, and material
- Traceable JSON plus a raw-material summary CSV

Scanned drawings, image-only PDFs, OCR, multi-page drawings, GD&T, dimension
interpretation, geometric reasoning, and assembly-sequence inference are outside
the current scope.
