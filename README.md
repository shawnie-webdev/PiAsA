# PiAsA — Pi As A USB Everything

PiAsA is an nmcli-inspired command-line utility for configuring Linux USB composite gadgets on Raspberry Pi boards and other Linux systems with USB Device Controller (UDC) support.

It stores a declarative configuration first, then applies it to Linux configfs when explicitly requested.

> **Hardware note:** Gadget mode requires a USB port wired to a USB Device Controller and a kernel with configfs/libcomposite support. Not every Raspberry Pi USB port supports device mode. Raspberry Pi 5's USB-C power connector is not a general-purpose gadget port.

## Install

The easiest option is the per-user installer. From the cloned repository:

```sh
bash install.sh
```

It creates an isolated Python virtual environment at `~/.local/share/piasa/venv`, installs PiAsA there, and places the `piasa` command in `~/.local/bin`. It does not need sudo and does not modify your system Python.

If `piasa` is not found after installation, add this to your shell profile and open a new terminal:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

To update, pull the latest repository changes and run `bash install.sh` again. To uninstall the application (your PiAsA configuration is preserved):

```sh
bash install.sh --uninstall
```

Manual/development install is also available with `python3 -m pip install .`. For development without installing, run `python3 piasa.py --help`.

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
| `piasa composite SERIAL send="text"` | Send text over a CDC ACM serial function |
| `piasa composite SERIAL listen timeout=1000` | Wait for serial data (timeout in ms) |
| `piasa composite ETHERNET sendtarget` | Start the selected Ethernet mode |
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

## USB descriptors and Ethernet MAC addresses

Set descriptors on the composite device before applying it:

```sh
piasa composite vendor_id=0x1234 product_id=0x5678
piasa composite manufacturer="My Lab" product="PiAsA Test Gadget" serial=PIASA0002
piasa composite bcd_device=0x0101 bcd_usb=0x0200
```

Supported global properties are `vendor_id`, `product_id`, `manufacturer`, `product`, `serial`, `bcd_device`, `bcd_usb`, `device_class`, `device_subclass`, and `device_protocol`. Numeric descriptor values accept decimal or hexadecimal notation.

For ECM/RNDIS network functions, configure the device-side and host-side MAC addresses:

```sh
piasa composite network dev_mac_address=02:11:22:33:44:55 host_mac_address=02:11:22:33:44:66
```

The shorter `mac_address` alias sets the device-side address. MAC addresses must be valid six-byte hexadecimal addresses.

### Serial runtime commands

```sh
piasa composite console bandwidth=9600
piasa composite console send="hello!"
piasa composite console listen timeout=1000
```

The send/listen commands use the local gadget TTY (for example `/dev/ttyGS0`). The host must have opened its corresponding serial port. `listen` waits up to the supplied timeout in milliseconds and prints received bytes. The configured baud rate is applied to the local TTY; set the same rate in the host's serial application.

### Ethernet modes

Configure the USB Ethernet function's mode and start it after applying the composite gadget:

```sh
piasa composite network type=piasa-router dns_upstream=1.1.1.1
sudo piasa composite apply
sudo piasa composite network sendtarget
```

Supported mode names: `relay`, `peertopeer`, `pctorouter`, `loopback`, and `piasa-router`. The first `piasa-router` implementation assigns the USB-side Pi interface `192.168.7.1/24` and starts a UDP/TCP DNS forwarder on port 53. Configure the USB host with a static address in that subnet and DNS server `192.168.7.1`. DHCP and general IP routing are not included yet. Set `dns_upstream=1.1.1.1` to choose another resolver.

The other Ethernet modes are accepted as configuration values, but their forwarding/bridging runtime is not implemented in this initial release.

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

- PiAsA currently configures HID descriptors, but does not yet provide keyboard typing/key-combination or mouse movement/button action commands.
- `piasa-router` is currently DNS forwarding only. It does not provide DHCP, NAT, or general IP routing.
- Storage uses an existing image file. Do not modify the same backing image from the Pi and host simultaneously.
- UDC availability, supported function drivers, host OS compatibility, and board wiring vary.
- The initial release supports keyboard/mouse HID descriptors, serial, ECM/RNDIS networking, and mass storage. UVC webcam gadget support (screen, video-file, or image sources) is not implemented yet.
