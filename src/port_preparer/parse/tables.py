"""Generic VOSS table handling.

VOSS `show` output is a banner, then one or more sections, each being header line(s), a long
dashed rule, rows, and sometimes a footer like `All 8 out of 8 Total Num of mlt displayed`.

Two strategies are used by the callers:

* **Row regex** — tolerant of column widths shifting between releases, which they do. Used
  wherever every field is whitespace-free.
* **Column slicing** — needed wherever a field contains spaces or a row *wraps* onto a
  continuation line, which `show vlan members` does on 9.x with channelized ports. Column
  offsets are taken from the header, so the parser follows the release's own widths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DASH = re.compile(r"^-{10,}\s*$")
_EQUALS = re.compile(r"^={10,}\s*$")
_STARS = re.compile(r"^\*{10,}\s*$")
_FOOTER = re.compile(
    r"^\s*(all\s+)?\d+\s+out\s+of\s+\d+|^\s*total\s+num|^\s*total\s+\w+\s*:|^\s*[a-z]:\s*\w",
    re.IGNORECASE,
)
_NOISE = re.compile(
    r"command execution time|preparing to display|^\s*#", re.IGNORECASE
)


@dataclass
class Section:
    header_lines: list[str] = field(default_factory=list)
    rows: list[str] = field(default_factory=list)

    @property
    def header(self) -> str:
        return " ".join(self.header_lines).upper()

    def mentions(self, *needles: str) -> bool:
        """True if every needle appears in the header. Used to identify which section of a
        multi-section output we are looking at."""
        return all(n.upper() in self.header for n in needles)


def _is_structural(line: str) -> bool:
    return bool(
        _DASH.match(line)
        or _EQUALS.match(line)
        or _STARS.match(line)
        or _FOOTER.match(line)
        or _NOISE.search(line)
    )


def sections(text: str) -> list[Section]:
    """Split `show` output into sections keyed on the dashed rule under each header."""
    lines = text.splitlines()
    found: list[Section] = []
    index = 0
    while index < len(lines):
        if not _DASH.match(lines[index]):
            index += 1
            continue

        header_lines: list[str] = []
        back = index - 1
        while back >= 0:
            candidate = lines[back]
            if not candidate.strip() or _is_structural(candidate):
                break
            header_lines.append(candidate)
            back -= 1
        header_lines.reverse()

        rows: list[str] = []
        forward = index + 1
        while forward < len(lines):
            candidate = lines[forward]
            if not candidate.strip() or _is_structural(candidate):
                break
            rows.append(candidate.rstrip())
            forward += 1

        found.append(Section(header_lines=header_lines, rows=rows))
        index = max(forward, index + 1)
    return found


def columns_from_header(header_lines: list[str]) -> list[int]:
    """Column start offsets, taken as the union of token starts across all header lines.

    Multi-line headers in VOSS align their tokens, so the union is the column grid. Offsets
    within one character of each other are merged, because some releases are off by one.
    """
    starts: set[int] = set()
    for line in header_lines:
        for match in re.finditer(r"\S+", line):
            starts.add(match.start())
    merged: list[int] = []
    for start in sorted(starts):
        if merged and start - merged[-1] <= 1:
            continue
        merged.append(start)
    return merged


def slice_columns(row: str, offsets: list[int]) -> list[str]:
    """Cut a row at the given offsets and strip each cell."""
    cells: list[str] = []
    for position, start in enumerate(offsets):
        end = offsets[position + 1] if position + 1 < len(offsets) else len(row)
        cells.append(row[start:end].strip())
    return cells


def slice_wrapped(section: Section) -> list[list[str]]:
    """Column-slice a section, joining continuation lines into the row above.

    A continuation line is one whose first cell is empty -- that is how VOSS wraps a long
    member list. `1/1-1/16,1/17/1-` on one line and `1/18/4,2/1` on the next is a single
    value and must be concatenated *without* a separator, because the wrap happens
    mid-token.
    """
    offsets = columns_from_header(section.header_lines)
    if not offsets:
        return []
    out: list[list[str]] = []
    for row in section.rows:
        cells = slice_columns(row, offsets)
        if cells and not cells[0] and out:
            for position, extra in enumerate(cells):
                if extra:
                    out[-1][position] += extra
            continue
        out.append(cells)
    return out
