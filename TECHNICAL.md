# VRGB Technical Reference

This document describes VRGB's internal architecture, HID LampArray
handling, Core/Suite boundary, state model, desktop integration, and
development-oriented behavior.

For normal installation and usage, start with
[`README.md`](README.md). For contribution rules and hardware-report
requirements, see [`CONTRIBUTING.md`](CONTRIBUTING.md).

## 1. Architecture

VRGB is intentionally split into two layers.

### VRGB Core

`vrgb.py` is the canonical implementation of keyboard discovery, HID
communication, configuration, profiles, effects, and restore behavior.

Core is designed to remain:

-   a single Python file;
-   Python standard-library only;
-   usable directly as the `vrgb` CLI;
-   importable by other frontends;
-   independent of any desktop environment;
-   usable without a permanently running daemon for static lighting.

The HID protocol, report IDs, device mappings, and configuration
semantics belong in Core. Frontends should reuse them rather than
reimplement them.

### VRGB Suite

`suite/vrgb_suite/` is the optional PyQt6 desktop layer.

The Suite imports and uses Core rather than maintaining a second HID
implementation. It provides:

-   the desktop window;
-   system tray integration;
-   live color preview;
-   unified brightness handling;
-   profile controls;
-   software-rainbow integration;
-   idle detection;
-   daytime automation;
-   startup/session integration.

Device I/O from the GUI is serialized through the Suite worker thread so
rapid UI updates do not compete for the HID device.

## 2. Control Path

For normal static lighting, the path is:

``` text
VRGB Core / Suite
        |
        v
    /dev/hidrawX
        |
        v
ITE5570 HID LampArray
        |
        v
 keyboard lighting
```

VRGB does not depend on a reverse-engineered Windows driver or a kernel
RGB patch. It uses the Linux HID subsystem and the LampArray reports
exposed by the keyboard.

Some verified systems still require an existing kernel module such as
`asus-nb-wmi` to initialize the hardware before the HID LampArray
accepts commands. That requirement is recorded in the verified mapping.

## 3. Device Discovery

VRGB scans available `hidraw` devices and selects compatible keyboard
controllers automatically.

Discovery has two useful levels:

1.  **Verified mapping** --- a HID ID that has been physically tested
    and is recorded with known models, fallback report IDs, and any
    required kernel modules.
2.  **Descriptor-discovered LampArray** --- a device whose HID report
    descriptor declares the standard LampArray usage page (`0x59`) even
    though its exact HID ID is not yet in the verified table.

Verified mappings are preferred because a HID descriptor cannot describe
everything VRGB needs to know about a laptop, especially model
confirmation and required kernel modules.

An unverified descriptor-discovered device can still be controlled when
its standard LampArray reports are usable. For such devices, Core reads
the LampArray Attributes report to obtain the reported lamp count and
uses the full reported range (`0` through `LampCount - 1`) for range
updates. `vrgb status` identifies the device as unverified so successful
hardware can later be promoted to a verified mapping.

Descriptor discovery is intentionally broader than the current verified
hardware table: Core does not require an unverified device to be an
ITE5570 or to use a known ASUS HID ID if the required LampArray reports
can be discovered. Turnkey installation and udev access are still
oriented around the ITE5570 hardware currently verified by the project.

Matching a known HID ID or exposing the expected LampArray reports does
**not** by itself guarantee compatibility. A laptop may require
model-specific controller initialization or other platform behavior that
the HID descriptor cannot describe. A device is considered verified only
after physical hardware testing.

## 4. Verified Devices and Report IDs

Current verified mappings:

  -------------------------------------------------------------------------------------------
  HID ID                     Confirmed       Firmware report     Color report Required module
                             models
  -------------------------- -------------- ---------------- ---------------- ---------------
  `0018:00000B05:000019B6`   ASUS Vivobook            `0x0B`           `0x05` `asus-nb-wmi`
                             S14 S5406SA /
                             S5406SA-WH79

  `0018:00000B05:00005570`   ASUS Vivobook            `0x46`           `0x45` ---
                             S16 M5606K,
                             S16 M5606WA,
                             S14 M5406WA
  -------------------------------------------------------------------------------------------

The firmware and color reports correspond to the HID LampArray control
and range-update reports used by these devices.

VRGB attempts to read the device's HID report descriptor and discover
the report IDs dynamically. The values in the verified mapping are
known-good fallbacks when descriptor reading or parsing is unavailable.

This means adding a verified device is not merely adding a laptop
marketing name. A mapping records hardware knowledge that runtime
descriptor discovery cannot provide, including tested model association,
known-good fallback report IDs, and any required kernel-module behavior.

## 5. Collecting Device Information

Useful identifiers:

``` bash
grep -H . /sys/class/hidraw/*/device/uevent | grep -E 'HID_ID|HID_NAME'
```

VRGB diagnostics:

``` bash
vrgb --debug status
```

Example identifiers from verified hardware:

``` text
HID_NAME=ITE5570:00 0B05:19B6
HID_ID=0018:00000B05:000019B6
```

``` text
HID_NAME=ITE5570:00 0B05:5570
HID_ID=0018:00000B05:00005570
```

When validating a new device, preserve the exact `HID_ID`, `HID_NAME`,
report IDs shown by debug output, laptop model, required modules, and
the behavior of static color, brightness, `auto`, `rainbow`, and
`cycle`.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the current mapping/test
procedure.

## 6. Static Color and Brightness

A normal static command such as:

``` bash
vrgb set 00aaff 70
```

updates the LampArray through Core and saves the resulting state.

Brightness is represented as a percentage for the user and converted to
the intensity expected by the device.

Low-level functions such as `set_color()` communicate with the device
without necessarily changing persistent state. CLI-level `cmd_*`
functions implement user-facing command semantics and update
configuration where appropriate.

This distinction is useful to the Suite: live preview can change the
keyboard while a slider or color control is moving without committing
every intermediate value to disk.

## 7. Firmware / Autonomous Mode

``` bash
vrgb auto on
vrgb auto off
```

Firmware/autonomous mode controls whether lighting is handed back to the
keyboard's firmware or controlled by VRGB.

This is separate from the removed model-specific OEM firmware-rainbow
experiment. Current VRGB uses its portable software rainbow/cycle
implementation for animated RGB effects.

## 8. Software Rainbow and Cycle

The simple effect command is:

``` bash
vrgb rainbow
```

It is the user-friendly entry point for the software color cycle.

Advanced control is available through:

``` bash
vrgb cycle [brightness] [period_seconds] [fps]
```

For example:

``` bash
vrgb cycle 50 10
```

The effect is implemented in software by sending successive colors
through the same Core HID path used for normal RGB control.

### State behavior

Rainbow/cycle is treated as a real saved lighting mode rather than a
disposable animation:

-   its state is stored in the VRGB configuration;
-   `vrgb restore` can resume it;
-   login restore can resume it after a session restart;
-   `brightness` can update its active brightness;
-   `set`, `auto`, or loading a profile takes over from it;
-   `off` pauses lighting until a later restore;
-   stopping an attached foreground cycle with Ctrl+C prevents that run
    from being treated as an active effect to resume.

The Suite's Rainbow toggle coordinates with Core rather than
implementing its own animation loop.

## 9. Configuration and Profiles

User state lives in:

``` text
~/.config/vrgb/config.json
```

Core owns the common configuration structure.

The file contains lighting state and profiles, and may also contain
Suite-specific settings. Core's configuration writer preserves keys it
does not own so frontends can share the file without destroying each
other's settings.

Configuration writes are atomic.

Profiles represent saved lighting state and are managed through:

``` bash
vrgb profile save NAME
vrgb profile load NAME
vrgb profile list
vrgb profile delete NAME
```

## 10. Restore and Session Startup

Static HID state may survive a reboot on some hardware but can return to
firmware defaults after a complete power cycle. VRGB therefore supports
restoring saved state when the user's graphical session begins.

The normal desktop path is XDG autostart.

The Suite option **Start VRGB in the tray at login** creates the
appropriate XDG autostart entry and launches:

``` text
vrgb-gui --tray
```

For sessions/compositors that do not honor XDG autostart, the session
configuration can launch `vrgb-gui --tray` directly.

An optional systemd user unit is retained for sessions where that
integration is appropriate, particularly environments that expose
`graphical-session.target`.

Avoid enabling multiple restore mechanisms without a reason. The current
design prefers one clear startup path instead of stacking KDE-specific,
XDG, and systemd restore jobs.

## 11. Suite Process Behavior

Useful Suite commands:

``` bash
vrgb-gui
vrgb-gui --foreground
vrgb-gui --tray
vrgb-gui --quit
```

Normal launch detaches from the invoking terminal. `--foreground` keeps
the process attached for debugging. `--tray` starts the application for
background/session use.

Only one Suite instance is intended to run per user session. Starting it
again signals/opens the existing instance rather than creating competing
keyboard controllers.

The Suite can remain useful even when a visible tray host is unavailable
because automation does not depend on the tray icon itself.

## 12. Suite I/O Worker and Live Preview

GUI controls can generate updates much faster than a person can
meaningfully commit settings. The Suite therefore separates live preview
from committed operations.

Device I/O is serialized through a worker thread.

During aggressive live color dragging, transient Linux HID/I2C refusal
errors can occur on some hardware. Preview writes use a narrow retry
path for transient `EIO` / `EREMOTEIO` failures and may drop an
intermediate preview update if the retry is still refused.

Committed operations are not silently discarded. Errors from operations
that represent an actual requested state change remain
visible/reportable.

This keeps the UI responsive without hiding failures that matter.

## 13. Unified Brightness in the Suite

On supported laptops, keyboard brightness has two layers:

1.  the firmware/kernel keyboard-backlight level, such as
    `asus::kbd_backlight`;
2.  the HID LampArray intensity controlled by VRGB.

If both are independently reduced, the keyboard can be effectively
double-dimmed. The Suite therefore presents one 0--100% brightness
control and coordinates the two layers.

Where available, the Suite observes firmware brightness changes so
hardware Fn brightness keys are reflected in the GUI. Kernel
`brightness_hw_changed` notification is preferred, with limited polling
while the window is open where necessary.

If the firmware LED node or required desktop privilege path is
unavailable, the Suite can fall back to HID-only brightness behavior.

The privilege path uses the system-installed VRGB executable rather than
running arbitrary user-controlled code as root. The Suite only accepts
the installed `/usr/bin/vrgb` or `/usr/local/bin/vrgb` path for this
elevated operation after verifying that the executable is root-owned and
not group- or world-writable. This prevents `pkexec` from being used to
elevate an arbitrary checkout or user-controlled replacement.

### Brightness state semantics

The Suite's unified brightness control and Core's persisted lighting
state are related but are not currently identical representations of
brightness. Core commands update the persisted Core brightness used by
`vrgb status`, while Suite brightness may coordinate the firmware
backlight layer and HID intensity without rewriting that same persisted
Core field on every change.

As a result, `vrgb status` can show the last Core-saved brightness even
when the Suite is currently presenting a different effective unified
brightness. This is a state-model distinction, not evidence that the
keyboard failed to apply the Suite brightness. Do not infer effective
Suite brightness solely from the persisted Core status value.

## 14. Idle Auto-Off

The Suite can turn the live keyboard intensity off after inactivity
while preserving the user's saved brightness. Activity restores the
light.

The feature is paused while software Rainbow is active.

Idle detection is selected for the current session:

  -----------------------------------------------------------------------
  Session/environment                 Backend
  ----------------------------------- -----------------------------------
  GNOME                               Mutter IdleMonitor over D-Bus

  KDE Plasma Wayland and compatible   `ext-idle-notify-v1`
  Wayland compositors

  X11 sessions                        XScreenSaver extension (`libXss`)
  -----------------------------------------------------------------------

Wayland support applies to compositors that implement
`ext-idle-notify-v1`, including environments such as KDE Plasma and
several wlroots-based compositors.

The implementation avoids adding a permanent polling loop where an
event-driven backend is available.

## 15. Daytime Automation

The Suite can keep the keyboard off between sunrise and sunset.

Sunrise/sunset is calculated locally; VRGB does not need a network
weather or geolocation service for this feature.

The Suite can suggest a location from the system timezone's reference
city. The configured location is then used for the local solar
calculation.

At sunset, lighting can return if it was otherwise supposed to be on.

## 16. Desktop and Tray Integration

The Suite installs a desktop entry and application icons through the
normal Linux desktop paths.

The canonical Suite icon is the VRGB three-cube mark. Raster hicolor
sizes are installed for desktop shells, while a bundled master PNG is
used as the preferred application/window/tray icon so branding does not
depend entirely on theme lookup.

The desktop file uses the `vrgb` icon name.

System tray support expects a StatusNotifierItem-capable host. KDE
Plasma and many Linux panels support this directly; GNOME generally
needs an AppIndicator-style extension.

KDE/DBusMenu tray implementations do not support arbitrary embedded
widgets in menus, so Suite tray controls use normal menu/submenu actions
rather than embedded sliders or color widgets.

## 17. Suspend, Resume, and HID Recovery

Laptop suspend/resume can invalidate or temporarily disturb HID access.

Core software effects explicitly recover from transient HID loss by
rediscovering the keyboard if the active `hidraw` device disappears or
re-enumerates. This allows a running software cycle to resume after
temporary device loss when the controller becomes available again.

The Suite worker serializes HID access and has the narrow transient retry
behavior described above for live preview, but it should not be
documented as providing a general device-reacquisition guarantee for
every committed Suite operation. Successful suspend/resume behavior has
been physically validated on supported hardware, but that validation is
not a substitute for a broader architectural guarantee.

Hardware acceptance testing should therefore always include
suspend/resume. A change that works from a fresh boot can still fail
after the device has been power-managed or re-enumerated.

## 18. Permissions

Normal VRGB use should not require running `vrgb` as root.

Installation creates the udev/device-access configuration needed for the
currently supported ITE5570 controller and maintains the `vrgb` group
fallback. Desktop `uaccess` can grant the active logged-in session
immediate access; newly added group membership becomes active after the
next login.

Because descriptor discovery in Core is broader than the project's
current ITE5570-oriented udev rule, an otherwise compatible unverified
LampArray device may still require an appropriate device-access rule
before it can be used as a normal non-root user.

The installer itself should be run as the normal user:

``` bash
./install.sh
```

It invokes `sudo` only for system-level installation steps.

The same rule applies to:

``` bash
./uninstall.sh
```

Running the entire installer/uninstaller under `sudo` changes the user
context and can place user-session files under root's home, which is
specifically guarded against.

## 19. Manual Core Installation

The project installer is preferred because it handles permissions,
mappings, desktop files, and optional Suite integration together.

For development or controlled packaging, the Core executable itself is
simply `vrgb.py` installed as `vrgb`, for example:

``` bash
sudo install -m 755 vrgb.py /usr/local/bin/vrgb
```

A functional manual installation must also provide appropriate access to
the matching `hidraw` device. Do not copy old udev examples from
historical VRGB releases; use the current repository's installer/rules
as the source of truth.

Distro/package maintainers should reproduce the current installer
behavior rather than depending on legacy v0.3.x paths or filenames.

## 20. Using Core as a Python Module

`vrgb.py` can be imported directly:

``` python
import vrgb

dev = vrgb.find_device()
cfg = vrgb.load_config()

vrgb.cmd_set(cfg, dev, "00aaff", 70)
vrgb.set_color(
    dev,
    255,
    0,
    0,
    vrgb.percent_to_intensity(40),
)
```

The `cmd_*` functions follow CLI semantics and generally update/save
persistent state.

Lower-level device functions such as `set_color()` and
`set_firmware_mode()` communicate with the keyboard without necessarily
committing a new user configuration.

Frontends should prefer these APIs over copying HID packet construction.

## 21. Repository Layout

Important paths:

``` text
vrgb.py                     Core CLI/module
install.sh                  Core/Suite installer
uninstall.sh                uninstaller
suite/
  vrgb_suite/
    app.py                  window, tray, entry point
    worker.py               serialized device I/O
    idle.py                 idle backends
    sun.py                  local solar calculations
    system.py               desktop/system helpers
    widgets.py              shared GUI widgets/icon handling
    core.py                 Suite bridge/import handling
  data/                     desktop integration and icon assets
  pyproject.toml            Suite packaging metadata
systemd/                    optional user restore/service files
tests/                      automated Core/Suite-facing tests
scripts/build-release.sh    manual release-asset helper
```

Exact filenames can evolve; inspect the current tree when packaging or
contributing.

## 22. Running from a Checkout

Core:

``` bash
python3 vrgb.py --debug status
```

Suite:

``` bash
PYTHONPATH=.:suite python3 -m vrgb_suite
```

The Suite requires PyQt6. Core itself remains standard-library only.

## 23. Tests and CI

Install pytest for development:

``` bash
pip install pytest
pytest -q
```

The test suite captures HID writes, so most automated tests do not
require a physical keyboard.

CI currently validates:

-   the supported Python matrix;
-   pytest;
-   Python source compilation;
-   matching Core/Suite version strings;
-   shell scripts with `shellcheck`.

CI intentionally has read-only repository permissions for normal
validation and does **not** create release tags or GitHub releases.

A green CI run is necessary but not sufficient for release. HID behavior
must still be physically tested on supported hardware.

## 24. Adding a Verified Device

The contribution procedure is intentionally evidence-driven.

1.  Collect `HID_ID` and `HID_NAME`.
2.  Run `vrgb --debug status`.
3.  Physically test static color, brightness, firmware mode, Rainbow,
    and Cycle.
4.  Add the mapping to Core with the discovered/verified report IDs,
    confirmed models, and required modules.
5.  Add exact report-byte coverage to the table-driven tests.
6.  When possible, add the device report descriptor to test data with a
    parser test.
7.  Add the device to the README verified-mapping table.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the canonical
contributor checklist.

## 25. Debugging Checklist

Start with:

``` bash
vrgb --debug status
```

Then inspect HID devices:

``` bash
grep -H . /sys/class/hidraw/*/device/uevent | grep -E 'HID_ID|HID_NAME'
```

For the verified `0B05:19B6` mapping, check:

``` bash
lsmod | grep asus_nb_wmi
```

and, if needed:

``` bash
sudo modprobe asus-nb-wmi
```

For Suite/session problems, run attached to the terminal:

``` bash
vrgb-gui --foreground
```

For startup problems, determine which mechanism is actually enabled
before adding another one. Prefer fixing the configured XDG/session path
over stacking duplicate restore jobs.

## 26. Release Model

VRGB releases are deliberate and manual.

The intended flow is:

``` text
pull request
    |
    v
automated CI
    |
    v
review / merge
    |
    v
physical hardware validation
    |
    v
manual version/tag/release
    |
    v
distribution packaging
```

`scripts/build-release.sh` remains a manual helper for release assets.
It is not an automatic release trigger. The active repository should not
carry semantic-release configuration or another mechanism that turns a
successful CI run into an automatic tag or GitHub release.

Historical release snapshots remain historical records. Current
documentation and packaging should describe the current architecture
rather than rewriting old releases to match it.

## 27. Design Principles

A few rules explain most VRGB architectural decisions:

-   **Core stays small and portable.**
-   **HID logic has one source of truth.**
-   **Suite adds desktop behavior; it does not fork Core behavior.**
-   **Verified hardware knowledge beats broad guesses.**
-   **A matching HID ID is evidence, not proof of compatibility.**
-   **Descriptor discovery expands compatibility without pretending
    untested hardware is verified.**
-   **Normal use should not require root.**
-   **CI validates software; real hardware validates releases.**
-   **Startup behavior should be predictable rather than duplicated
    across competing mechanisms.**
-   **Technical detail belongs here so the README can stay useful to
    normal users.**
