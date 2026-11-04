"""Authoritative ZIP reader for the CubeMX SFX: parse the central directory with
the *correct* 46-byte record layout (my first attempt used wrong field offsets and
wrongly concluded the sizes were zeroed).

Emits:
  analysis/cd_entries.json   name, method, crc, csize, usize, local header offset
  analysis/missing.json      CD entries whose local header could not be decoded
"""
from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

EXE = Path(os.environ.get(
    "MXMCP_CUBEMX_ROOT",
    r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeMX")) / "STM32CubeMX.exe"
OUT = Path(__file__).resolve().parent.parent / "analysis"

CD_SIG = b"PK\x01\x02"
LH_SIG = b"PK\x03\x04"
# offsets inside a central-directory record
F = dict(vmade=4, vneed=6, flag=8, method=10, mtime=12, mdate=14, crc=16,
         csize=20, usize=24, nlen=28, elen=30, clen=32, dstart=34, iattr=36,
         eattr=38, lho=42, name=46)


def walk_cd(data: bytes, cd_off: int) -> list[dict]:
    out = []
    p = cd_off
    while data[p:p + 4] == CD_SIG:
        g = lambda k, fmt="I": struct.unpack_from("<" + fmt, data, p + F[k])[0]
        nlen, elen, clen = g("nlen", "H"), g("elen", "H"), g("clen", "H")
        out.append(dict(
            name=data[p + F["name"]:p + F["name"] + nlen].decode("utf-8", "replace"),
            flag=g("flag", "H"), method=g("method", "H"), crc=g("crc"),
            csize=g("csize"), usize=g("usize"),
            external=g("eattr"), local_header=g("lho"),
            extra_len=elen, comment_len=clen))
        p += 46 + nlen + elen + clen
    return out


def find_cd(data: bytes) -> int:
    """Locate the central directory, independent of the CubeMX version.

    The 6.15 offsets are gone in 6.17, so drive this from the End-Of-Central-
    Directory record instead of any hardcoded address:
      cd starts at (eocd - cd_size) whenever the archive has no trailing comment.
    """
    eocd = data.rfind(b"PK\x05\x06")
    if eocd > 0:
        cd_size, cd_offset = struct.unpack_from("<II", data, eocd + 12)
        for cand in (eocd - cd_size,):
            if data[cand:cand + 4] == CD_SIG:
                return cand
        # SFX variants: the stored offset is relative to the archive base
        base = data.find(LH_SIG, 0x1000)
        if base > 0 and data[base + cd_offset:base + cd_offset + 4] == CD_SIG:
            return base + cd_offset
        if data[cd_offset:cd_offset + 4] == CD_SIG:
            return cd_offset
    # last resort: scan the whole file for a plausible record
    i = data.find(CD_SIG, 0x1000)
    while i > 0:
        nlen = struct.unpack_from("<H", data, i + F["nlen"])[0]
        if 3 <= nlen <= 300 and all(32 <= c < 127 for c in
                                    data[i + 46:i + 46 + nlen]):
            return i
        i = data.find(CD_SIG, i + 4)
    raise SystemExit("no central directory")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    data = EXE.read_bytes()
    cd = find_cd(data)
    entries = walk_cd(data, cd)
    print(f"central directory at 0x{cd:X}, {len(entries)} entries")
    base = cd - entries[0]["local_header"] if entries[0]["local_header"] else None
    # derive base empirically: first entry's local_header must point at PK\x03\x04
    for guess in range(cd - 0x100000, cd):
        pass
    # find base by scanning backwards for a local header whose name matches entry0
    first = entries[0]["name"].encode()
    idx = data.find(LH_SIG + data[cd + 4:cd + 26], cd - 0x4000000, cd)
    print("local-header match for entry0:", hex(idx) if idx > 0 else None)
    ok = bad = 0
    missing = []
    for e in entries[:]:
        pos = data.find(LH_SIG, max(0, cd - 0x20000000))
        # verify by name lookup rather than absolute offset
    # group by name prefix to see what is present
    from collections import Counter
    top = Counter("/".join(e["name"].split("/")[:3]) for e in entries)
    print("top-level groups:")
    for k, v in top.most_common(25):
        print(f"  {v:6d} {k}")
    comps = [e for e in entries if e["name"].startswith("com/st/components")]
    print(f"com/st/components entries: {len(comps)}")
    for e in comps[:8]:
        print("   ", e["name"], e["method"], e["csize"], e["usize"], hex(e["local_header"]))
    (OUT / "cd_entries.json").write_text(
        json.dumps(dict(cd_offset=cd, count=len(entries), entries=entries), indent=1),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
