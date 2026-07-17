from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen.canvas import Canvas


@dataclass(frozen=True)
class BOMItem:
    item_number: str
    part_name: str
    quantity: str
    material: str
    remarks: str = "-"


@dataclass(frozen=True)
class DrawingDefinition:
    drawing_number: str
    title: str
    revision: str
    scale: str
    drawn_date: str
    checked_date: str
    approved_date: str
    bom: tuple[BOMItem, ...]
    diagram: str


DRAWINGS = (
    DrawingDefinition(
        drawing_number="SBA-001",
        title="SUPPORT BRACKET ASSEMBLY",
        revision="A",
        scale="1:1",
        drawn_date="15-05-2024",
        checked_date="15-05-2024",
        approved_date="15-05-2024",
        diagram="support_bracket",
        bom=(
            BOMItem("1", "HEX BOLT M10 x 25", "1", "MILD STEEL"),
            BOMItem("2", "SPRING WASHER \u00d810", "1", "MILD STEEL"),
            BOMItem("3", "SUPPORT BRACKET", "1", "CAST IRON"),
            BOMItem("4", "SPACER", "1", "MILD STEEL"),
            BOMItem("5", "BASE PLATE", "1", "MILD STEEL"),
            BOMItem("6", "HEX NUT M10", "1", "MILD STEEL"),
        ),
    ),
    DrawingDefinition(
        drawing_number="FCA-002",
        title="FLANGE COUPLING ASSEMBLY",
        revision="A",
        scale="1:2",
        drawn_date="16-05-2024",
        checked_date="16-05-2024",
        approved_date="16-05-2024",
        diagram="flange_coupling",
        bom=(
            BOMItem("1", "HEX BOLT M10 x 30", "6", "MILD STEEL"),
            BOMItem("2", "SPRING WASHER \u00d810", "6", "MILD STEEL"),
            BOMItem("3", "HUB (LEFT)", "1", "CAST IRON"),
            BOMItem("4", "SPIDER INSERT", "1", "POLYURETHANE"),
            BOMItem("5", "HUB (RIGHT)", "1", "CAST IRON"),
            BOMItem("6", "PLAIN WASHER \u00d810", "6", "MILD STEEL"),
            BOMItem("7", "HEX BOLT M10 x 30", "6", "MILD STEEL"),
            BOMItem("8", "PLAIN WASHER \u00d810", "6", "MILD STEEL"),
        ),
    ),
    DrawingDefinition(
        drawing_number="PBA-003",
        title="PILLOW BLOCK BEARING ASSEMBLY",
        revision="A",
        scale="1:2",
        drawn_date="17-05-2024",
        checked_date="18-05-2024",
        approved_date="17-05-2024",
        diagram="pillow_block",
        bom=(
            BOMItem("1", "HEX BOLT M10 x 30", "2", "MILD STEEL"),
            BOMItem("2", "SPRING WASHER \u00d810", "2", "MILD STEEL"),
            BOMItem("3", "BEARING CAP", "1", "CAST IRON"),
            BOMItem("4", "BALL BEARING 6205", "1", "BEARING STEEL"),
            BOMItem("5", "HOUSING", "1", "CAST IRON"),
            BOMItem("6", "PLAIN WASHER \u00d810", "2", "MILD STEEL"),
            BOMItem("7", "DOWEL PIN \u00d810 x 20", "2", "MILD STEEL"),
        ),
    ),
    DrawingDefinition(
        drawing_number="LPA-004",
        title="LEVER PRESS ASSEMBLY",
        revision="A",
        scale="1:2",
        drawn_date="18-05-2024",
        checked_date="18-05-2024",
        approved_date="18-05-2024",
        diagram="lever_press",
        bom=(
            BOMItem("1", "HANDLE GRIP", "1", "RUBBER"),
            BOMItem("2", "LEVER", "1", "MILD STEEL"),
            BOMItem("3", "CONNECTING LINK", "1", "MILD STEEL"),
            BOMItem("4", "PIN \u00d812 x 30", "1", "MILD STEEL"),
            BOMItem("5", "RAM", "1", "EN8"),
            BOMItem("6", "RETURN SPRING", "1", "SPRING STEEL"),
            BOMItem("7", "BASE", "1", "CAST IRON"),
            BOMItem("8", "HEX BOLT M10 x 30", "4", "MILD STEEL"),
        ),
    ),
    DrawingDefinition(
        drawing_number="VA-005",
        title="VALVE ASSEMBLY",
        revision="A",
        scale="1:2",
        drawn_date="18-05-2024",
        checked_date="19-05-2024",
        approved_date="19-05-2024",
        diagram="valve",
        bom=(
            BOMItem("1", "HANDWHEEL", "1", "CAST IRON"),
            BOMItem("2", "LOCK NUT M12", "1", "MILD STEEL"),
            BOMItem("3", "STEM", "1", "STAINLESS STEEL"),
            BOMItem("4", "GLAND", "1", "BRASS"),
            BOMItem("5", "BONNET", "1", "CAST IRON"),
            BOMItem("6", "PACKING", "1", "PTFE"),
            BOMItem("7", "BODY", "1", "CAST IRON"),
            BOMItem("8", "HEX BOLT M10 x 30", "4", "MILD STEEL"),
        ),
    ),
)


def generate(output_root: Path) -> None:
    pdf_directory = output_root / "data" / "sample_drawings"
    truth_directory = output_root / "data" / "ground_truth"
    pdf_directory.mkdir(parents=True, exist_ok=True)
    truth_directory.mkdir(parents=True, exist_ok=True)

    for definition in DRAWINGS:
        pdf_path = pdf_directory / f"{definition.drawing_number}.pdf"
        _draw_pdf(pdf_path, definition)
        truth = _ground_truth(definition, pdf_path.name)
        truth_path = truth_directory / f"{definition.drawing_number}.json"
        truth_path.write_text(
            json.dumps(truth, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _draw_pdf(path: Path, definition: DrawingDefinition) -> None:
    width, height = landscape(A3)
    canvas = Canvas(str(path), pagesize=(width, height), pageCompression=1)
    canvas.setTitle(definition.title)
    canvas.setAuthor("MECHTECH ENGINEERING PVT. LTD.")
    canvas.setLineWidth(0.8)
    canvas.rect(10, 10, width - 20, height - 20)

    _draw_diagram(canvas, definition.diagram, width, height)
    _draw_bom(canvas, definition, width, height)
    _draw_notes(canvas, definition, width, height)
    _draw_title_block(canvas, definition, width)

    canvas.showPage()
    canvas.save()


def _draw_bom(
    canvas: Canvas,
    definition: DrawingDefinition,
    page_width: float,
    page_height: float,
) -> None:
    x = page_width - 440
    top = page_height - 42
    widths = (62, 175, 48, 92, 53)
    row_height = 27
    headers = ("ITEM NO.", "PART NAME", "QTY.", "MATERIAL", "REMARKS")
    rows = (headers,) + tuple(
        (
            item.item_number,
            item.part_name,
            item.quantity,
            item.material,
            item.remarks,
        )
        for item in definition.bom
    )

    canvas.setFont("Helvetica", 7)
    for row_index, row in enumerate(rows):
        y = top - (row_index + 1) * row_height
        current_x = x
        for column_index, value in enumerate(row):
            cell_width = widths[column_index]
            canvas.rect(current_x, y, cell_width, row_height)
            font = "Helvetica-Bold" if row_index == 0 else "Helvetica"
            canvas.setFont(font, 7)
            _center_text(canvas, value, current_x, y + 9, cell_width)
            current_x += cell_width


def _draw_title_block(canvas: Canvas, definition: DrawingDefinition, width: float) -> None:
    bottom = 10
    lower_height = 70
    upper_height = 60
    upper_y = bottom + lower_height
    canvas.line(10, upper_y, width - 10, upper_y)
    canvas.line(10, upper_y + upper_height, width - 10, upper_y + upper_height)

    upper_cells = (
        (10, 290, "MECHTECH ENGINEERING PVT. LTD.", "BENGALURU - INDIA"),
        (300, 490, "TITLE:", definition.title),
        (790, 245, "DRAWING NO.:", definition.drawing_number),
        (1035, width - 1045, "REV.:", definition.revision),
    )
    for x, cell_width, label, value in upper_cells:
        canvas.line(x, upper_y, x, upper_y + upper_height)
        _label_value(canvas, label, value, x, upper_y, cell_width, upper_height)
    canvas.line(width - 10, upper_y, width - 10, upper_y + upper_height)

    lower_cells = (
        (10, 150, "MATERIAL:", "AS PER BOM"),
        (160, 140, "FINISH:", "PAINTED"),
        (300, 180, "DRAWN BY:", f"R. KUMAR\n{definition.drawn_date}"),
        (480, 180, "CHECKED BY:", f"S. NAIR\n{definition.checked_date}"),
        (660, 180, "APPROVED BY:", f"P. MENON\n{definition.approved_date}"),
        (840, 90, "SCALE:", definition.scale),
        (930, 80, "SHEET:", "1 OF 1"),
        (1010, 70, "UNIT:", "MM"),
        (1080, width - 1090, "PROJECTION:", "FIRST ANGLE"),
    )
    for x, cell_width, label, value in lower_cells:
        canvas.line(x, bottom, x, upper_y)
        _label_value(canvas, label, value, x, bottom, cell_width, lower_height)
    canvas.line(width - 10, bottom, width - 10, upper_y)


def _label_value(
    canvas: Canvas,
    label: str,
    value: str,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    canvas.setFont("Helvetica-Bold", 7)
    canvas.drawString(x + 7, y + height - 14, label)
    lines = value.splitlines()
    canvas.setFont("Helvetica", 9)
    start_y = y + 25 + (len(lines) - 1) * 9
    for index, line in enumerate(lines):
        _center_text(canvas, line, x, start_y - index * 14, width)


def _draw_notes(
    canvas: Canvas,
    definition: DrawingDefinition,
    page_width: float,
    page_height: float,
) -> None:
    x = page_width - 425
    y = page_height - 340
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(x, y, "NOTES:")
    canvas.setFont("Helvetica", 8)
    notes = (
        "1. ALL DIMENSIONS ARE IN MM",
        "2. DEBURR AND BREAK ALL SHARP EDGES",
        "3. GENERAL TOLERANCE: +/-0.1 mm",
        f"4. ASSEMBLY REFERENCE: {definition.drawing_number}",
    )
    for index, note in enumerate(notes):
        canvas.drawString(x, y - 20 - index * 18, note)


def _draw_diagram(canvas: Canvas, diagram: str, width: float, height: float) -> None:
    drawers: dict[str, Callable[[Canvas, float, float], None]] = {
        "support_bracket": _support_bracket,
        "flange_coupling": _flange_coupling,
        "pillow_block": _pillow_block,
        "lever_press": _lever_press,
        "valve": _valve,
    }
    drawers[diagram](canvas, width, height)


def _support_bracket(canvas: Canvas, width: float, height: float) -> None:
    canvas.rect(245, 300, 280, 55)
    canvas.rect(345, 355, 80, 235)
    canvas.circle(385, 535, 28)
    for x in (275, 495):
        canvas.circle(x, 327, 12)
    _dimension(canvas, 245, 275, 525, "90")
    _balloons(canvas, 6, 70, height - 120)


def _flange_coupling(canvas: Canvas, width: float, height: float) -> None:
    canvas.circle(370, 470, 125)
    canvas.circle(370, 470, 58)
    for angle_point in ((370, 560), (460, 470), (370, 380), (280, 470)):
        canvas.circle(*angle_point, 12)
    canvas.rect(270, 275, 200, 80)
    canvas.line(370, 250, 370, 590)
    _dimension(canvas, 245, 620, 495, "DIA 110")
    _balloons(canvas, 8, 70, height - 100)


def _pillow_block(canvas: Canvas, width: float, height: float) -> None:
    canvas.rect(230, 300, 330, 55)
    canvas.rect(285, 355, 220, 155)
    canvas.circle(395, 430, 75)
    canvas.circle(395, 430, 42)
    for x in (265, 525):
        canvas.circle(x, 327, 12)
    _dimension(canvas, 230, 270, 560, "150")
    _balloons(canvas, 7, 70, height - 110)


def _lever_press(canvas: Canvas, width: float, height: float) -> None:
    canvas.rect(250, 280, 240, 55)
    canvas.rect(335, 335, 65, 250)
    canvas.rect(310, 520, 120, 70)
    canvas.line(370, 575, 215, 690)
    canvas.setLineWidth(8)
    canvas.line(215, 690, 130, 750)
    canvas.setLineWidth(0.8)
    canvas.rect(420, 375, 55, 135)
    _dimension(canvas, 510, 335, 510, "280", vertical=True)
    _balloons(canvas, 8, 70, height - 90)


def _valve(canvas: Canvas, width: float, height: float) -> None:
    canvas.circle(380, 680, 70)
    canvas.circle(380, 680, 15)
    canvas.rect(365, 405, 30, 275)
    canvas.rect(300, 365, 160, 75)
    canvas.circle(270, 400, 55)
    canvas.circle(490, 400, 55)
    canvas.rect(250, 365, 260, 70)
    canvas.circle(380, 400, 75)
    _dimension(canvas, 535, 365, 535, "190", vertical=True)
    _balloons(canvas, 8, 70, height - 90)


def _dimension(
    canvas: Canvas,
    x1: float,
    y1: float,
    x2: float,
    label: str,
    *,
    vertical: bool = False,
) -> None:
    if vertical:
        canvas.line(x1, y1, x1, y1 + 240)
        canvas.drawString(x1 + 8, y1 + 115, label)
    else:
        canvas.line(x1, y1, x2, y1)
        _center_text(canvas, label, x1, y1 + 7, x2 - x1)


def _balloons(canvas: Canvas, count: int, x: float, start_y: float) -> None:
    canvas.setFont("Helvetica", 8)
    for index in range(count):
        y = start_y - index * 55
        canvas.circle(x, y, 12)
        _center_text(canvas, str(index + 1), x - 12, y - 3, 24)
        canvas.line(x + 12, y, x + 80, y - 8)


def _center_text(canvas: Canvas, text: str, x: float, y: float, width: float) -> None:
    text_width = canvas.stringWidth(text, canvas._fontname, canvas._fontsize)
    canvas.drawString(x + max(3, (width - text_width) / 2), y, text)


def _ground_truth(definition: DrawingDefinition, source_file: str) -> dict[str, object]:
    material_totals: dict[str, float] = {}
    source_rows: dict[str, list[int]] = {}
    for row_number, item in enumerate(definition.bom, start=1):
        material_totals[item.material] = material_totals.get(item.material, 0) + float(
            item.quantity
        )
        source_rows.setdefault(item.material, []).append(row_number)

    return {
        "source_file": source_file,
        "title_block": {
            "drawing_number": definition.drawing_number,
            "drawing_title": definition.title,
            "revision": definition.revision,
            "material": "AS PER BOM",
            "scale": definition.scale,
            "drawn_by": "R. KUMAR",
            "checked_by": "S. NAIR",
            "approved_by": "P. MENON",
            "drawing_date": definition.drawn_date,
        },
        "bom": [asdict(item) for item in definition.bom],
        "raw_material_list": [
            {
                "material": material,
                "quantity": quantity,
                "source_bom_rows": source_rows[material],
            }
            for material, quantity in sorted(material_totals.items())
        ],
    }


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1])
