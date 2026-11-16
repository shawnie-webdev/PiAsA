#!/usr/bin/env python3
"""PiAsA: configure Linux USB gadget composites with an nmcli-like CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

APP = "PiAsA"
CONFIG_DIR = Path(os.environ.get("PIASA_CONFIG_DIR", Path.home() / ".config/piasa"))
CONFIG_FILE = CONFIG_DIR / "composite.json"
GADGET_ROOT = Path("/sys/kernel/config/usb_gadget")
DEFAULT_ID = "0x0100"

TEMPLATES = {
    "keyboard": {
        "type": "hid", "protocol": 1, "subclass": 1, "report_length": 8,
        "report_desc": "05010906a101050719e029e71500250175019508810295017508810195057501050819012905910295017503910195067508150025650507190029658100c0",
    },
    "mouse": {
        "type": "hid", "protocol": 2, "subclass": 1, "report_length": 4,
        "report_desc": "05010902a1010901a100050919012903150025019503750181029501750581010501093009311581257f750895028106c0c0",
    },
    "serial": {"type": "serial"},
    "ethernet": {"type": "ethernet", "function": "ecm"},
    "rndis": {"type": "ethernet", "function": "rndis"},
    "storage": {"type": "storage", "backing_file": ""},
}

def fail(message: str, code: int = 2) -> None:
    print(f"piasa: error: {message}", file=sys.stderr)
    raise SystemExit(code)

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        fail("no composite configuration; run 'piasa --init composite' first")
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read {CONFIG_FILE}: {exc}")
    data.setdefault("name", "PiAsA Composite")
    data.setdefault("devices", {})
    return data

def save_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n")
    temp.replace(CONFIG_FILE)

def parse_assignments(tokens: list[str]) -> dict:
    values = {}
    for token in tokens:
        if "=" not in token:
            fail(f"expected key=value, got '{token}'")
        key, value = token.split("=", 1)
        values[key.replace("-", "_")] = value
    return values

def init_composite() -> None:
    if CONFIG_FILE.exists():
        fail(f"configuration already exists at {CONFIG_FILE}; use 'piasa composite reset' to replace it")
    save_config({"name": "PiAsA Composite", "idVendor": "0x1d6b", "idProduct": "0x0104",
                 "manufacturer": "PiAsA", "product": "PiAsA USB Composite", "serial": "PIASA0001",
                 "devices": {}})
    print(f"success: initialized composite configuration ({CONFIG_FILE})")
    print("hint: piasa composite add device keyboard --type hid")

def add_device(name: str, kind: str) -> None:
    data = load_config()
    if name in data["devices"]:
        fail(f"device '{name}' already exists")
    if kind not in {"hid", "serial", "ethernet", "storage"}:
        fail("supported types: hid, serial, ethernet, storage")
    data["devices"][name] = {"type": kind, "name": name}
    save_config(data)
    print(f"success: added device '{name}' (type {kind})")

def set_device(name: str, assignments: list[str]) -> None:
    data = load_config()
    if name not in data["devices"]:
        fail(f"unknown device '{name}'")
    values = parse_assignments(assignments)
    device = data["devices"][name]
    for key, value in values.items():
        if key == "template":
            if value not in TEMPLATES:
                fail(f"unknown template '{value}'; available: {', '.join(TEMPLATES)}")
            template = dict(TEMPLATES[value])
            if device["type"] != template["type"]:
                fail(f"template '{value}' requires type '{template['type']}', not '{device['type']}'")
            device.update(template)
            device["template"] = value
        elif key in {"name", "function", "backing_file", "readonly", "protocol", "subclass", "report_length", "report_desc"}:
            if key in {"protocol", "subclass", "report_length"}:
                try:
                    device[key] = int(value, 0)
                except ValueError:
                    fail(f"{key} must be an integer")
            elif key == "readonly":
                device[key] = value.lower() in {"1", "yes", "true", "on"}
            else:
                device[key] = value
        else:
            fail(f"unknown property '{key}'")
    save_config(data)
    print(f"success: updated device '{name}'")

def show(data: dict) -> None:
    print("GENERAL")
    print(f"  composite         {data.get('product', data.get('name', 'PiAsA Composite'))}")
    print(f"  vendor_id         {data.get('idVendor')}")
    print(f"  product_id        {data.get('idProduct')}")
    print(f"  config_file       {CONFIG_FILE}")
    print()
    print("DEVICES")
    if not data["devices"]:
        print("  (none)")
    for name, dev in data["devices"].items():
        print(f"  {name:<18} type={dev['type']:<10} template={dev.get('template', '-'):<10} name={dev.get('name', name)}")

def write_text(path: Path, value: str) -> None:
    path.write_text(str(value))

def require_root() -> None:
    if os.geteuid() != 0:
        fail("this operation needs root; rerun with sudo", 1)

def hid_descriptor(device: dict) -> bytes:
    try:
        return bytes.fromhex(device["report_desc"])
    except (KeyError, ValueError):
        fail(f"HID device '{device['name']}' needs a valid report_desc; choose template=keyboard or template=mouse")

def apply_composite() -> None:
    require_root()
    data = load_config()
    if not data["devices"]:
        fail("composite has no devices; add at least one device first")
    if not GADGET_ROOT.exists():
        fail("configfs USB gadget support is unavailable; mount configfs and check your kernel")
    gadget = GADGET_ROOT / "piasa"
    if gadget.exists():
        fail("a gadget named 'piasa' already exists; run 'piasa composite down' first")
    gadget.mkdir()
    try:
        write_text(gadget / "idVendor", data["idVendor"])
        write_text(gadget / "idProduct", data["idProduct"])
        strings = gadget / "strings/0x409"
        strings.mkdir(parents=True)
        write_text(strings / "serialnumber", data["serial"])
        write_text(strings / "manufacturer", data["manufacturer"])
        write_text(strings / "product", data["product"])
        config = gadget / "configs/c.1"
        config.mkdir(parents=True)
        config_strings = config / "strings/0x409"
        config_strings.mkdir(parents=True)
        write_text(config_strings / "configuration", "PiAsA composite")
        write_text(config / "MaxPower", "250")

        type_counts = {"hid": 0, "serial": 0, "ethernet": 0, "storage": 0}
        for name, dev in data["devices"].items():
            kind = dev["type"]
            index = type_counts[kind]
            type_counts[kind] += 1
            if kind == "hid":
                function = gadget / f"functions/hid.usb{index}"
                function.mkdir(parents=True)
                write_text(function / "protocol", str(dev.get("protocol", 1)))
                write_text(function / "subclass", str(dev.get("subclass", 1)))
                write_text(function / "report_length", str(dev.get("report_length", 8)))
                (function / "report_desc").write_bytes(hid_descriptor(dev))
            elif kind == "serial":
                function = gadget / f"functions/acm.usb{index}"
                function.mkdir(parents=True)
            elif kind == "ethernet":
                mode = dev.get("function", "ecm")
                if mode not in {"ecm", "rndis"}:
                    fail(f"ethernet device '{name}': function must be ecm or rndis")
                function = gadget / f"functions/{mode}.usb{index}"
                function.mkdir(parents=True)
            elif kind == "storage":
                backing = dev.get("backing_file")
                if not backing or not Path(backing).is_file():
                    fail(f"storage device '{name}' needs backing_file=/path/to/disk.img")
                function = gadget / f"functions/mass_storage.usb{index}"
                function.mkdir(parents=True)
                lun = function / "lun.0"
                write_text(lun / "file", str(Path(backing).resolve()))
                write_text(lun / "ro", "1" if dev.get("readonly", True) else "0")
            else:
                fail(f"unsupported device type '{kind}'")
            (config / function.name).symlink_to(function)

        udcs = Path("/sys/class/udc")
        controllers = sorted(p.name for p in udcs.iterdir()) if udcs.exists() else []
        if not controllers:
            fail("no USB Device Controller (UDC) found; this board/USB port may not support gadget mode")
        write_text(gadget / "UDC", controllers[0])
        print(f"success: composite gadget active on {controllers[0]}")
    except Exception:
        try:
            if gadget.exists():
                shutil.rmtree(gadget)
        except OSError:
            pass
        raise

def down_composite() -> None:
    require_root()
    gadget = GADGET_ROOT / "piasa"
    if not gadget.exists():
        print("info: composite gadget is not active")
        return
    udc = gadget / "UDC"
    if udc.exists():
        write_text(udc, "")
    shutil.rmtree(gadget)
    print("success: composite gadget stopped")

def main() -> None:
    args = sys.argv[1:]
    if args[:2] == ["--init", "composite"]:
        init_composite()
        return
    if not args or args[0] in {"-h", "--help", "help"}:
        print("""PiAsA - Pi As A USB Everything

Usage:
  piasa --init composite
  piasa composite add device NAME --type TYPE
  piasa composite NAME key=value [key=value ...]
  piasa composite show
  piasa composite apply
  piasa composite down
  piasa composite reset

Types: hid, serial, ethernet, storage
Templates: keyboard, mouse, serial, ethernet, rndis, storage
""")
        return
    if args[0] != "composite":
        fail(f"unknown command '{args[0]}'")
    if len(args) == 1 or args[1] == "show":
        show(load_config())
    elif args[1:3] == ["add", "device"]:
        parser = argparse.ArgumentParser(prog="piasa composite add device")
        parser.add_argument("name")
        parser.add_argument("--type", required=True)
        parsed = parser.parse_args(args[3:])
        add_device(parsed.name, parsed.type)
    elif args[1] == "apply":
        apply_composite()
    elif args[1] == "down":
        down_composite()
    elif args[1] == "reset":
        if (GADGET_ROOT / "piasa").exists():
            fail("stop the active gadget with 'piasa composite down' first")
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
        print("success: removed composite configuration")
    else:
        set_device(args[1], args[2:])

if __name__ == "__main__":
    main()
