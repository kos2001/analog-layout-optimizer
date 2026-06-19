"""Verify virtuoso_bridge features WITHOUT a running Virtuoso/Spectre.

Exercises the bridge's offline-capable surfaces: pure SKILL builders, the PSF
parser, and — crucially — the VirtuosoClient TCP/protocol path against a fake
in-process daemon that speaks the bridge wire protocol.
"""

import json
import socket
import tempfile
import threading
from pathlib import Path

from virtuoso_bridge import ExecutionStatus, VirtuosoClient
from virtuoso_bridge.spectre.parsers import parse_spectre_psf_ascii
from virtuoso_bridge.virtuoso.layout.ops import layout_create_rect, layout_create_path
from virtuoso_bridge.virtuoso.schematic.ops import schematic_create_inst, schematic_create_wire

_STX, _NAK = "\x02", "\x15"

PSF_SAMPLE = (
    'HEADER\nPROPERTIES\nSWEEP\n"freq" 1\nTRACE\n"vout" "V"\nVALUE\n'
    '"freq" 1e3\n"vout" 100.0\n"freq" 1e6\n"vout" 70.7\n"freq" 1e9\n"vout" 0.1\nEND\n'
)


# --- pure SKILL builders ----------------------------------------------------
def test_layout_builders_emit_skill():
    assert layout_create_rect("M1", "drawing", 0, 0, 1, 0.5).startswith("dbCreateRect(")
    assert layout_create_path("M2", "drawing", [(0, 0), (1, 0)], 0.1).startswith("dbCreatePath(")


def test_schematic_builders_emit_skill():
    inst = schematic_create_inst('dbOpenCellViewByType("a" "b" "symbol")', "M0", 0, 0, "R0")
    assert "dbCreateInst(" in inst
    assert schematic_create_wire([(0, 0), (1, 0)]).startswith("schCreateWire(")


# --- PSF parser -------------------------------------------------------------
def test_psf_parser_reads_signals():
    p = Path(tempfile.mkdtemp()) / "out.tran.tran"
    p.write_text(PSF_SAMPLE)
    res = parse_spectre_psf_ascii(p)
    assert res.ok
    assert res.data["vout"] == [100.0, 70.7, 0.1]


# --- VirtuosoClient TCP path against a fake daemon --------------------------
class _FakeDaemon:
    def __init__(self):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(4)
        threading.Thread(target=self._serve, daemon=True).start()

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
                    reply = (_NAK + "boom") if "boom" in skill else _STX + str(eval(skill, {"__builtins__": {}}, {}))
                except Exception as e:  # noqa: BLE001
                    reply = _NAK + str(e)
                conn.sendall(reply.encode())

    def close(self):
        self.sock.close()


def test_client_roundtrip_via_fake_daemon():
    d = _FakeDaemon()
    try:
        c = VirtuosoClient.local(port=d.port)
        ok = c.execute_skill("1+2")
        assert ok.status is ExecutionStatus.SUCCESS and ok.output == "3"
        assert c.execute_skill("6*7").output == "42"
        bad = c.execute_skill("boom()")
        assert bad.status is ExecutionStatus.ERROR
    finally:
        d.close()


def test_client_no_daemon_returns_error_not_crash():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); dead = s.getsockname()[1]; s.close()
    r = VirtuosoClient.local(port=dead).execute_skill("1+1", timeout=2)
    assert r.status is ExecutionStatus.ERROR
