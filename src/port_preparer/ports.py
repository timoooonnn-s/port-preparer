"""Port identifier handling.

Port ids in this estate come in two *and three* part forms, and appear in configs as lists
and ranges: `1/45`, `2/1/1`, `1/1-1/48`, `1/17/1-1/18/4`, `1/1-1/2,1/23-1/24`.

Nothing here assumes `slot/port`. An id is a tuple of integers of length 2 or 3, and a range
is only expandable when its endpoints differ in exactly one position.
"""

from __future__ import annotations

import re

_ID_RE = re.compile(r"^\d+(?:/\d+){1,2}$")


class PortSpecError(ValueError):
    """A port specification could not be understood."""


def is_port_id(text: str) -> bool:
    return bool(_ID_RE.match(text.strip()))


def parts(port_id: str) -> tuple[int, ...]:
    if not is_port_id(port_id):
        raise PortSpecError(f"not a port id: {port_id!r}")
    return tuple(int(p) for p in port_id.strip().split("/"))


def normalise(port_id: str) -> str:
    """Canonical form, so `01/5` and `1/5` are the same key."""
    return "/".join(str(p) for p in parts(port_id))


def expand_range(text: str) -> list[str]:
    """Expand a single `a-b` range.

    >>> expand_range("1/1-1/4")
    ['1/1', '1/2', '1/3', '1/4']
    >>> expand_range("1/17/1-1/18/4")
    ['1/17/1', '1/17/2', '1/17/3', '1/17/4', '1/18/1', '1/18/2', '1/18/3', '1/18/4']
    """
    left, _, right = text.partition("-")
    start, end = parts(left), parts(right)
    if len(start) != len(end):
        raise PortSpecError(f"range endpoints have different shapes: {text!r}")

    differing = [i for i, (a, b) in enumerate(zip(start, end)) if a != b]
    if not differing:
        return [normalise(left)]

    if len(differing) == 1:
        index = differing[0]
        lo, hi = start[index], end[index]
        if hi < lo:
            raise PortSpecError(f"descending range: {text!r}")
        out = []
        for value in range(lo, hi + 1):
            item = list(start)
            item[index] = value
            out.append("/".join(str(p) for p in item))
        return out

    # Channelized case: 1/17/1-1/18/4 varies the sub-port *and* the port. Only valid for
    # three-part ids varying the last two positions, and only if we know the channel count,
    # which we take from the endpoints themselves.
    if len(start) == 3 and differing == [1, 2]:
        channels = end[2]
        if channels < start[2]:
            raise PortSpecError(f"cannot infer channel count from {text!r}")
        out = []
        for port in range(start[1], end[1] + 1):
            first = start[2] if port == start[1] else 1
            last = end[2] if port == end[1] else channels
            out.extend(f"{start[0]}/{port}/{ch}" for ch in range(first, last + 1))
        return out

    raise PortSpecError(f"cannot expand a range varying {len(differing)} positions: {text!r}")


def expand(spec: str) -> list[str]:
    """Expand a comma-separated port specification into individual ids.

    >>> expand("1/1-1/2,1/23,2/1/1")
    ['1/1', '1/2', '1/23', '2/1/1']
    """
    out: list[str] = []
    for token in spec.replace(" ", "").split(","):
        if not token:
            continue
        if token in {"NONE", "-", "--"}:
            continue
        out.extend(expand_range(token) if "-" in token else [normalise(token)])
    return out


def expand_tolerant(spec: str) -> tuple[list[str], list[str]]:
    """Like `expand`, but returns `(ids, unparsed_tokens)` instead of raising.

    Used when reading a device: an id shape we do not understand must not abort a whole
    collection, it must be reported.
    """
    ids: list[str] = []
    bad: list[str] = []
    for token in spec.replace(" ", "").split(","):
        if not token or token in {"NONE", "-", "--"}:
            continue
        try:
            ids.extend(expand_range(token) if "-" in token else [normalise(token)])
        except PortSpecError:
            bad.append(token)
    return ids, bad


def compress(port_ids: list[str]) -> str:
    """Render ids back to VOSS's comma-and-range form, for generated config.

    >>> compress(["1/1", "1/2", "1/3", "1/23"])
    '1/1-1/3,1/23'
    """
    if not port_ids:
        return ""
    ordered = sorted({normalise(p) for p in port_ids}, key=parts)
    groups: list[list[str]] = [[ordered[0]]]
    for current in ordered[1:]:
        previous = parts(groups[-1][-1])
        this = parts(current)
        contiguous = (
            len(previous) == len(this)
            and previous[:-1] == this[:-1]
            and this[-1] == previous[-1] + 1
        )
        if contiguous:
            groups[-1].append(current)
        else:
            groups.append([current])
    return ",".join(g[0] if len(g) == 1 else f"{g[0]}-{g[-1]}" for g in groups)
