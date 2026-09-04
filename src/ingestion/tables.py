"""Table extraction from document text.

Detects pipe-delimited tables in PDF text, converts them to
structured format, and provides human-readable formatting.
"""

from __future__ import annotations

import re


def extract_tables_from_text(text: str) -> list[dict]:
    """Detect and extract pipe-delimited tables from text."""
    tables = []
    lines = text.split("\n")
    current_table: list[str] = []

    for line in lines:
        stripped = line.strip()
        pipe_count = stripped.count("|")
        if pipe_count >= 1:
            current_table.append(stripped)
        else:
            if len(current_table) >= 2:
                table = _parse_pipe_table(current_table)
                if table:
                    tables.append(table)
            current_table = []

    if len(current_table) >= 2:
        table = _parse_pipe_table(current_table)
        if table:
            tables.append(table)

    return tables


def _parse_pipe_table(lines: list[str]) -> dict | None:
    """Parse a list of pipe-delimited lines into headers + rows."""
    if len(lines) < 2:
        return None

    def split_row(line: str) -> list[str]:
        cells = [c.strip() for c in line.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        return cells

    headers = split_row(lines[0])
    if not headers:
        return None

    rows = []
    for line in lines[1:]:
        if re.match(r"^[\s\-|:]+$", line):
            continue
        cells = split_row(line)
        if cells:
            rows.append(cells)

    if not rows:
        return None

    return {"headers": headers, "rows": rows}


def format_table_as_text(table: dict) -> str:
    """Format a table dict as readable aligned text."""
    headers = table["headers"]
    rows = table["rows"]

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    def fmt_row(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            w = col_widths[i] if i < len(col_widths) else len(cell)
            parts.append(str(cell).ljust(w))
        return " | ".join(parts)

    lines = [fmt_row(headers)]
    lines.append("-" * len(lines[0]))
    for row in rows:
        lines.append(fmt_row(row))

    return "\n".join(lines)
