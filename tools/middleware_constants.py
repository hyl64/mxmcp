"""Extract the middleware name table (the set of integrable middleware IPs).

`com.st.microxplorer.mcu.MiddleWareConstants` declares every middleware instance
name CubeMX knows (`MW_FREERTOS=FREERTOS`, `MW_LWIP=LWIP`, `MW_USB_HOST=USB_HOST`,
multi-core variants `*_M4/_M7`, and the template paths each one generates).
These names are exactly what `set mode <name> ...` / `Mcu.IPn` use.

Writes analysis/middleware_constants.json and mxmcp/data/middleware.json.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

JAVAP = os.environ.get("MXMCP_JAVAP") or shutil.which("javap") or \
    r"C:\Program Files\Eclipse Adoptium\jdk-21.0.10.7-hotspot\bin\javap.exe"
HERE = Path(__file__).resolve().parent.parent
JAR = HERE / "_extract" / "cubemx_full.jar"
CLS = "com.st.microxplorer.mcu.MiddleWareConstants"
OUT = HERE / "analysis" / "middleware_constants.json"
DATA = HERE / "mxmcp" / "data" / "middleware.json"

STR = re.compile(r'static final java\.lang\.String ([A-Za-z0-9_]+) = "([^"]*)";')
INT = re.compile(r"static final int ([A-Za-z0-9_]+) = (-?\d+);")


def main() -> int:
    txt = subprocess.run([JAVAP, "-p", "-constants", "-cp", str(JAR), CLS],
                         capture_output=True, timeout=180).stdout.decode("utf-8",
                                                                        "replace")
    strings = dict(STR.findall(txt))
    ints = dict(INT.findall(txt))
    mw = {k: v for k, v in strings.items() if k.startswith("MW_")}
    # instance names, keyed by the short form used in .ioc / set mode
    names = sorted(set(mw.values()))
    templates = {k: v for k, v in strings.items() if v.endswith(".ftl")}
    report = {"class": CLS, "constants": strings, "int_constants": ints,
              "middleware_names": names,
              "middleware_constants": mw,
              "template_constants": templates}
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps({"names": names,
                                "name_by_constant": mw,
                                "templates": templates}, indent=1),
                    encoding="utf-8")
    print(f"{len(strings)} string constants, {len(mw)} MW_* entries, "
          f"{len(names)} distinct middleware names")
    print("names:", ", ".join(names[:24]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
