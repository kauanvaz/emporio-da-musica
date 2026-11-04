from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import pymupdf4llm  # type: ignore[import-untyped]
from pymupdf.table import Table


class PolicyParsingError(RuntimeError):
    pass


_SECTION_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
_TABLE_PIPE_RE = re.compile(r"(?<!\\)\|")


@dataclass(frozen=True)
class _MarkdownTable:
    start_line: int
    end_line: int
    column_count: int


@dataclass(frozen=True)
class _PdfTable:
    page: pymupdf.Page
    table: Table
    page_number: int

    @property
    def column_count(self) -> int:
        return self.table.col_count


def parse_policy_manual(pdf_path: str | Path) -> str:
    path = Path(pdf_path)
    if not path.is_file():
        raise PolicyParsingError(f"Policy PDF not found at {path}.")

    try:
        document = pymupdf.open(str(path))
    except Exception as exc:
        raise PolicyParsingError(f"Could not open policy PDF at {path}.") from exc

    try:
        if document.page_count == 0:
            raise PolicyParsingError(f"Policy PDF at {path} has no pages.")

        try:
            markdown = pymupdf4llm.to_markdown(
                document,
                header=False,
                footer=False,
                use_ocr=False,
                write_images=False,
                page_chunks=False,
            )
        except Exception as exc:
            raise PolicyParsingError(
                f"Could not convert policy PDF at {path} to Markdown."
            ) from exc

        if not isinstance(markdown, str) or not markdown.strip():
            raise PolicyParsingError(
                f"Policy PDF at {path} did not produce Markdown text."
            )
        if not _SECTION_HEADING_RE.search(markdown):
            raise PolicyParsingError(
                f"Policy PDF at {path} did not produce any section headings."
            )

        pdf_tables = _find_pdf_tables(document)
        markdown_tables = _find_markdown_tables(markdown)
        if len(markdown_tables) != len(pdf_tables):
            raise PolicyParsingError(
                "Policy manual table validation failed: "
                f"Markdown has {len(markdown_tables)} table(s) but the PDF has "
                f"{len(pdf_tables)}."
            )

        lines = markdown.splitlines()
        replacements: list[tuple[_MarkdownTable, list[str]]] = []
        for markdown_table, pdf_table in zip(markdown_tables, pdf_tables):
            if markdown_table.column_count == pdf_table.column_count:
                continue
            replacements.append(
                (markdown_table, _rebuild_table_from_pdf(pdf_table)),
            )

        for markdown_table, replacement in reversed(replacements):
            lines[markdown_table.start_line : markdown_table.end_line + 1] = replacement

        return "\n".join(lines).strip() + "\n"
    finally:
        document.close()


def _find_pdf_tables(document: pymupdf.Document) -> list[_PdfTable]:
    tables: list[_PdfTable] = []
    for page_number in range(document.page_count):
        page = document.load_page(page_number)
        try:
            found_tables = page.find_tables().tables
        except Exception as exc:
            raise PolicyParsingError(
                f"Could not inspect tables on PDF page {page_number + 1}."
            ) from exc
        tables.extend(
            _PdfTable(page=page, table=table, page_number=page_number + 1)
            for table in found_tables
        )
    return tables


def _find_markdown_tables(markdown: str) -> list[_MarkdownTable]:
    lines = markdown.splitlines()
    tables: list[_MarkdownTable] = []
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue

        start_line = index
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            index += 1
        end_line = index - 1

        if end_line - start_line + 1 < 2:
            continue

        header_cells = _split_table_row(lines[start_line])
        separator_cells = _split_table_row(lines[start_line + 1])
        if len(header_cells) < 2 or not _is_table_separator(separator_cells):
            continue
        if len(header_cells) != len(separator_cells):
            raise PolicyParsingError(
                "Policy manual table validation failed: a Markdown table has "
                f"{len(header_cells)} header column(s) and "
                f"{len(separator_cells)} separator column(s)."
            )

        tables.append(
            _MarkdownTable(
                start_line=start_line,
                end_line=end_line,
                column_count=len(header_cells),
            )
        )

    return tables


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip().removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in _TABLE_PIPE_RE.split(stripped)]


def _is_table_separator(cells: list[str]) -> bool:
    return len(cells) >= 1 and all(
        _TABLE_SEPARATOR_CELL_RE.fullmatch(cell) is not None for cell in cells
    )


def _rebuild_table_from_pdf(pdf_table: _PdfTable) -> list[str]:
    column_count = pdf_table.column_count
    rows: list[list[str]] = []
    for row in pdf_table.table.rows:
        cell_rects = list(row.cells[:column_count])
        cell_rects.extend([None] * (column_count - len(cell_rects)))
        rows.append(
            [_extract_cell_text(pdf_table.page, rect) for rect in cell_rects],
        )

    if not rows or column_count == 0:
        return []

    header, *body = rows
    rendered = [
        _render_table_row(header),
        _render_table_row(["---"] * column_count),
    ]
    rendered.extend(_render_table_row(row) for row in body)
    return rendered


def _extract_cell_text(
    page: pymupdf.Page,
    rect: tuple[float, float, float, float] | None,
) -> str:
    if rect is None:
        return ""
    return " ".join(page.get_textbox(pymupdf.Rect(rect)).split())


def _render_table_row(cells: list[str]) -> str:
    escaped = [cell.replace("|", r"\|") for cell in cells]
    return f"| {' | '.join(escaped)} |"


__all__ = ["PolicyParsingError", "parse_policy_manual"]
