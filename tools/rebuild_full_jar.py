"""Rebuild the *complete* embedded jar from the central directory (54 774 entries).

The earlier streaming walk recovered only the first 12 666 local headers because
it stopped at the first byte-pattern mismatch. Driving extraction from the
central directory gives every entry, including `com/st/components/**` — the CLI
framework (CommandLineManager & friends) the app references.
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
EXE = Path(os.environ.get(
    "MXMCP_CUBEMX_ROOT",
    r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeMX")) / "STM32CubeMX.exe"
CD = json.loads((HERE / "analysis" / "cd_entries.json").read_text(encoding="utf-8"))
OUT = HERE / "_extract"
OUT.mkdir(exist_ok=True)

LOCAL = re.compile(rb"PK\x03\x04.{22}", re.S)
ANCHOR = b"META-INF/MANIFEST.MF"


def find_base(data: bytes) -> int:
    """Anchor on the first real file entry (its local_header offset is 39)."""
    for m in LOCAL.finditer(data, 0x1000, CD["cd_offset"]):
        pos = m.start()
        nlen = struct.unpack_from("<H", data, pos + 26)[0]
        if data[pos + 30:pos + 30 + nlen] == ANCHOR:
            return pos - 39
    raise SystemExit("archive base not found")


def main() -> int:
    data = EXE.read_bytes()
    entries = CD["entries"]
    base = find_base(data)
    print(f"archive base: 0x{base:X}; {len(entries)} CD entries")
    target = OUT / "cubemx_full.jar"
    ok = bad = 0
    bad_list = []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for e in entries:
            pos = base + e["local_header"]
            if data[pos:pos + 4] != b"PK\x03\x04":
                bad += 1
                bad_list.append(e["name"])
                continue
            nlen, elen = struct.unpack_from("<HH", data, pos + 26)
            start = pos + 30 + nlen + elen
            blob = data[start:start + e["csize"]]
            if e["method"] == 8:
                try:
                    raw = zlib.decompress(blob, -15)
                except Exception:
                    bad += 1
                    bad_list.append(e["name"])
                    continue
            else:
                raw = blob
            if e["usize"] and len(raw) != e["usize"]:
                bad += 1
                bad_list.append(f"{e['name']} size {len(raw)} != {e['usize']}")
                continue
            z.writestr(e["name"], raw)
            ok += 1
    print(f"wrote {target.name} ({target.stat().st_size:,} bytes) ok={ok} bad={bad}")
    if bad_list:
        (HERE / "analysis" / "cd_bad_entries.json").write_text(
            json.dumps(bad_list[:3000], indent=1), encoding="utf-8")
        print("bad sample:", bad_list[:6])
    return 0


if __name__ == "__main__":
    sys.exit(main())
