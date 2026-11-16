#!/usr/bin/env python3
"""Linux networking helpers for PiAsA Ethernet gadget modes."""
import ipaddress, json, os, re, subprocess
from pathlib import Path

STATE = Path(os.environ.get("PIASA_CONFIG_DIR", Path.home() / ".config/piasa")) / "network-state.json"
TABLE = "piasa"

def run(*args):
    try:
        return subprocess.run(args, check=True, text=True, capture_output=True).stdout.strip()
    except FileNotFoundError:
        raise RuntimeError("required command missing: " + args[0])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError((exc.stderr or "").strip() or "command failed: " + " ".join(args))

def iface(name):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", name or "") or not Path("/sys/class/net", name).exists():
        raise RuntimeError("network interface does not exist: " + str(name))
    return name

def usb_iface(device):
    if device.get("usb_interface"):
        return iface(device["usb_interface"])
    found = sorted(p.name for p in Path("/sys/class/net").iterdir() if p.name.startswith(("usb", "enx")))
    if len(found) != 1:
        raise RuntimeError("cannot uniquely identify USB gadget interface; set usb_interface=usb0")
    return found[0]

def nft(script):
    try:
        subprocess.run(["nft", "-f", "-"], input=script, text=True, check=True, capture_output=True)
    except FileNotFoundError:
        raise RuntimeError("install nftables first")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("nftables: " + (exc.stderr or "").strip())

def setup(device):
    mode = device.get("mode")
    usb = usb_iface(device)
    if STATE.exists():
        raise RuntimeError("network mode already active; run piasa composite down first")
    cidr = device.get("ip_address", "192.168.7.1/24")
    try:
        usb_addr = ipaddress.ip_interface(cidr)
    except ValueError:
        raise RuntimeError("ip_address must be CIDR, e.g. 192.168.7.1/24")
    old_forward = Path("/proc/sys/net/ipv4/ip_forward").read_text().strip()
    state = {"usb": usb, "mode": mode, "old_forward": old_forward, "peer": None, "usb_address": str(usb_addr)}
    run("ip", "address", "replace", str(usb_addr), "dev", usb)
    run("ip", "link", "set", usb, "up")

    if mode == "loopback":
        target = device.get("target", "")
        if target.count(":") != 1:
            raise RuntimeError("loopback target must be IPv4:PORT, e.g. 127.0.0.1:8080")
        host, port = target.rsplit(":", 1)
        try:
            host, port = str(ipaddress.IPv4Address(host)), int(port)
        except ValueError:
            raise RuntimeError("invalid loopback target; use IPv4:PORT")
        if not 1 <= port <= 65535:
            raise RuntimeError("target port must be 1..65535")
        nft('table inet piasa { chain prerouting { type nat hook prerouting priority dstnat; policy accept; iifname "' + usb + '" meta l4proto { tcp, udp } dnat to ' + host + ':' + str(port) + ' } }')
        state["target"] = target

    elif mode in {"relay", "pctorouter"}:
        upstream = iface(device.get("relaywho", ""))
        if upstream == usb:
            raise RuntimeError("relaywho cannot be the USB interface")
        nft('table inet piasa { chain forward { type filter hook forward priority filter; policy accept; iifname "' + usb + '" oifname "' + upstream + '" accept; iifname "' + upstream + '" oifname "' + usb + '" ct state established,related accept } chain postrouting { type nat hook postrouting priority srcnat; policy accept; oifname "' + upstream + '" masquerade } }')
        Path("/proc/sys/net/ipv4/ip_forward").write_text("1")
        state["upstream"] = upstream
        print("USB host gateway: " + str(usb_addr.ip) + "; upstream: " + upstream)
        if mode == "relay":
            print("Relay uses routed/NAT forwarding, not a transparent layer-2 bridge.")

    elif mode == "peertopeer":
        peer = iface(device.get("relaywho", ""))
        if peer == usb:
            raise RuntimeError("relaywho cannot be the USB interface")
        run("ip", "address", "replace", "192.168.8.1/30", "dev", peer)
        run("ip", "link", "set", peer, "up")
        nft('table inet piasa { chain forward { type filter hook forward priority filter; policy accept; iifname "' + usb + '" oifname "' + peer + '" accept; iifname "' + peer + '" oifname "' + usb + '" ct state established,related accept } }')
        Path("/proc/sys/net/ipv4/ip_forward").write_text("1")
        state["peer"] = peer
        print("PC 2 must use 192.168.8.2/30; Pi peer-side address is 192.168.8.1/30.")
        print("Configure return routes on both PCs.")

    else:
        raise RuntimeError("unsupported Ethernet mode: " + str(mode))
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    print("PiAsA network mode active: " + mode)

def teardown():
    if not STATE.exists():
        return
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    subprocess.run(["nft", "delete", "table", "inet", TABLE], check=False, capture_output=True)
    old = state.get("old_forward")
    if old in {"0", "1"}:
        Path("/proc/sys/net/ipv4/ip_forward").write_text(old)
    peer = state.get("peer")
    if peer:
        subprocess.run(["ip", "address", "del", "192.168.8.1/30", "dev", peer], check=False, capture_output=True)
    usb, usb_address = state.get("usb"), state.get("usb_address")
    if usb and usb_address:
        subprocess.run(["ip", "address", "del", usb_address, "dev", usb], check=False, capture_output=True)
    STATE.unlink(missing_ok=True)
