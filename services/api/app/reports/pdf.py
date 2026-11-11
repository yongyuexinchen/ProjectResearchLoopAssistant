from io import BytesIO
import html
import re
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from app.reports.architecture import STATIC_LIMITATION, call_resolution_label, records, report_navigation, source_location, split_architecture_chapter, text

FONT_NAME = "STSong-Light"
PAGE_MARGIN = 48
TITLE_SIZE = 16
BODY_SIZE = 10
TITLE_LEADING = 24
BODY_LEADING = 14


def render_markdown_pdf(title: str, markdown: str, *, architecture_diagrams: list[dict[str, Any]] | None = None) -> bytes:
    """Render saved report text and offline vector diagrams; never fetch a renderer."""

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(title)
    register_chinese_font()
    writer = _ReportCanvas(pdf)
    writer.paragraph(title, size=TITLE_SIZE, leading=TITLE_LEADING)
    body = split_architecture_chapter(markdown)[0] if architecture_diagrams else markdown
    for line in body.splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            writer.paragraph(heading, size=12, leading=19)
        else:
            writer.paragraph(line)
    if architecture_diagrams:
        writer.new_page()
        writer.paragraph("源码流程与架构图", size=TITLE_SIZE, leading=TITLE_LEADING)
        writer.paragraph("本节依据报告创建时保存的图快照绘制；后续重画或修改源码不改变此处内容。")
        writer.paragraph(STATIC_LIMITATION)
        for diagram in architecture_diagrams:
            writer.diagram(diagram)
    writer.footer()
    pdf.save()
    return buffer.getvalue()


class _ReportCanvas:
    def __init__(self, pdf: canvas.Canvas):
        self.pdf = pdf
        self.width, self.height = A4
        self.available_width = self.width - PAGE_MARGIN * 2
        self.y = self.height - PAGE_MARGIN
        self.page_number = 1

    def footer(self) -> None:
        self.pdf.setFillColor(HexColor("#64748B"))
        self.pdf.setFont(FONT_NAME, 8)
        self.pdf.drawRightString(self.width - PAGE_MARGIN, 25, f"{self.page_number}")
        self.pdf.setFillColor(HexColor("#172033"))

    def new_page(self) -> None:
        self.footer()
        self.pdf.showPage()
        self.page_number += 1
        self.y = self.height - PAGE_MARGIN

    def ensure(self, height: float) -> None:
        if self.y - height < PAGE_MARGIN:
            self.new_page()

    def wrap(self, value: Any, width: float, size: float) -> list[str]:
        lines, current = [], ""
        for character in text(value).replace("\r", " ").replace("\n", " "):
            if current and pdfmetrics.stringWidth(current + character, FONT_NAME, size) > width:
                lines.append(current)
                current = ""
            current += character
        return [*lines, current] if current or not lines else lines

    def paragraph(self, value: Any, *, size: float = BODY_SIZE, leading: float = BODY_LEADING) -> None:
        for line in self.wrap(value, self.available_width, size):
            self.ensure(leading)
            self.pdf.setFillColor(HexColor("#172033"))
            self.pdf.setFont(FONT_NAME, size)
            self.pdf.drawString(PAGE_MARGIN, self.y, line)
            self.y -= leading

    def card_lines(self, value: str, width: float) -> list[str]:
        # Only graph labels carry renderer markup. Source excerpts remain literal text.
        label = re.sub(r"<br\s*/?>", " ", html.unescape(value), flags=re.IGNORECASE)
        lines = self.wrap(label, width - 16, 8.5)
        return lines if len(lines) <= 6 else [*lines[:5], "（长标签已缩略，完整位置见函数导航）"]

    def box(self, x: float, top: float, width: float, height: float, lines: list[str]) -> None:
        self.pdf.setStrokeColor(HexColor("#94A3B8"))
        self.pdf.setFillColor(HexColor("#F1F5F9"))
        self.pdf.rect(x, top - height, width, height, fill=1, stroke=1)
        self.pdf.setFillColor(HexColor("#172033"))
        self.pdf.setFont(FONT_NAME, 8.5)
        for index, line in enumerate(lines):
            self.pdf.drawString(x + 8, top - 14 - index * 12, line)

    def diagram(self, diagram: dict[str, Any]) -> None:
        self.ensure(90)
        self.paragraph("")
        self.paragraph(diagram.get("title"), size=13, leading=21)
        self.paragraph(f"依据：{text(diagram.get('basis'))} · 图快照：{text(diagram.get('id'))}", size=8.5)
        graph = diagram.get("graph_json") if isinstance(diagram.get("graph_json"), dict) else {}
        for note in graph.get("notes", []) if isinstance(graph.get("notes"), list) else []:
            self.paragraph(note, size=9)
        nodes, edges = records(graph.get("nodes")), records(graph.get("edges"))
        by_id = {text(node.get("id")): node for node in nodes}
        if nodes:
            self.paragraph("节点索引", size=11, leading=19)
        for index, node in enumerate(nodes, 1):
            label = f"{index}. {text(node.get('label'))}"
            if node.get("path"):
                label += f" · {text(node['path'])}"
            if node.get("description"):
                label += f" · 说明：{text(node['description'])}"
            lines = self.card_lines(label, self.available_width)
            height = max(32, len(lines) * 12 + 14)
            self.ensure(height + 18)
            self.box(PAGE_MARGIN, self.y, self.available_width, height, lines)
            self.y -= height + 18
        if edges:
            self.paragraph("静态引用关系（箭头只表示已保存的连接）", size=11, leading=19)
        for edge in edges:
            left = by_id.get(text(edge.get("source")), {})
            right = by_id.get(text(edge.get("target")), {})
            box_width = (self.available_width - 42) / 2
            left_lines = self.card_lines(text(left.get("label") or edge.get("source")), box_width)
            right_lines = self.card_lines(text(right.get("label") or edge.get("target")), box_width)
            height = max(32, max(len(left_lines), len(right_lines)) * 12 + 14)
            self.ensure(height + 32)
            self.paragraph(f"调用/连接：{text(edge.get('label')) or '未记录调用行号'}", size=8.5)
            self.ensure(height + 12)
            x1, x2 = PAGE_MARGIN, PAGE_MARGIN + box_width + 42
            self.box(x1, self.y, box_width, height, left_lines)
            self.box(x2, self.y, box_width, height, right_lines)
            arrow_y = self.y - height / 2
            self.pdf.setStrokeColor(HexColor("#334155"))
            self.pdf.line(x1 + box_width + 4, arrow_y, x2 - 4, arrow_y)
            self.pdf.line(x2 - 9, arrow_y + 4, x2 - 4, arrow_y)
            self.pdf.line(x2 - 9, arrow_y - 4, x2 - 4, arrow_y)
            self.y -= height + 20
        details = graph.get("details")
        if isinstance(details, dict):
            self.source_details(details)

    def source_details(self, details: dict[str, Any]) -> None:
        self.paragraph("源码位置与语句导航", size=11, leading=19)
        files, functions, notice = report_navigation(details)
        if notice:
            self.paragraph(notice, size=9)
        for file in files:
            self.paragraph(
                f"{text(file.get('path'))} · {text(file.get('language'))} · SHA-256 {text(file.get('sha256'))} · "
                f"说明：{text(file.get('description') or '未记录')}",
                size=8,
            )
        for warning in details.get("warnings", []) if isinstance(details.get("warnings"), list) else []:
            self.paragraph(f"限制：{text(warning)}", size=9)
        functions_by_id = {text(function.get("id")): function for function in records(details.get("functions"))}
        for function in functions:
            self.ensure(45)
            self.paragraph(f"{text(function.get('qualified_name') or function.get('name'))} · {source_location(function)}", size=10, leading=17)
            if function.get("docstring"):
                self.paragraph(f"源码注释：{text(function['docstring'])}", size=9)
            for statement in records(function.get("statements")):
                self.paragraph(f"{text(statement.get('label') or statement.get('kind'))} · {source_location(statement, path=function.get('path'))} · {text(statement.get('excerpt'))}", size=8.5)
            for call in records(function.get("calls")):
                result = call_resolution_label(call, functions_by_id)
                self.paragraph(f"{text(call.get('expression'))} · {text(function.get('path'))}:L{text(call.get('line'))} · {result} · {text(call.get('reason'))}", size=8.5)


def register_chinese_font() -> None:
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
