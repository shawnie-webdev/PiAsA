# PiAsA — Pi As A USB Everything

PiAsA is an nmcli-inspired command-line utility for configuring Linux USB composite gadgets on Raspberry Pi boards and other Linux systems with USB Device Controller (UDC) support.

It stores a declarative configuration first, then applies it to Linux configfs when explicitly requested.

> **Hardware note:** Gadget mode requires a USB port wired to a USB Device Controller and a kernel with configfs/libcomposite support. Not every Raspberry Pi USB port supports device mode. Raspberry Pi 5's USB-C power connector is not a general-purpose gadget port.

## Install

```sh
python3 -m pip install .
```

For development, run `python3 piasa.py --help`.

## Quick start

```sh
piasa --init composite
piasa composite add device keyboard --type hid
piasa composite keyboard template=keyboard
piasa composite keyboard name="Pi4 HID keyboard"
piasa composite add device mouse --type hid
piasa composite mouse template=mouse
piasa composite show
```

This creates a local configuration. It does **not** activate the USB gadget yet.

## Commands

| Command | Purpose |
| --- | --- |
| `piasa --init composite` | Create a composite configuration |
| `piasa composite show` | Display configuration, nmcli-style |
| `piasa composite add device NAME --type TYPE` | Add a named function |
| `piasa composite NAME key=value ...` | Set device properties |
| `piasa composite apply` | Apply configuration to configfs and bind a UDC |
| `piasa composite down` | Unbind and remove the active gadget |
| `piasa composite reset` | Remove the saved configuration (only while inactive) |

Supported types: `hid`, `serial`, `ethernet`, `storage`.

## Templates

| Template | Required type | Result |
| --- | --- | --- |
| `keyboard` | `hid` | Standard boot keyboard report descriptor |
| `mouse` | `hid` | Standard relative mouse report descriptor |
| `serial` | `serial` | USB CDC ACM serial port |
| `ethernet` | `ethernet` | USB CDC ECM network interface |
| `rndis` | `ethernet` | USB RNDIS network interface |
| `storage` | `storage` | USB mass-storage function; set a backing image |

Example additional functions:

```sh
piasa composite add device console --type serial
piasa composite console template=serial
piasa composite add device network --type ethernet
piasa composite network template=ethernet
piasa composite add device disk --type storage
piasa composite disk template=storage backing_file=/path/to/disk.img readonly=true
```

## Apply

Applying changes system USB gadget state and requires root. Make sure the Pi is connected to the host through a gadget-capable USB port.

```sh
sudo piasa composite apply
```

Stop the gadget:

```sh
sudo piasa composite down
```

The active gadget is created at `/sys/kernel/config/usb_gadget/piasa`. The configuration is stored at `~/.config/piasa/composite.json` (or under `PIASA_CONFIG_DIR` when set).

## Safety and limitations

- PiAsA only configures the local Linux gadget. It does not inject keystrokes or mouse actions; HID input transport/application logic is outside this initial release.
- Storage uses an existing image file. Do not modify the same backing image from the Pi and host simultaneously.
- UDC availability, supported function drivers, host OS compatibility, and board wiring vary.
- The initial release supports keyboard/mouse HID descriptors, serial, ECM/RNDIS networking, and mass storage. UVC video/audio gadget support is not implemented yet.
