# PiAsA — Pi As A USB Everything

PiAsA is an nmcli-inspired command-line utility for configuring Linux USB composite gadgets on Raspberry Pi boards and other Linux systems with USB Device Controller (UDC) support.

It stores a declarative configuration first, then applies it to Linux configfs when explicitly requested.

> **Hardware note:** Gadget mode requires a USB port wired to a USB Device Controller and a kernel with configfs/libcomposite support. Not every Raspberry Pi USB port supports device mode. Raspberry Pi 5's USB-C power connector is not a general-purpose gadget port.

## Install

The installer sets up PiAsA system-wide. From the cloned repository:

```sh
bash install.sh
```

It creates a root-owned virtual environment at `/opt/piasa/venv` and installs the `piasa` command in `/usr/local/bin`. This makes `piasa` available both normally and through `sudo piasa`, without relying on the user's home-directory PATH. The installer asks for sudo permission when needed and does not modify system Python.

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

The `--first-time` option prepares the system prerequisites: it mounts configfs if needed, loads `libcomposite`, attempts to load `dwc2`, checks for a registered USB Device Controller, and creates the composite configuration. It does **not** activate the USB gadget yet. If no UDC is found, PiAsA prints board-specific guidance; the required device-tree/boot configuration and USB port selection may still need manual setup.

## Commands

| Command | Purpose |
| --- | --- |
| `piasa --init composite` | Create a composite configuration |\n| `sudo piasa --init composite --first-time` | Mount configfs, load libcomposite, check UDC, and create the configuration |
| `piasa composite show` | Display configuration, nmcli-style |
| `piasa composite add device NAME --type TYPE` | Add a named function |
| `piasa composite NAME key=value ...` | Set device properties |
| `piasa composite SERIAL bandwidth=9600` | Set the local CDC ACM TTY baud rate |
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

Example additional functions (using the short names from the CLI examples):

```sh
piasa composite add device serial --type serial
piasa composite serial template=serial
piasa composite serial bandwidth=9600
piasa composite serial send="hello!"
piasa composite serial listen timeout=1000

piasa composite add device eth --type ethernet
piasa composite eth template=ethernet
piasa composite eth type=relay relaywho=wlan0
piasa composite eth type=peertopeer
piasa composite eth type=pctorouter
piasa composite eth target=127.0.0.1:8080
piasa composite eth type=piasa-router dns_upstream=1.1.1.1
sudo piasa composite apply
sudo piasa composite eth sendtarget

piasa composite add device disk --type storage
piasa composite disk template=storage backing_file=/path/to/disk.img readonly=true
```

## HID keyboard input

After configuring a HID keyboard and applying the gadget, send input from the Pi:

    sudo piasa keyboard type "Hello world!"
    sudo piasa keyboard key ENTER
    sudo piasa keyboard key UP
    sudo piasa keyboard key CTRL+C
    sudo piasa keyboard key CTRL+ALT+DELETE
    sudo piasa keyboard key WIN
    sudo piasa keyboard key WIN+R

Arrow keys are UP, DOWN, LEFT, and RIGHT. Other named keys include ENTER, TAB, ESC, BACKSPACE, DELETE, HOME, END, PAGEUP, PAGEDOWN, and F1 through F12. Modifier names include CTRL, SHIFT, ALT, and GUI/WIN (also WINDOWS, SUPER, and META). A modifier can be tapped on its own, for example `piasa keyboard key WIN`, or combined with another key. For multiple keyboards, pass --device NAME. Root is required to write to /dev/hidgX. Typing supports basic US-layout ASCII only; non-ASCII characters are not translated. The host must be connected and ready to receive input.

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

Supported mode names: `relay`, `peertopeer`, `pctorouter`, `loopback`, and `piasa-router`. In this release, `piasa-router` is the only Ethernet mode with a runtime action: it assigns the USB-side Pi interface `192.168.7.1/24` and starts a UDP/TCP DNS forwarder on port 53. Configure the USB host with a static address in that subnet and DNS server `192.168.7.1`. DHCP and general IP routing are not included yet. Set `dns_upstream=1.1.1.1` to choose another resolver.

The other Ethernet modes are accepted and saved as configuration, but their packet-forwarding/bridging runtime is not implemented yet. `target` is reserved for the loopback server endpoint; `relaywho` selects the intended outgoing interface for relay/router modes.

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

- PiAsA supports keyboard typing and key taps/chords through /dev/hidgX; mouse movement/button action commands are not implemented.
- `piasa-router` is currently DNS forwarding only. It does not provide DHCP, NAT, or general IP routing. It binds TCP and UDP port 53 on the Pi-side USB interface; ensure another DNS service is not already using that address/port.
- Storage uses an existing image file. Do not modify the same backing image from the Pi and host simultaneously.
- UDC availability, supported function drivers, host OS compatibility, and board wiring vary.
- The initial release supports keyboard/mouse HID descriptors, serial, ECM/RNDIS networking, and mass storage. UVC webcam gadget support (screen, video-file, or image sources) is not implemented yet.


## Ethernet runtime modes

After applying the gadget, activate the selected mode with `sudo piasa composite ETH sendtarget`. Install `iproute2` and `nftables` first. PiAsA creates a dedicated `inet piasa` nftables table and removes only that table on `sudo piasa composite down`.

- `relay relaywho=wlan0`: routed/NAT forwarding from USB to the selected upstream interface. It is not a transparent layer-2 bridge; this avoids assuming Wi-Fi client interfaces support bridging.
- `pctorouter relaywho=eth0`: routes USB-host traffic through the Pi's upstream router with NAT. Set the USB host's default gateway to the Pi USB-side address (default `192.168.7.1`).
- `peertopeer relaywho=eth0`: configures the Pi's second interface as `192.168.8.1/30`; configure PC 2 as `192.168.8.2/30`. Configure PC addresses and return routes as needed.
- `loopback target=127.0.0.1:8080`: redirects TCP/UDP traffic arriving from the USB host to the specified local IPv4 server endpoint. The server must already be listening. Use the Pi's USB-side address instead of 127.0.0.1 if loopback routing is blocked by the host kernel.
- `piasa-router`: DNS forwarding only; it does not provide general IP routing or DHCP.

Set `usb_interface=usb0` if automatic USB interface detection is ambiguous. Set `ip_address=192.168.7.1/24` to change the USB-side address. These operations configure the Pi only; the connected PCs still need appropriate IP settings. The `down` command removes PiAsA's firewall table, restores the previous IPv4-forwarding setting, and removes addresses configured by PiAsA. Loopback currently redirects TCP and UDP, not arbitrary IP protocols.
