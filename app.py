from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from src.config import ApplicationConfig
from src.pipeline import DrawingPipeline
from src.schemas import DrawingResult, DrawingStatus, ExtractedField


MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class ProcessedUpload:
    """Display-ready pipeline result retained after temporary files are removed."""

    drawing: DrawingResult
    json_bytes: bytes | None
    csv_bytes: bytes | None
    json_name: str
    csv_name: str
    export_error: str | None = None


def process_upload(file_name: str, content: bytes) -> ProcessedUpload:
    """Process one uploaded PDF entirely inside a temporary directory."""
    safe_name = _safe_pdf_name(file_name)
    with tempfile.TemporaryDirectory(prefix="drawing-extractor-") as temporary:
        root = Path(temporary)
        pdf_path = root / safe_name
        pdf_path.write_bytes(content)

        config = ApplicationConfig().with_output_directory(root / "outputs")
        run = DrawingPipeline.from_config(config).run(pdf_path)
        stem = pdf_path.stem

        json_bytes: bytes | None = None
        csv_bytes: bytes | None = None
        export_error: str | None = None
        if run.export is not None and run.export.is_successful:
            if run.export.json_path is not None:
                json_bytes = run.export.json_path.read_bytes()
            if run.export.csv_path is not None:
                csv_bytes = run.export.csv_path.read_bytes()
        elif run.export is not None:
            export_error = run.export.error_reason or "Output generation failed."

        return ProcessedUpload(
            drawing=run.drawing,
            json_bytes=json_bytes,
            csv_bytes=csv_bytes,
            json_name=f"{stem}.json",
            csv_name=f"{stem}.csv",
            export_error=export_error,
        )


def main() -> None:
    """Render the Streamlit upload and extraction interface."""
    st.set_page_config(
        page_title="Engineering Drawing Extractor",
        page_icon=None,
        layout="wide",
    )
    st.title("Engineering Drawing Extractor")

    uploaded = st.file_uploader("Drawing PDF", type=["pdf"], accept_multiple_files=False)
    process_clicked = st.button("Process drawing", type="primary", disabled=uploaded is None)

    if process_clicked and uploaded is not None:
        if uploaded.size > MAX_UPLOAD_BYTES:
            st.error("The PDF exceeds the 25 MB upload limit.")
        else:
            try:
                with st.spinner("Processing drawing..."):
                    st.session_state["processed_upload"] = process_upload(
                        uploaded.name,
                        uploaded.getvalue(),
                    )
            except (OSError, ValueError) as exc:
                st.session_state.pop("processed_upload", None)
                st.error(f"The upload could not be processed: {exc}")

    processed = st.session_state.get("processed_upload")
    if isinstance(processed, ProcessedUpload):
        _render_result(processed)


def _render_result(processed: ProcessedUpload) -> None:
    """Render status, structured extraction tables, and output controls."""
    drawing = processed.drawing
    if drawing.status is DrawingStatus.SUCCESS:
        st.success("Extraction completed successfully.")
    elif drawing.status is DrawingStatus.PARTIAL:
        st.warning("Extraction completed with missing fields.")
    else:
        st.error(drawing.rejection_reason or "The drawing was rejected.")

    if processed.export_error:
        st.error(processed.export_error)

    st.caption("Click a button below to download the file. Your extraction results will remain unchanged.")
    download_columns = st.columns(2)
    with download_columns[0]:
        st.download_button(
            "Click to download JSON result",
            data=processed.json_bytes or drawing.model_dump_json(indent=2).encode("utf-8"),
            file_name=processed.json_name,
            mime="application/json",
            key="download_json_result",
            on_click="ignore",
            use_container_width=True,
        )
    with download_columns[1]:
        st.download_button(
            "Click to download material CSV",
            data=processed.csv_bytes or b"material,quantity,source_bom_rows\n",
            file_name=processed.csv_name,
            mime="text/csv",
            key="download_material_csv",
            on_click="ignore",
            use_container_width=True,
        )

    title_tab, bom_tab, material_tab, json_tab = st.tabs(
        ["Title block", "BOM", "Raw materials", "JSON"]
    )
    with title_tab:
        _render_title_block(drawing)
    with bom_tab:
        _render_bom(drawing)
    with material_tab:
        _render_materials(drawing)
    with json_tab:
        st.json(json.loads(drawing.model_dump_json()))


def _render_title_block(drawing: DrawingResult) -> None:
    if drawing.title_block is None:
        st.info("No title-block result is available.")
        return

    rows = []
    for field_name in drawing.title_block.__class__.model_fields:
        field = getattr(drawing.title_block, field_name)
        rows.append(
            {
                "Field": field_name.replace("_", " ").title(),
                "Value": field.value or "",
                "Status": field.status.value,
                "Page": field.citation.page if field.citation else "",
                "Bounding box": _bbox_text(field),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_bom(drawing: DrawingResult) -> None:
    if not drawing.bom:
        st.info("No BOM rows were extracted.")
        return
    rows = [
        {
            "Item": row.item_number.value or "",
            "Part number": row.part_number.value or "",
            "Description": row.description.value or "",
            "Quantity": row.quantity.value or "",
            "Material": row.material.value or "",
        }
        for row in drawing.bom
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_materials(drawing: DrawingResult) -> None:
    if not drawing.raw_material_list:
        st.info("No raw-material entries were produced.")
        return
    rows = [
        {
            "Material": item.material,
            "Quantity": "" if item.quantity is None else item.quantity,
            "Source BOM rows": ", ".join(str(row) for row in item.source_bom_rows),
        }
        for item in drawing.raw_material_list
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _safe_pdf_name(file_name: str) -> str:
    """Return a local filename while preventing traversal and non-PDF uploads."""
    original = Path(file_name).name
    if Path(original).suffix.lower() != ".pdf":
        raise ValueError("Only PDF uploads are supported.")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original).stem).strip("._-")
    if not stem:
        raise ValueError("The uploaded PDF does not have a usable filename.")
    return f"{stem}.pdf"


def _bbox_text(field: ExtractedField) -> str:
    if field.citation is None:
        return ""
    bbox = field.citation.bbox
    return f"({bbox.x0:.1f}, {bbox.top:.1f}, {bbox.x1:.1f}, {bbox.bottom:.1f})"


if __name__ == "__main__":
    main()
