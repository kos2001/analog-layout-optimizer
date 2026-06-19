#!/usr/bin/env python3
"""Exercise virtuoso_bridge features WITHOUT a running Virtuoso/Spectre.

Run:  python verify_bridge.py

Covers the parts of the bridge that work offline:
  1. Layout SKILL builders  -> generate real dbCreate* SKILL strings
  2. Schematic SKILL builders -> generate schCreate* SKILL strings
  3. Spectre PSF parser      -> parse synthesized PSF ASCII into signals
  4. VirtuosoClient TCP path -> round-trip against a FAKE daemon (no Virtuoso)
  5. VirtuosoClient no-daemon -> graceful error (not a crash)
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
from pathlib import Path

from virtuoso_bridge import ExecutionStatus, VirtuosoClient
from virtuoso_bridge.spectre.parsers import parse_spectre_psf_ascii
from virtuoso_bridge.virtuoso.layout.ops import (
    layout_create_label, layout_create_param_inst, layout_create_path,
    layout_create_polygon, layout_create_rect, layout_create_simple_mosaic,
    layout_create_via_by_name,
)
from virtuoso_bridge.virtuoso.schematic.ops import (
    schematic_create_inst, schematic_create_pin, schematic_create_wire,
    schematic_create_wire_label,
)

_STX = "\x02"
_NAK = "\x15"

PSF_SAMPLE = """\
HEADER
PROPERTIES
SWEEP
"freq" 1
TRACE
"vout" "V"
VALUE
"freq" 1e3
"vout" 100.0
"freq" 1e6
"vout" 70.7
"freq" 1e9
"vout" 0.1
END
"""


def section(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def check_layout_builders():
    section("1. Layout SKILL builders (pure — no Virtuoso)")
    out = {
        "rect": layout_create_rect("M1", "drawing", 0, 0, 1, 0.5),
        "path": layout_create_path("M2", "drawing", [(0, 0), (1, 0), (1, 1)], 0.1),
        "polygon": layout_create_polygon("M1", "drawing", [(0, 0), (1, 0), (1, 1)]),
        "label": layout_create_label("M1", "drawing", 0.5, 0.5, "VDD", "centerCenter", "R0", "roman", 0.1),
        "param_inst": layout_create_param_inst("tsmcN28", "nch", "layout", "M0", 0, 0, "R0"),
        "via": layout_create_via_by_name("M1_M2", 0.5, 0.25),
        "mosaic": layout_create_simple_mosaic("tsmcN28", "nch", rows=2, cols=4, row_pitch=0.5, col_pitch=0.3),
    }
    for k, v in out.items():
        print(f"  {k:11}: {v[:90]}")
    ok = all(v.startswith(("dbCreate", "let(", "dbOpen")) or "dbCreate" in v for v in out.values())
    print(f"  -> {len(out)} builders produced SKILL: {'OK' if ok else 'CHECK'}")
    return ok


def check_schematic_builders():
    section("2. Schematic SKILL builders (pure — no Virtuoso)")
    out = {
        "inst": schematic_create_inst('dbOpenCellViewByType("analogLib" "nmos4" "symbol")', "M0", 0, 0, "R0"),
        "wire": schematic_create_wire([(0, 0), (1, 0)]),
        "pin": schematic_create_pin("VINP", 0, 0, "R0"),
        "wire_label": schematic_create_wire_label(0.5, 0, "net1", "lowerLeft", "R0"),
    }
    for k, v in out.items():
        print(f"  {k:11}: {v[:90]}")
    ok = all(isinstance(v, str) and v for v in out.values())
    print(f"  -> {len(out)} builders produced SKILL: {'OK' if ok else 'CHECK'}")
    return ok


def check_psf_parser():
    section("3. Spectre PSF parser (pure — no Spectre)")
    tmp = Path(tempfile.mkdtemp()) / "out.tran.tran"
    tmp.write_text(PSF_SAMPLE)
    res = parse_spectre_psf_ascii(tmp)
    data = getattr(res, "data", {}) or {}
    print(f"  status: {res.status}")
    print(f"  signals parsed: {list(data.keys())}")
    print(f"  vout samples: {data.get('vout')}")
    ok = res.ok and "vout" in data and len(data["vout"]) == 3
    print(f"  -> parsed PSF ASCII into signals: {'OK' if ok else 'CHECK'}")
    return ok


class _FakeDaemon:
    """Minimal stand-in for the in-Virtuoso RAMIC daemon: speaks the bridge
    wire protocol (JSON request -> STX/NAK-framed reply) and 'evaluates' simple
    arithmetic, so the full TCP+protocol path is exercised without Virtuoso."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(4)
        self.t = threading.Thread(target=self._serve, daemon=True)
        self.t.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                buf = b""
                while True:
                    ch = conn.recv(4096)
                    if not ch:
                        break
                    buf += ch
                try:
                    skill = json.loads(buf.decode())["skill"]
                    if "boom" in skill:
                        reply = _NAK + "deliberate SKILL error"
                    else:
                        # stand in for evalstring on a simple arithmetic form
                        val = eval(skill, {"__builtins__": {}}, {})
                        reply = _STX + str(val)
                except Exception as e:  # noqa: BLE001
                    reply = _NAK + f"daemon error: {e}"
                conn.sendall(reply.encode())

    def close(self):
        self.sock.close()


def check_client_roundtrip():
    section("4. VirtuosoClient TCP round-trip via a FAKE daemon (no Virtuoso)")
    d = _FakeDaemon()
    try:
        client = VirtuosoClient.local(port=d.port)
        r1 = client.execute_skill("1+2")
        print(f"  execute_skill('1+2')  -> status={r1.status.name} output={r1.output!r}")
        r2 = client.execute_skill("6*7")
        print(f"  execute_skill('6*7')  -> status={r2.status.name} output={r2.output!r}")
        r3 = client.execute_skill("boom()")
        print(f"  execute_skill('boom') -> status={r3.status.name} errors={r3.errors}")
        ok = (r1.status is ExecutionStatus.SUCCESS and r1.output == "3"
              and r2.output == "42" and r3.status is ExecutionStatus.ERROR)
        print(f"  -> TCP + JSON request + STX/NAK framing verified: {'OK' if ok else 'CHECK'}")
        return ok
    finally:
        d.close()


def check_client_no_daemon():
    section("5. VirtuosoClient with no daemon -> graceful error (no crash)")
    # bind+close to get a definitely-closed port
    s = socket.socket(); s.bind(("127.0.0.1", 0)); dead = s.getsockname()[1]; s.close()
    r = VirtuosoClient.local(port=dead).execute_skill("1+1", timeout=2)
    print(f"  status={r.status.name} errors={r.errors}")
    ok = r.status is ExecutionStatus.ERROR
    print(f"  -> returned an ERROR result instead of crashing: {'OK' if ok else 'CHECK'}")
    return ok


def main() -> int:
    results = {
        "layout_builders": check_layout_builders(),
        "schematic_builders": check_schematic_builders(),
        "psf_parser": check_psf_parser(),
        "client_roundtrip": check_client_roundtrip(),
        "client_no_daemon": check_client_no_daemon(),
    }
    section("SUMMARY — virtuoso_bridge features verified WITHOUT Virtuoso")
    for k, v in results.items():
        print(f"  {'✓' if v else '✗'} {k}")
    print(f"\n  {sum(results.values())}/{len(results)} feature groups OK")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
