# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

VRGB controls RGB on ASUS Vivobook keyboards that expose the ITE5570 HID LampArray controller, by writing HID feature reports to `/dev/hidrawX` (no kernel patches, no daemon). Two parts:

- **Core** — `vrgb.py`: a single-file, **stdlib-only** CLI that is also an importable module (`vrgb`). Must stay dependency-free.
- **Suite** — `suite/vrgb_suite/`: optional PyQt6 GUI + tray + automation built on Core. It must never change how Core behaves.

## Commands

```sh
pytest                                         # tests (pytest config in pyproject.toml; no hardware needed)
pytest tests/test_core.py -k find_device       # single test / subset
python3 vrgb.py --debug status                 # run Core from checkout (needs hidraw access: `vrgb` group or sudo)
PYTHONPATH=.:suite python3 -m vrgb_suite       # run Suite from checkout without installing
./install.sh [core|suite]                      # copies vrgb.py -> /usr/local/bin/vrgb, udev rule, vrgb group, optional autostart
./uninstall.sh
```

`pyproject.toml` (package `vrgb`) and `suite/pyproject.toml` (package `vrgb-gui`) exist only for distro packaging; `install.sh` copies files directly instead.

## Architecture

**Core (`vrgb.py`)**
- The protocol is standard HID LampArray: the "firmware report" is `LampArrayControlReport` (autonomous mode), the "color report" is `LampRangeUpdateReport`. `find_device()` reads report IDs from each hidraw node's `report_descriptor` (`parse_lamparray_report_ids`).
- `SUPPORTED_DEVICES` (HID_ID → fallback report IDs, models, `rainbow_supported`, `required_modules`) holds verified devices; they win over unlisted LampArray devices, which are driven generically (`verified: False`, `lamp_id_end` from the attributes report). Verified devices keep their tested lamp range 0..0.
- `vrgb cycle` saves `cfg["cycle"]` (`{period, fps, pid}`) so `vrgb restore` resumes it; the running loop watches the config file and exits, re-applying the saved state, once another command owns the keyboard (`owns_cycle`, `hand_over`). Commands that set another mode must `cfg.pop("cycle")`. From the CLI, `cycle` / bare `rainbow` save the cycle and `start_cycle_service()` restarts `vrgb-restore.service` to run it; only without that service does the CLI run the loop itself.
- `hid_set_feature()` / `hid_get_feature()` issue `HIDIOCSFEATURE` / `HIDIOCGFEATURE` ioctls; `set_color()` / `set_firmware_mode()` build the reports.
- OEM rainbow goes through a different path: asus-nb-wmi debugfs (`/sys/kernel/debug/asus-nb-wmi`), hence requires root (`vrgb rainbow-oem on|off`; `rainbow on|off` is a deprecated alias).
- `cmd_*` functions are the public API used by both `main()` and the Suite (signature pattern `cmd_x(cfg, devinfo, ...)`). `main()` is guarded by `__name__ == "__main__"`; entry point is `run()`.
- Config: `~/.config/vrgb/config.json`. `get_real_home()` honours `SUDO_USER`/`PKEXEC_UID` so elevated runs use the invoking user's config. `save_config` preserves unknown keys (the Suite stores its own keys in the same file — see `sun.DEFAULTS`).

**Suite (`suite/vrgb_suite/`)** — `__init__.py`'s docstring is the design doc; read it first.
- `core.py` loads Core: `import vrgb` if packaged, else loads `/usr/bin/vrgb`, `/usr/local/bin/vrgb`, or the repo's `vrgb.py` by path. HID protocol/config logic stays in Core — don't duplicate it in the Suite.
- `worker.py` `DeviceWorker` (QThread) serializes all device I/O off the UI thread via a queue of `(op, args)`.
- On `PermissionError`, persisting actions fall back to `pkexec vrgb ...`, but **only ever a root-owned system copy of the CLI**, never a user-writable script. Live previews are skipped instead.
- Unified brightness: slider B is split into firmware backlight level F (`/sys/class/leds/asus::kbd_backlight` via logind, `system.py`) and HID intensity I with `(F/max)*(I/255) == B`.
- Rainbow: the worker starts Core's `vrgb cycle` as a detached process (`_start_cycle`) instead of looping in-process; with a saved cycle, same-color "color" ops are brightness changes (`cmd_brightness`), a new color replaces the rainbow, and power-on/login/sunset resume it.
- Automation runs in the tray process: idle dimming (`idle.py`: GNOME Mutter, Wayland ext-idle-notify-v1, X11 backends) touches only HID intensity, never saved config, and is skipped while a cycle is saved; daytime-off uses locally computed sun times (`sun.py`).

## Conventions

- Releases are automated by semantic-release (`.releaserc.json`, `.github/workflows/ci.yml`) from Conventional Commit messages; `scripts/build-release.sh` stamps the version into `vrgb.VERSION` and `vrgb_suite.__version__` and builds the release assets. Don't bump versions by hand.
- New devices: add the mapping, pin its bytes in `test_verified_device_bytes`, and list it in the README (see CONTRIBUTING.md).
- `releases/` holds frozen copies of `vrgb.py` up to v0.3.5; newer versions are GitHub release assets. Don't edit them.
- `packaging/` (udev rule, sysusers) and `systemd/`/`suite/data/` units are installed by `install.sh`; keep `uninstall.sh` symmetric when changing either.
