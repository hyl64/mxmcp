"""Authoritative CLI registry: every `CommandLineManager.addCommand(...)` in the
whole product (app jar + every plugin/ip jar), with the handler's bytecode facts.

For each registered command we recover:
  command name, help text, declared argc, declaring class, handler method
  (inner class onCommandEntered or lambda method), the argv indices it reads,
  the string constants it can emit, and the model calls it performs.

Output: analysis/cli_registry.json (+ human readable docs/CLI_REGISTRY.md).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

JAVAP = os.environ.get("MXMCP_JAVAP") or shutil.which("javap") or \
    r"C:\Program Files\Eclipse Adoptium\jdk-21.0.10.7-hotspot\bin\javap.exe"
HERE = Path(__file__).resolve().parent.parent
ROOT = Path(os.environ.get(
    "MXMCP_CUBEMX_ROOT",
    r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeMX"))
OUT = HERE / "analysis"
JAR_CANDIDATES = [HERE / "_extract" / "cubemx_full.jar"] + \
    sorted((ROOT / "plugins").glob("*.jar")) + \
    sorted((ROOT / "plugins" / "ip").glob("*.jar"))

LDC = re.compile(r"// String (.*)$")
LDCW = re.compile(r"// String (.*)$")
ARGC = re.compile(r"^\s+\d+: (iconst_(\d)|bipush\s+(\d+)|sipush\s+(\d+))")
ADD = re.compile(r"invokestatic.*CommandLineManager\.addCommand")
METHOD_DECL = re.compile(r"^  (?:private|public|protected|static|final)[^\n;]*\b(\w+)\("
                         r"[^\n]*\)\s*;\s*$")
ALOAD_IDX = re.compile(r"^\s+\d+: aaload")


def referencing_classes(jar: Path) -> list[str]:
    out = []
    try:
        z = zipfile.ZipFile(jar)
    except Exception:
        return out
    for n in z.namelist():
        if not n.endswith(".class"):
            continue
        b = z.read(n)
        if b"addCommand" in b and b"CommandLineManager" in b:
            out.append(n[:-6].replace("/", "."))
    return out


def javap(jar: Path, cls: str) -> str:
    p = subprocess.run([JAVAP, "-p", "-c", "-constants", "-cp", str(jar), cls],
                       capture_output=True, timeout=240)
    return p.stdout.decode("utf-8", "replace")


def registrations(text: str, jar_key: str, cls: str) -> list[dict]:
    lines = text.splitlines()
    rows = []
    method = ""
    for i, line in enumerate(lines):
        m = METHOD_DECL.match(line)
        if m:
            method = m.group(1)
        if not ADD.search(line):
            continue
        strings = []
        argc = None
        listener = ""
        for j in range(i - 1, max(-1, i - 60), -1):
            sm = LDC.search(lines[j])
            if sm and len(strings) < 2:
                strings.append(sm.group(1))
            am = ARGC.match(lines[j])
            if am and argc is None:
                argc = int(am.group(2) or am.group(3) or am.group(4))
            lm = re.search(r"// (?:Method|InterfaceMethod) (\S+):\S*\(([^)]*)\)"
                           r".*onCommandEntered", lines[j])
            im = re.search(r"invokedynamic.*// InvokeDynamic #\d+:\w+:\("
                           r"([^)]*)\)", lines[j])
            if (lm or im) and not listener:
                src = lm.group(1) if lm else im.group(1)
                listener = src
            if len(strings) == 2 and argc is not None and listener:
                break
        rows.append({"jar": jar_key, "registrar": cls, "registrar_method": method,
                     "command": strings[-1].strip() if strings else "?",
                     "help": strings[0].strip() if len(strings) > 1 else "",
                     "argc": argc, "listener": listener})
    return rows


def handler_facts(text: str, names: set[str]) -> dict:
    """argv indices + emitted strings for the handler bodies of one class."""
    facts: dict[str, dict] = {}
    lines = text.splitlines()
    cur = None
    for i, line in enumerate(lines):
        m = METHOD_DECL.match(line)
        if m:
            cur = m.group(1)
            if cur not in names:
                cur = None
            else:
                facts.setdefault(cur, {"argv": set(), "strings": [], "calls": []})
            continue
        if cur is None:
            continue
        # argv access:  aload_N / aaload patterns -> approximate by tracking the
        # constant index pushed right before aaload
        if ALOAD_IDX.match(line):
            idx = None
            for j in range(i - 1, max(-1, i - 8), -1):
                im = re.match(r"^\s+\d+: (iconst_(\d)|bipush\s+(\d+))", lines[j])
                if im:
                    idx = int(im.group(2) or im.group(3))
                    break
                if "aload" in lines[j] and "aload_" not in lines[j]:
                    break
            if idx is not None:
                facts[cur]["argv"].add(idx)
        sm = LDC.search(line)
        if sm and len(facts[cur]["strings"]) < 40:
            facts[cur]["strings"].append(sm.group(1))
        cm = re.search(r"// (?:Method|InterfaceMethod) (com/st/\S+):\S", line)
        if cm and len(facts[cur]["calls"]) < 60:
            facts[cur]["calls"].append(cm.group(1))
    return {k: {"argv": sorted(v["argv"]), "strings": v["strings"],
                "calls": v["calls"]} for k, v in facts.items()}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    all_rows: list[dict] = []
    for jar in JAR_CANDIDATES:
        if not jar.exists():
            continue
        key = "app" if jar.name == "cubemx_full.jar" else jar.name
        classes = referencing_classes(jar)
        for cls in classes:
            text = javap(jar, cls)
            if "addCommand" not in text:
                continue
            regs = registrations(text, key, cls)
            names = {r["listener"].split(".")[-1] for r in regs if r["listener"]}
            facts = handler_facts(text, names or {"onCommandEntered"})
            for r in regs:
                r["handler_facts"] = facts
            all_rows.extend(regs)
    seen = set()
    uniq = []
    for r in all_rows:
        k = (r["jar"], r["command"], r["help"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    uniq.sort(key=lambda r: r["command"])
    (OUT / "cli_registry.json").write_text(
        json.dumps(uniq, indent=1), encoding="utf-8")
    print(f"{len(uniq)} unique command registrations across {len(set(r['jar'] for r in uniq))} jars")
    for r in uniq:
        print(f"{r['command']:36s} argc={r['argc']} [{r['jar']}] {r['registrar'].split('.')[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
