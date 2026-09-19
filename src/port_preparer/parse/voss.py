"""Parsers for individual VOSS `show` commands.

Every parser is tolerant by design: a line it does not recognise is skipped and counted, not
fatal. A collection that half-worked must still produce a report that says which half.

Each parser returns plain dicts/lists; assembling them into a `DeviceState` is `discover.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .tables import Section, sections, slice_wrapped

# --- binding notation --------------------------------------------------------------
# `show i-sid` prints bindings as `c<vid>:<interface>`, or `u:<interface>` for untagged.
_BINDING_RE = re.compile(r"^(?:c(?P<cvid>\d+)|u):(?P<iface>\S+)$")


def parse_binding_list(cell: str) -> list[tuple[str, int | None]]:
    """`'c100:1/10,c100:1/11'` -> `[('1/10', 100), ('1/11', 100)]`. `u:` gives `None`."""
    out: list[tuple[str, int | None]] = []
    if not cell or cell.strip() in {"-", "--", "NONE"}:
        return out
    for token in cell.split(","):
        match = _BINDING_RE.match(token.strip())
        if match is None:
            continue
        cvid = match["cvid"]
        out.append((match["iface"], int(cvid) if cvid is not None else None))
    return out


@dataclass
class ParseResult:
    """Rows a parser understood, plus the lines it did not."""

    rows: list[dict] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rows)


def _scan(section: Section | None, pattern: re.Pattern[str], build) -> ParseResult:
    result = ParseResult()
    if section is None:
        return result
    for row in section.rows:
        match = pattern.match(row)
        if match is None:
            result.skipped.append(row)
            continue
        result.rows.append(build(match))
    return result


def _pick(text: str, *needles: str) -> Section | None:
    for section in sections(text):
        if section.mentions(*needles):
            return section
    return None


# --- show vlan basic ---------------------------------------------------------------

_VLAN_BASIC = re.compile(
    r"^(?P<vid>\d+)\s+(?P<name>\S+)\s+(?P<type>\S+)\s+(?P<inst>\d+)\s+\S+\s+\S+\s+\S+\s+(?P<vrf>\d+)\s+(?P<origin>\S+)\s*$"
)


def parse_vlan_basic(text: str) -> ParseResult:
    return _scan(
        _pick(text, "VLAN", "MSTP"),
        _VLAN_BASIC,
        lambda m: {
            "vid": int(m["vid"]),
            "name": m["name"],
            "vlan_type": m["type"],
            "mstp_instance": int(m["inst"]),
            "vrf_id": int(m["vrf"]),
            "origin": m["origin"],
        },
    )


# --- show vlan i-sid ---------------------------------------------------------------

_VLAN_ISID = re.compile(r"^(?P<vid>\d+)(?:\s+(?P<isid>\d+)(?:\s+(?P<name>\S.*?))?)?\s*$")


def parse_vlan_i_sid(text: str) -> ParseResult:
    return _scan(
        _pick(text, "VLAN_ID", "I-SID"),
        _VLAN_ISID,
        lambda m: {
            "vid": int(m["vid"]),
            "i_sid": int(m["isid"]) if m["isid"] else None,
            "i_sid_name": (m["name"] or "").strip() or None,
        },
    )


# --- show vlan members -------------------------------------------------------------
# Column-sliced, because rows wrap on 9.x with channelized sub-ports.


def parse_vlan_members(text: str) -> ParseResult:
    result = ParseResult()
    section = _pick(text, "VLAN", "PORT", "MEMBER")
    if section is None:
        return result
    for cells in slice_wrapped(section):
        if not cells or not cells[0].isdigit():
            result.skipped.append(" ".join(cells))
            continue
        padded = cells + [""] * (4 - len(cells))
        result.rows.append(
            {
                "vid": int(padded[0]),
                "port_members": padded[1],
                "active_members": padded[2],
                "static_members": padded[3],
            }
        )
    return result


# --- show i-sid --------------------------------------------------------------------

_ISID = re.compile(
    r"^(?P<isid>\d+)\s+(?P<type>\S+)\s+(?P<ports>\S+)\s+(?P<mlts>\S+)\s+(?P<origin>\S+)\s*(?P<name>.*)$"
)


def parse_i_sid(text: str) -> ParseResult:
    """`show i-sid`. The TYPE column is how we detect the UNI model (decision 0003)."""
    return _scan(
        _pick(text, "ISID", "TYPE"),
        _ISID,
        lambda m: {
            "i_sid": int(m["isid"]),
            "type": m["type"].upper(),
            "port_bindings": parse_binding_list(m["ports"]),
            "mlt_bindings": parse_binding_list(m["mlts"]),
            "origin": m["origin"],
            "name": (m["name"] or "").strip() or None,
        },
    )


# --- show interfaces gigabitethernet i-sid -----------------------------------------
# The ORIGIN column is a flag field containing spaces (`C  ---  -  ---  -  -  --`), so the
# tail is matched on the MAC-SUNI boolean and the middle split on runs of whitespace.

_PORT_ISID = re.compile(
    r"^(?P<port>\S+)\s+(?P<ifindex>\d+)\s+(?P<isid>\d+)\s+(?P<vlan>\S+)\s+(?P<cvid>\S+)\s+"
    r"(?P<type>\S+)\s+(?P<tail>.*?)\s+(?P<suni>TRUE|FALSE)\s*$",
    re.IGNORECASE,
)
_FLAGS_ONLY = re.compile(r"^[-C\s]*$", re.IGNORECASE)


def _split_origin_and_name(tail: str) -> tuple[str, str | None]:
    chunks = [c for c in re.split(r"\s{2,}", tail.strip()) if c]
    if not chunks:
        return "", None
    if len(chunks) == 1:
        return ("", chunks[0]) if not _FLAGS_ONLY.match(chunks[0]) else (chunks[0], None)
    if _FLAGS_ONLY.match(chunks[-1]):
        return " ".join(chunks), None
    return " ".join(chunks[:-1]), chunks[-1]


def parse_port_i_sid(text: str) -> ParseResult:
    def build(match: re.Match[str]) -> dict:
        origin, name = _split_origin_and_name(match["tail"])
        cvid = match["cvid"]
        vlan = match["vlan"]
        return {
            "port_id": match["port"],
            "i_sid": int(match["isid"]),
            "vlan_id": int(vlan) if vlan.isdigit() else None,
            "c_vid": int(cvid) if cvid.isdigit() else None,
            "type": match["type"].upper(),
            "origin": origin,
            "i_sid_name": name,
            "mac_suni": match["suni"].upper() == "TRUE",
        }

    return _scan(_pick(text, "PORTNUM", "ISID"), _PORT_ISID, build)


# --- show interfaces gigabitethernet [interface] -----------------------------------

_PORT_IFACE = re.compile(
    r"^(?P<port>\S+)\s+(?P<ifindex>\d+)\s+(?P<descr>\S+)\s+(?P<trap>true|false)\s+"
    r"(?P<lock>true|false)\s+(?P<mtu>\d+)\s+(?P<mac>[0-9a-fA-F:]{11,})\s+(?P<admin>\S+)\s+(?P<oper>\S+)\s*$",
    re.IGNORECASE,
)


def parse_port_interface(text: str) -> ParseResult:
    return _scan(
        _pick(text, "INDEX", "ADDRESS"),
        _PORT_IFACE,
        lambda m: {
            "port_id": m["port"],
            "transceiver": m["descr"],
            "mtu": int(m["mtu"]),
            "mac": m["mac"].lower(),
            "admin": m["admin"].lower(),
            "oper": m["oper"].lower(),
        },
    )


_PORT_NAME_7 = re.compile(
    r"^(?P<port>\S+)\s+(?P<name>\S+)\s+(?P<descr>\S+)\s+(?P<trap>true|false)\s+"
    r"(?P<status>\S+)\s+(?P<duplex>\S+)\s+(?P<speed>\d+)\s*$",
    re.IGNORECASE,
)
_PORT_NAME_6 = re.compile(
    r"^(?P<port>\S+)\s+(?P<descr>\S+)\s+(?P<trap>true|false)\s+"
    r"(?P<status>\S+)\s+(?P<duplex>\S+)\s+(?P<speed>\d+)\s*$",
    re.IGNORECASE,
)


def parse_port_name(text: str) -> ParseResult:
    """The `Port Name` section. NAME is absent on ports that have none, so the six-field
    shape is tried second."""
    result = ParseResult()
    section = _pick(text, "DUPLEX", "SPEED")
    if section is None:
        return result
    for row in section.rows:
        match = _PORT_NAME_7.match(row)
        if match is not None:
            result.rows.append(
                {
                    "port_id": match["port"],
                    "name": match["name"],
                    "transceiver": match["descr"],
                    "duplex": match["duplex"],
                    "speed": int(match["speed"]),
                }
            )
            continue
        match = _PORT_NAME_6.match(row)
        if match is not None:
            result.rows.append(
                {
                    "port_id": match["port"],
                    "name": None,
                    "transceiver": match["descr"],
                    "duplex": match["duplex"],
                    "speed": int(match["speed"]),
                }
            )
            continue
        result.skipped.append(row)
    return result


_PORT_CONFIG = re.compile(
    r"^(?P<port>\S+)\s+(?P<type>\S+)\s+(?P<diffserv>true|false)\s+(?P<dstype>\S+)\s+"
    r"(?P<qos>\d+)\s+(?P<mlt>\d+)\s*(?P<vendor>.*)$",
    re.IGNORECASE,
)


def parse_port_config(text: str) -> ParseResult:
    return _scan(
        _pick(text, "DIFF-SERV"),
        _PORT_CONFIG,
        lambda m: {
            "port_id": m["port"],
            "diffserv_enabled": m["diffserv"].lower() == "true",
            "diffserv_type": m["dstype"],
            "qos_level": int(m["qos"]),
            "mlt_id": int(m["mlt"]) or None,
        },
    )


# --- show mlt ----------------------------------------------------------------------
# Four sections. Section 1 and section 4 have colliding row shapes, so both are located by
# header keywords rather than by scanning the whole file.

_MLT_MAIN = re.compile(
    r"^(?P<id>\d+)\s+(?P<ifindex>\d+)\s+(?P<name>\S+)\s+(?P<ptype>\S+)\s+(?P<admin>\S+)\s+"
    r"(?P<current>\S+)\s+(?P<members>\S+)\s*(?P<vlans>.*)$"
)
_MLT_LACP = re.compile(
    r"^(?P<id>\d+)\s+(?P<ifindex>\d+)\s+(?P<designated>\S+)\s+(?P<admin>\S+)\s+(?P<oper>\S+)\s*$"
)
_MLT_ENCAP = re.compile(
    r"^(?P<id>\d+)\s+(?P<ifindex>\d+)\s+(?P<dot1q>\S+)\s+(?P<lossless>\S+)\s+(?P<pvlan>\S+)\s+"
    r"(?P<pvlantype>\S+)\s+(?P<vidtype>\S+)\s+(?P<flexuni>\S+)\s*$"
)


_ALL_NUMBERS = re.compile(r"^[\d\s]+$")


def _parse_mlt_main(section: Section | None) -> ParseResult:
    """Section 1 of `show mlt`, handling the wrapped VLAN IDS column.

    A long VLAN list continues on the next line, which in real output starts at column 0 and
    contains nothing but numbers -- so it cannot be recognised by indentation. It is
    identified by being unmatchable as a row while consisting only of digits, and its numbers
    belong to the MLT above it. Dropping it silently would under-report an MLT's VLANs, which
    is exactly the kind of quiet wrongness an audit must not have.
    """
    result = ParseResult()
    if section is None:
        return result
    for row in section.rows:
        match = _MLT_MAIN.match(row)
        if match is None:
            if result.rows and _ALL_NUMBERS.match(row) and row.strip():
                result.rows[-1]["vlan_ids"].extend(int(v) for v in row.split())
            else:
                result.skipped.append(row)
            continue
        result.rows.append(
            {
                "mlt_id": int(match["id"]),
                "name": match["name"],
                "port_type": match["ptype"].lower(),
                "smlt": match["admin"].lower() == "smlt" or match["current"].lower() == "smlt",
                "ports": match["members"],
                "vlan_ids": [int(v) for v in match["vlans"].split() if v.isdigit()],
            }
        )
    return result


def parse_mlt(text: str) -> ParseResult:
    """Merge the MLT sections into one row per MLT id."""
    result = ParseResult()
    merged: dict[int, dict] = {}

    main = _parse_mlt_main(_pick(text, "MLTID", "MLT", "MEMBERS"))
    for row in main.rows:
        merged[row["mlt_id"]] = row
    result.skipped.extend(main.skipped)

    lacp = _scan(_pick(text, "LACP", "DESIGNATED"), _MLT_LACP, lambda m: {
        "mlt_id": int(m["id"]),
        "lacp": m["admin"].lower() == "enable",
        "lacp_designated": m["designated"],
    })
    for row in lacp.rows:
        merged.setdefault(row["mlt_id"], {"mlt_id": row["mlt_id"]}).update(row)

    encap = _scan(_pick(text, "FLEX-UNI"), _MLT_ENCAP, lambda m: {
        "mlt_id": int(m["id"]),
        "dot1q": m["dot1q"].lower() == "enable",
        "flex_uni": m["flexuni"].lower() == "enable",
    })
    for row in encap.rows:
        merged.setdefault(row["mlt_id"], {"mlt_id": row["mlt_id"]}).update(row)

    result.rows = [merged[k] for k in sorted(merged)]
    return result


# --- show virtual-ist --------------------------------------------------------------

_VIST = re.compile(
    r"^(?P<peer>\d+\.\d+\.\d+\.\d+|[0-9a-fA-F:]+)\s+(?P<vlan>\d+)\s+(?P<enabled>true|false)\s+(?P<status>\S+)\s*$",
    re.IGNORECASE,
)


def parse_virtual_ist(text: str) -> ParseResult:
    return _scan(
        _pick(text, "PEER-IP"),
        _VIST,
        lambda m: {
            "peer_ip": m["peer"],
            "vlan_id": int(m["vlan"]),
            "enabled": m["enabled"].lower() == "true",
            "status": m["status"].lower(),
        },
    )


# --- show dvr interfaces -----------------------------------------------------------

_DVR = re.compile(
    r"^(?P<iface>\d+\.\d+\.\d+\.\d+)\s+(?P<mask>\S+)\s+(?P<l3isid>\d+)\s+(?P<vrf>\d+)\s+"
    r"(?P<l2isid>\d+)\s+(?P<vlan>\d+)\s+(?P<gw>\S+)\s+(?P<admin>\S+)\s+(?P<spbmc>\S+)\s+(?P<igmp>\d+)\s*$"
)


def parse_dvr_interfaces(text: str) -> ParseResult:
    return _scan(
        _pick(text, "L2ISID"),
        _DVR,
        lambda m: {
            "interface": m["iface"],
            "mask": m["mask"],
            "l3_i_sid": int(m["l3isid"]) or None,
            "vrf_id": int(m["vrf"]),
            "l2_i_sid": int(m["l2isid"]),
            "vlan_id": int(m["vlan"]),
            "gateway": m["gw"],
            "admin_state": m["admin"],
        },
    )


# --- show lldp neighbor summary ----------------------------------------------------
# Column-sliced: REMOTE PORT and SYSDESCR both contain spaces, and SYSNAME can be empty.


def parse_lldp_neighbor_summary(text: str) -> ParseResult:
    result = ParseResult()
    section = _pick(text, "SYSNAME")
    if section is None:
        return result
    for cells in slice_wrapped(section):
        if not cells or "/" not in cells[0]:
            result.skipped.append(" ".join(cells))
            continue
        padded = cells + [""] * (7 - len(cells))
        result.rows.append(
            {
                "port_id": padded[0],
                "protocol": padded[1] or None,
                "mgmt_address": padded[2] or None,
                "chassis_id": (padded[3] if padded[3] not in {"--", "-"} else None) or None,
                "remote_port": padded[4] or None,
                "sysname": padded[5] or None,
                "sysdescr": padded[6] or None,
            }
        )
    return result
