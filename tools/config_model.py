"""Index `db/mcu/config/*_Configs.xml`: the HAL init model behind code generation.

Each config file declares, per IP:
  <RefConfig Name="Usart_Init">      the init sequence
    <CallLibMethod Name="HAL_USART_Init">
      <MethodArg Name="Parity" ParameterName="UsartParity"/>
    <ImplementCallBack Name="HAL_USART_MspInit"/>
  <LibMethod Name="HAL_USART_Init">
    <Argument Name="husart" GenericType="struct" TypeName="USART_HandleTypeDef"
              AddressOf="true">
      <Argument Name="Instance" GenericType="baseaddress" TypeName="USART_TypeDef"/>
      <Argument Name="Init" GenericType="struct" TypeName="USART_InitTypeDef">
        <Argument Name="BaudRate" GenericType="simple"/>

The `Argument` tree is the HAL struct CubeMX fills: parameter names, C types and
the `OptimizationCondition` that decides whether a field is emitted. This is the
data the standalone code generator needs, so it is packed verbatim.

Writes analysis/config_model.json and (compactly) into the data pack.
"""
from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(os.environ.get(
    "MXMCP_CUBEMX_ROOT",
    r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeMX")) / "db" / "mcu" / "config"
HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "analysis" / "config_model.json"
DATA = HERE / "mxmcp" / "data" / "config_model.json"


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _args(node) -> list[dict]:
    out = []
    for el in node:
        if _local(el.tag) != "Argument":
            continue
        out.append({
            "name": el.get("Name", ""),
            "generic": el.get("GenericType", ""),
            "type": el.get("TypeName", ""),
            "address_of": el.get("AddressOf") == "true",
            "context": el.get("Context", ""),
            "optimize": el.get("OptimizationCondition", ""),
            "condition": el.get("Condition", ""),
            "children": _args(el),
        })
    return out


def parse(path: Path) -> dict:
    root = ET.parse(path).getroot()
    ip = root.get("Name") or path.stem.split("-")[0]
    fam = path.stem.split("-", 1)[1].rsplit("_", 1)[0] if "-" in path.stem else ""
    methods = {}
    for lm in root:
        if _local(lm.tag) != "LibMethod":
            continue
        methods[lm.get("Name", "")] = {
            "comment": lm.get("Comment", ""),
            "arguments": _args(lm),
            "file": lm.get("File", ""),
            "condition": lm.get("IFCondition", ""),
        }
    configs = {}
    for rc in root:
        if _local(rc.tag) != "RefConfig":
            continue
        calls = []
        for ch in rc:
            tag = _local(ch.tag)
            if tag in ("CallLibMethod", "ImplementCallBack", "CallHALMethod"):
                calls.append({"kind": tag, "name": ch.get("Name", ""),
                              "return_hal": ch.get("ReturnHAL", ""),
                              "args": [{"name": a.get("Name", ""),
                                        "parameter": a.get("ParameterName", "")}
                                       for a in ch if _local(a.tag) == "MethodArg"]})
        configs[rc.get("Name", "")] = {"comment": rc.get("Comment", ""),
                                       "condition": rc.get("IFCondition", ""),
                                       "calls": calls}
    files = [{"category": f.get("Category", ""), "name": f.get("Name", "")}
             for f in root if _local(f.tag) == "File"]
    return {"ip": ip, "family": fam, "lib_methods": methods,
            "configs": configs, "files": files}


def main() -> int:
    index: dict[str, dict] = {}
    for path in sorted(ROOT.glob("*_Configs.xml")):
        try:
            rec = parse(path)
        except (ET.ParseError, OSError):
            continue
        index.setdefault(rec["ip"], {})[rec["family"] or path.stem] = rec
    OUT.write_text(json.dumps(index, indent=1), encoding="utf-8")
    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    print(f"{len(index)} IPs, {sum(len(v) for v in index.values())} family variants")
    for ip in ("USART", "GPIO", "RCC", "ADC"):
        if ip in index:
            fam = sorted(index[ip])[0]
            rec = index[ip][fam]
            print(f"  {ip}[{fam}]: methods={list(rec['lib_methods'])[:5]} "
                  f"configs={list(rec['configs'])[:4]}")
    print(f"-> {DATA} ({DATA.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
