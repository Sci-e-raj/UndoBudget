#!/usr/bin/env python3
"""Render the short, editable Markdown report to a two-page PDF.

Uses only the Python standard library. Run from the repository root:
python3 submission/render_report.py
"""

import re
import textwrap
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "UndoBudget_Report.md"
OUTPUT = HERE / "UndoBudget_Report.pdf"
WIDTH, HEIGHT = 595, 842  # A4, points.
LEFT, RIGHT, BOTTOM = 50, 50, 48


def clean(line):
    return line.replace("**", "").replace("`", "").strip()


def literal(value):
    value = value.replace("\\", "\\\\").replace("(", "\\(")
    return value.replace(")", "\\)")


class Page:
    def __init__(self):
        self.commands = []
        self.y = HEIGHT - 50

    def text(self, value, *, font="F1", size=10, leading=13, indent=0):
        if self.y - leading < BOTTOM:
            raise ValueError("report page overflow; shorten the source")
        self.commands.append(
            f"BT /{font} {size} Tf {LEFT + indent} {self.y} Td "
            f"({literal(value)}) Tj ET\n"
        )
        self.y -= leading

    def gap(self, points=5):
        self.y -= points


def render():
    lines = SOURCE.read_text(encoding="ascii").splitlines()
    pages = [Page()]
    page = pages[0]
    paragraph = []
    diagram = []
    in_diagram = False

    def flush_paragraph():
        nonlocal paragraph
        if not paragraph:
            return
        words = " ".join(clean(line) for line in paragraph)
        for line in textwrap.wrap(words, width=88, break_long_words=False):
            page.text(line)
        page.gap(4)
        paragraph = []

    for raw in lines + [""]:
        if raw.startswith("```"):
            flush_paragraph()
            if in_diagram:
                height = len(diagram) * 11 + 12
                if page.y - height < BOTTOM:
                    raise ValueError("diagram does not fit on page")
                page.commands.append(
                    f"0.94 g {LEFT - 5} {page.y - height + 3} "
                    f"{WIDTH - LEFT - RIGHT + 10} {height} re f 0 g\n"
                )
                page.gap(5)
                for line in diagram:
                    page.text(line, font="F3", size=8, leading=11, indent=3)
                page.gap(7)
                diagram = []
            in_diagram = not in_diagram
            continue
        if in_diagram:
            diagram.append(raw)
            continue
        if raw.startswith("## 3."):
            flush_paragraph()
            pages.append(Page())
            page = pages[-1]
        if raw.startswith("# "):
            flush_paragraph()
            page.text(clean(raw[2:]), font="F2", size=17, leading=25)
            page.gap(3)
        elif raw.startswith("## "):
            flush_paragraph()
            page.gap(5)
            page.text(clean(raw[3:]), font="F2", size=12, leading=18)
        elif raw.startswith("| "):
            flush_paragraph()
            if not re.fullmatch(r"[| :\-]+", raw):
                page.text(clean(raw), font="F3", size=8.5, leading=12)
        elif raw.strip() == "":
            flush_paragraph()
        else:
            paragraph.append(raw)

    if len(pages) != 2:
        raise ValueError(f"expected 2 report pages, got {len(pages)}")
    for number, item in enumerate(pages, 1):
        item.commands.append(
            f"BT /F1 8 Tf {WIDTH - RIGHT - 40} 25 Td "
            f"(Page {number} of 2) Tj ET\n"
        )

    # Minimal, standards-compliant PDF with three base-14 fonts.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [6 0 R 8 0 R] /Count 2 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
    for index, item in enumerate(pages):
        page_id = 6 + index * 2
        stream_id = page_id + 1
        objects.append(
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {WIDTH} {HEIGHT}] "
             f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
             f"/Contents {stream_id} 0 R >>").encode("ascii")
        )
        stream = "".join(item.commands).encode("ascii")
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") +
            stream + b"endstream"
        )

    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii"))
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
         f"startxref\n{xref}\n%%EOF\n").encode("ascii")
    )
    OUTPUT.write_bytes(data)
    print(f"Wrote {OUTPUT} ({len(pages)} A4 pages)")


if __name__ == "__main__":
    render()
