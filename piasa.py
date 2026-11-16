#!/usr/bin/env python3
"""PiAsA: configure Linux USB gadget composites with an nmcli-like CLI."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import shutil
import socket
import select
import subprocess
import termios
import time
import sys
from pathlib import Path

APP = "PiAsA"
_config_default = Path.home() / ".config/piasa"
if os.geteuid() == 0 and os.environ.get("SUDO_USER"):
    try:
        _config_default = Path(pwd.getpwnam(os.environ["SUDO_USER"]).pw_dir) / ".config/piasa"
    except KeyError:
        pass
CONFIG_DIR = Path(os.environ.get("PIASA_CONFIG_DIR", _config_default))
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
        elif key in {"name", "function", "backing_file", "readonly", "protocol", "subclass", "report_length", "report_desc", "mac_address", "host_mac_address", "dev_mac_address", "mode", "relaywho", "target", "bandwidth", "dns_upstream", "ip_address", "usb_interface"} or key == "type":
            if key == "type":
                if device.get("type") != "ethernet":
                    fail("type=... is an Ethernet mode and requires an ethernet device")
                key = "mode"
                value = value.lower()
                if value not in {"relay", "peertopeer", "pctorouter", "loopback", "piasa-router"}:
                    fail("Ethernet modes: relay, peertopeer, pctorouter, loopback, piasa-router")
                device[key] = value
            elif key == "mode":
                value = value.lower()
                if value not in {"relay", "peertopeer", "pctorouter", "loopback", "piasa-router"}:
                    fail("Ethernet modes: relay, peertopeer, pctorouter, loopback, piasa-router")
                device[key] = value
            elif key == "bandwidth":
                if device.get("type") != "serial":
                    fail("bandwidth is only valid for serial devices")
                try:
                    baud = int(value, 10)
                except ValueError:
                    fail("bandwidth must be an integer baud rate")
                if baud not in {50, 75, 110, 134, 150, 200, 300, 600, 1200, 1800, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400}:
                    fail("unsupported baud rate")
                device[key] = baud
            elif key in {"relaywho", "target", "dns_upstream", "ip_address", "usb_interface"}:
                if device.get("type") != "ethernet":
                    fail(f"{key} is only valid for ethernet devices")
                device[key] = value
            elif key in {"protocol", "subclass", "report_length"}:
                try:
                    device[key] = int(value, 0)
                except ValueError:
                    fail(f"{key} must be an integer")
            elif key == "readonly":
                device[key] = value.lower() in {"1", "yes", "true", "on"}
            else:
                if key in {"mac_address", "host_mac_address", "dev_mac_address"}:
                    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", value):
                        fail(f"{key} must look like 02:11:22:33:44:55")
                    value = value.lower()
                device[key] = value
        else:
            fail(f"unknown property '{key}'")
    save_config(data)
    print(f"success: updated device '{name}'")

GLOBAL_PROPERTIES = {
    "vendor_id": "idVendor", "product_id": "idProduct",
    "manufacturer": "manufacturer", "product": "product", "serial": "serial",
    "bcd_device": "bcdDevice", "bcd_usb": "bcdUSB",
    "device_class": "bDeviceClass", "device_subclass": "bDeviceSubClass",
    "device_protocol": "bDeviceProtocol",
}

def serial_path(data: dict, name: str) -> Path:
    names = [n for n, d in data["devices"].items() if d.get("type") == "serial"]
    if name not in names:
        fail(f"'{name}' is not a serial device")
    return Path(f"/dev/ttyGS{names.index(name)}")

def serial_open(data: dict, name: str) -> int:
    dev = data["devices"][name]
    path = serial_path(data, name)
    if not path.exists():
        fail(f"{path} is unavailable; apply the gadget and open the host serial port")
    baud = int(dev.get("bandwidth", 9600))
    speed = getattr(termios, f"B{baud}", None)
    if speed is None:
        fail(f"baud rate {baud} is not supported on this system")
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    attrs[4] = speed
    attrs[5] = speed
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd

def serial_send(name: str, payload: str, wait_ms=None) -> None:
    data = load_config()
    dev = data["devices"].get(name)
    if not dev or dev.get("type") != "serial":
        fail(f"'{name}' is not a configured serial device")
    fd = serial_open(data, name)
    try:
        raw = payload.encode("utf-8")
        offset = 0
        while offset < len(raw):
            offset += os.write(fd, raw[offset:])
        print(f"sent {offset} byte(s) through {name}")
    except OSError as exc:
        fail(f"serial write failed: {exc}", 1)
    finally:
        os.close(fd)
    if wait_ms is not None:
        serial_listen(name, wait_ms)

def serial_listen(name: str, timeout_ms: int) -> None:
    data = load_config()
    dev = data["devices"].get(name)
    if not dev or dev.get("type") != "serial":
        fail(f"'{name}' is not a configured serial device")
    fd = serial_open(data, name)
    try:
        ready, _, _ = select.select([fd], [], [], timeout_ms / 1000)
        if not ready:
            print("timeout: no serial response received")
            return
        chunks = []
        while True:
            try:
                part = os.read(fd, 4096)
            except BlockingIOError:
                break
            if not part:
                break
            chunks.append(part)
            ready, _, _ = select.select([fd], [], [], 0.05)
            if not ready:
                break
        sys.stdout.buffer.write(b"".join(chunks))
        if chunks and not b"".join(chunks).endswith(b"\\n"):
            sys.stdout.buffer.write(b"\\n")
        sys.stdout.buffer.flush()
    finally:
        os.close(fd)

def start_dns_proxy(bind_ip: str, upstream: str) -> None:
    pidfile = CONFIG_DIR / "dns-proxy.pid"
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)
            print(f"DNS forwarder already running (PID {pid})")
            return
        except (ValueError, OSError):
            pidfile.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "piasa_dns", "--listen", bind_ip, "--upstream", upstream],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True,
    )
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(proc.pid) + "\\n")
    time.sleep(0.15)
    if proc.poll() is not None:
        pidfile.unlink(missing_ok=True)
        fail("DNS forwarder failed to start; UDP/TCP port 53 may already be in use")
    print(f"DNS forwarder started on {bind_ip}:53 -> {upstream}:53 (PID {proc.pid})")

def ethernet_sendtarget(name: str) -> None:
    require_root()
    data = load_config()
    dev = data["devices"].get(name)
    if not dev or dev.get("type") != "ethernet":
        fail(f"'{name}' is not a configured ethernet device")
    gadget = GADGET_ROOT / "piasa"
    if not (gadget / "UDC").exists() or not (gadget / "UDC").read_text().strip():
        fail("apply the composite gadget before running sendtarget")
    mode = dev.get("mode")
    if mode == "piasa-router":
        iface = dev.get("usb_interface")
        if not iface:
            candidates = [p.name for p in Path("/sys/class/net").iterdir()
                          if p.name.startswith(("usb", "enx"))]
            if len(candidates) != 1:
                fail("cannot uniquely identify USB interface; set usb_interface=NAME")
            iface = candidates[0]
        address = dev.get("ip_address", "192.168.7.1/24")
        upstream = dev.get("dns_upstream", "1.1.1.1")
        try:
            subprocess.run(["ip", "address", "replace", address, "dev", iface], check=True)
            subprocess.run(["ip", "link", "set", iface, "up"], check=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            fail(f"could not configure {iface}: {exc}", 1)
        start_dns_proxy(address.split("/", 1)[0], upstream)
        print("Configure the USB host with a static address in the USB subnet and DNS server " + address.split("/", 1)[0])
        print("DNS forwarding only; general Internet routing is not enabled.")
        return
    if mode not in {"relay", "peertopeer", "pctorouter", "loopback"}:
        fail("set an Ethernet type first: relay, peertopeer, pctorouter, loopback, piasa-router")
    try:
        from piasa_net import setup
        setup(dev)
    except (RuntimeError, OSError) as exc:
        fail(str(exc), 1)

def set_global(assignments: list[str]) -> None:
    data = load_config()
    for key, value in parse_assignments(assignments).items():
        target = GLOBAL_PROPERTIES.get(key)
        if not target:
            fail(f"unknown composite property '{key}'")
        if key in {"vendor_id", "product_id", "bcd_device", "bcd_usb",
                   "device_class", "device_subclass", "device_protocol"}:
            try:
                number = int(value, 0)
            except ValueError:
                fail(f"{key} must be an integer, e.g. 0x1d6b")
            if not 0 <= number <= 0xffff:
                fail(f"{key} must be between 0 and 65535")
            data[target] = f"0x{number:04x}"
        else:
            data[target] = value
    save_config(data)
    print("success: updated composite descriptors")

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
        extra = []
        for key in ("mode", "target", "relaywho", "bandwidth", "dns_upstream"):
            if key in dev:
                extra.append(f"{key}={dev[key]}")
        suffix = (" " + " ".join(extra)) if extra else ""
        print(f"  {name:<18} type={dev['type']:<10} template={dev.get('template', '-'):<10} name={dev.get('name', name)}{suffix}")

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

def remove_configfs_tree(path: Path) -> None:
    """Remove a configfs gadget safely: unlink references before removing objects."""
    if not path.exists():
        return

    directories = []
    symlinks = []

    def collect(current: Path) -> None:
        directories.append(current)
        with os.scandir(current) as entries:
            for entry in entries:
                child = Path(entry.path)
                if entry.is_symlink():
                    symlinks.append(child)
                elif entry.is_dir(follow_symlinks=False):
                    collect(child)
                # Configfs attribute files are virtual and must not be unlinked.

    collect(path)

    # A function instance cannot be removed while a config still links to it.
    for link in symlinks:
        if link.is_symlink():
            link.unlink()

    # Remove configfs groups from the deepest child back to the gadget root.
    for directory in reversed(directories):
        if directory.exists():
            directory.rmdir()

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
        for prop in ("bcdDevice", "bcdUSB", "bDeviceClass", "bDeviceSubClass", "bDeviceProtocol"):
            if prop in data:
                write_text(gadget / prop, data[prop])
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
                if dev.get("dev_mac_address") or dev.get("mac_address"):
                    write_text(function / "dev_addr", dev.get("dev_mac_address", dev.get("mac_address")))
                if dev.get("host_mac_address"):
                    write_text(function / "host_addr", dev["host_mac_address"])
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
                udc = gadget / "UDC"
                if udc.exists():
                    write_text(udc, "")
                remove_configfs_tree(gadget)
        except OSError:
            pass
        raise

def stop_dns_proxy() -> None:
    pidfile = CONFIG_DIR / "dns-proxy.pid"
    if not pidfile.exists():
        return
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 15)
    except (ValueError, OSError):
        pass
    pidfile.unlink(missing_ok=True)


def down_composite() -> None:
    require_root()
    stop_dns_proxy()
    try:
        from piasa_net import teardown
        teardown()
    except (RuntimeError, OSError) as exc:
        fail(f"network cleanup failed: {exc}", 1)
    gadget = GADGET_ROOT / "piasa"
    if not gadget.exists():
        print("info: composite gadget is not active")
        return
    udc = gadget / "UDC"
    if udc.exists():
        write_text(udc, "")
    remove_configfs_tree(gadget)
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
  piasa composite SERIAL send="text"
  piasa composite SERIAL listen timeout=1000
  piasa composite ETHERNET sendtarget
  piasa composite vendor_id=0x1234 product_id=0x5678 [manufacturer=NAME ...]
  piasa composite show
  piasa composite apply
  piasa composite down
  piasa composite reset

Types: hid, serial, ethernet, storage
Templates: keyboard, mouse, serial, ethernet, rndis, storage
Ethernet modes: relay, peertopeer, pctorouter, loopback, piasa-router
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
    elif len(args) > 1 and "=" in args[1]:
        set_global(args[1:])
    elif args[1] == "apply":
        apply_composite()
    elif args[1] == "down":
        down_composite()
    elif len(args) >= 3 and args[2] == "sendtarget":
        ethernet_sendtarget(args[1])
    elif len(args) >= 3 and args[2] == "send":
        payload = args[3] if len(args) > 3 else ""
        if payload.startswith("text="):
            payload = payload.split("=", 1)[1]
        serial_send(args[1], payload)
    elif len(args) >= 3 and args[2].startswith("send="):
        options = parse_assignments(args[3:])
        wait_ms = None
        if "wait" in options:
            try:
                wait_ms = int(options["wait"], 10)
            except ValueError:
                fail("send wait must be milliseconds")
            if wait_ms < 0:
                fail("send wait cannot be negative")
        serial_send(args[1], args[2].split("=", 1)[1], wait_ms)
    elif len(args) >= 3 and args[2] == "listen":
        options = parse_assignments(args[3:])
        try:
            timeout_ms = int(options.get("timeout", "1000"), 10)
        except ValueError:
            fail("listen timeout must be milliseconds")
        if timeout_ms < 0:
            fail("listen timeout cannot be negative")
        serial_listen(args[1], timeout_ms)
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
