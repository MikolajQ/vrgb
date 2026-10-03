#!/usr/bin/env python3

import os
import sys
import json
import fcntl
import pwd
import time
import math
import datetime as _dt
from pathlib import Path

# ===== Debug =====

DEBUG = False


def debug(msg):
    if DEBUG:
        print(f"[debug] {msg}")


# ===== Constants =====

HIDIOCSFEATURE_BASE = 0xC0004806


def HIDIOCSFEATURE(length: int) -> int:
    return HIDIOCSFEATURE_BASE | (length << 16)


def get_real_home() -> Path:
    # Resolve the invoking user's home even when elevated, so config lives under
    # the real user's ~/.config and not /root. sudo sets SUDO_USER; pkexec scrubs
    # the environment but sets PKEXEC_UID.
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError:
            pass

    pkexec_uid = os.environ.get("PKEXEC_UID")
    if pkexec_uid:
        try:
            return Path(pwd.getpwuid(int(pkexec_uid)).pw_dir)
        except (KeyError, ValueError):
            pass

    return Path.home()


CONFIG_DIR = get_real_home() / ".config" / "vrgb"
CONFIG_FILE = CONFIG_DIR / "config.json"

SUPPORTED_DEVICES = {
    "0018:00000B05:000019B6": {
        "hid_name": "ITE5570:00 0B05:19B6",
        "model": "ASUS Vivobook S14 series (ITE5570 0x19B6)",
        "confirmed_models": [
            "ASUS Vivobook S14 (S5406SA)",
        ],
        "firmware_report_id": 0x0B,
        "color_report_id": 0x05,
        "rainbow_supported": True,
        "required_modules": ["asus-nb-wmi"],
    },
    "0018:00000B05:00005570": {
        "hid_name": "ITE5570:00 0B05:5570",
        "model": "ASUS Vivobook S series (ITE5570 0x5570)",
        "confirmed_models": [
            "ASUS Vivobook S16 (M5606K)",
            "ASUS Vivobook S16 (M5606WA)",
            "ASUS Vivobook S14 (M5406WA)",
        ],
        "firmware_report_id": 0x46,
        "color_report_id": 0x45,
        "rainbow_supported": False,
    },
}

HOST_BYTE = 0x00
FIRMWARE_BYTE = 0x01

ASUS_WMI_BASE = Path("/sys/kernel/debug/asus-nb-wmi")
ASUS_WMI_METHOD_ID = ASUS_WMI_BASE / "method_id"
ASUS_WMI_DEV_ID = ASUS_WMI_BASE / "dev_id"
ASUS_WMI_CTRL_PARAM = ASUS_WMI_BASE / "ctrl_param"
ASUS_WMI_DEVS = ASUS_WMI_BASE / "devs"

VERSION = "0.5.0"
PROJECT_URL = "https://github.com/MikolajQ/vrgb"
UPSTREAM_URL = "https://github.com/vrgb-dev/vrgb"

# ===== Utilities =====


def die(msg, exit_code=1):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(exit_code)


def clamp(n, lo, hi):
    return max(lo, min(hi, n))


def percent_to_intensity(p):
    p = clamp(int(p), 0, 100)
    return round(p * 255 / 100)


def hex_to_rgb(hexstr):
    hexstr = hexstr.strip().lower().replace("#", "")
    if len(hexstr) != 6:
        die("Color must be RRGGBB")

    try:
        r = int(hexstr[0:2], 16)
        g = int(hexstr[2:4], 16)
        b = int(hexstr[4:6], 16)
    except ValueError:
        die("Invalid hex color")

    return r, g, b


# ===== Config =====


def default_config():
    return {
        "color": "aa00ff",
        "percent": 100,
        "last_on_percent": 100,
        "autonomous": False,
        "profiles": {},
        "idle_timeout_seconds": 12,
        "idle_enabled": True,
        "day_off_enabled": False,
        "latitude": None,
        "longitude": None,
        "day_forced_off": False,
    }


def normalize_profile(profile, defaults):
    if not isinstance(profile, dict):
        return None

    normalized = {}

    try:
        r, g, b = hex_to_rgb(profile.get("color", defaults["color"]))
        normalized["color"] = f"{r:02x}{g:02x}{b:02x}"
    except SystemExit:
        normalized["color"] = defaults["color"]

    try:
        normalized["percent"] = clamp(
            int(profile.get("percent", defaults["percent"])), 0, 100
        )
    except (TypeError, ValueError):
        normalized["percent"] = defaults["percent"]

    normalized["autonomous"] = bool(
        profile.get("autonomous", defaults["autonomous"])
    )

    return normalized


def load_config():
    if not CONFIG_FILE.exists():
        return default_config()

    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except json.JSONDecodeError:
        backup = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + ".bad")
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.replace(backup)
            print(
                f"Warning: config file corrupted. Backed up to {backup} and using defaults.",
                file=sys.stderr,
            )
        except OSError:
            print(
                "Warning: config file corrupted. Could not back it up; using defaults.",
                file=sys.stderr,
            )
        return default_config()

    defaults = default_config()

    cfg.setdefault("color", defaults["color"])
    cfg.setdefault("percent", defaults["percent"])
    cfg.setdefault("last_on_percent", defaults["last_on_percent"])
    cfg.setdefault("autonomous", defaults["autonomous"])
    cfg.setdefault("profiles", defaults["profiles"])
    cfg.setdefault("idle_timeout_seconds", defaults["idle_timeout_seconds"])
    for key in ("idle_enabled", "day_off_enabled", "latitude", "longitude", "day_forced_off"):
        cfg.setdefault(key, defaults[key])

    try:
        r, g, b = hex_to_rgb(cfg["color"])
        cfg["color"] = f"{r:02x}{g:02x}{b:02x}"
    except SystemExit:
        cfg["color"] = defaults["color"]

    try:
        cfg["percent"] = clamp(int(cfg["percent"]), 0, 100)
    except (TypeError, ValueError):
        cfg["percent"] = defaults["percent"]

    try:
        cfg["last_on_percent"] = clamp(int(cfg["last_on_percent"]), 0, 100)
    except (TypeError, ValueError):
        cfg["last_on_percent"] = defaults["last_on_percent"]

    cfg["autonomous"] = bool(cfg["autonomous"])

    try:
        cfg["idle_timeout_seconds"] = clamp(int(cfg["idle_timeout_seconds"]), 1, 600)
    except (TypeError, ValueError):
        cfg["idle_timeout_seconds"] = defaults["idle_timeout_seconds"]

    cfg["idle_enabled"] = bool(cfg["idle_enabled"])
    cfg["day_off_enabled"] = bool(cfg["day_off_enabled"])
    cfg["day_forced_off"] = bool(cfg["day_forced_off"])
    try:
        cfg["latitude"] = clamp(float(cfg["latitude"]), -90.0, 90.0)
        cfg["longitude"] = clamp(float(cfg["longitude"]), -180.0, 180.0)
    except (TypeError, ValueError):
        cfg["latitude"] = cfg["longitude"] = None

    if not isinstance(cfg["profiles"], dict):
        cfg["profiles"] = {}
    else:
        normalized_profiles = {}
        for name, profile in cfg["profiles"].items():
            if not isinstance(name, str):
                continue
            normalized = normalize_profile(profile, defaults)
            if normalized is not None:
                normalized_profiles[name] = normalized
        cfg["profiles"] = normalized_profiles

    return cfg


def save_config(cfg):
    # Atomic replace: the GUI, `vrgb startup` and pkexec runs can write concurrently,
    # and a torn write would make load_config() discard the whole config.
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_name(f".{CONFIG_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    if os.geteuid() == 0:
        # Elevated (sudo/pkexec) run: keep the file owned by the real user.
        try:
            st = CONFIG_DIR.stat()
            os.chown(tmp, st.st_uid, st.st_gid)
        except OSError:
            pass
    os.replace(tmp, CONFIG_FILE)


# ===== Sun position (daytime-off) =====


def _sun_event_utc(date, lat, lon, rising, zenith=90.833):
    """UTC datetime of sunrise/sunset on `date` (Almanac for Computers algorithm).

    Returns True if the sun never sets that day (polar day), False if it never
    rises (polar night). Accuracy is ~1-2 minutes, plenty for a backlight.
    """
    rad, deg = math.radians, math.degrees
    n = date.timetuple().tm_yday
    lng_hour = lon / 15.0
    t = n + ((6 if rising else 18) - lng_hour) / 24.0
    m = 0.9856 * t - 3.289
    l = (m + 1.916 * math.sin(rad(m)) + 0.020 * math.sin(rad(2 * m)) + 282.634) % 360
    ra = deg(math.atan(0.91764 * math.tan(rad(l)))) % 360
    ra += (l // 90) * 90 - (ra // 90) * 90
    ra /= 15.0
    sin_dec = 0.39782 * math.sin(rad(l))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(rad(zenith)) - sin_dec * math.sin(rad(lat))) / (cos_dec * math.cos(rad(lat)))
    if cos_h > 1:
        return False
    if cos_h < -1:
        return True
    h = deg(math.acos(cos_h))
    h = (360 - h if rising else h) / 15.0
    ut = (h + ra - 0.06571 * t - 6.622 - lng_hour) % 24
    midnight = _dt.datetime(date.year, date.month, date.day, tzinfo=_dt.timezone.utc)
    return midnight + _dt.timedelta(hours=ut)


def sun_times(lat, lon, date=None):
    """(sunrise, sunset) as local-time datetimes, or a bool for polar day/night."""
    date = date or _dt.date.today()
    rise = _sun_event_utc(date, lat, lon, True)
    sett = _sun_event_utc(date, lat, lon, False)
    if isinstance(rise, bool) or isinstance(sett, bool):
        return rise if isinstance(rise, bool) else sett
    if sett < rise:
        sett += _dt.timedelta(days=1)
    return rise.astimezone(), sett.astimezone()


def is_daytime(lat, lon, now=None):
    now = now or _dt.datetime.now().astimezone()
    times = sun_times(lat, lon, now.date())
    if isinstance(times, bool):
        return times
    rise, sett = times
    return rise <= now < sett


def local_timezone_name():
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and "/" in tz and not tz.startswith("/"):
        return tz
    try:
        target = os.path.realpath("/etc/localtime")
    except OSError:
        return None
    marker = "/zoneinfo/"
    return target.split(marker, 1)[1] if marker in target else None


def _parse_iso6709(coord):
    """'+5215+02100' / '+405042-0735258' -> (lat, lon) in degrees."""
    split = max(coord.rfind("+"), coord.rfind("-"))
    out = []
    for part, deg_digits in ((coord[:split], 2), (coord[split:], 3)):
        sign = -1 if part[0] == "-" else 1
        digits = part[1:]
        d = int(digits[:deg_digits])
        mnt = int(digits[deg_digits:deg_digits + 2] or 0)
        sec = int(digits[deg_digits + 2:] or 0)
        out.append(sign * (d + mnt / 60 + sec / 3600))
    return round(out[0], 4), round(out[1], 4)


def guess_location():
    """Suggest (lat, lon, label) from the system timezone — offline and free.

    Uses the reference city of the tz database zone (e.g. Europe/Warsaw -> Warsaw).
    Returns None if the zone cannot be resolved.
    """
    tz = local_timezone_name()
    if not tz:
        return None
    for tab in ("/usr/share/zoneinfo/zone1970.tab", "/usr/share/zoneinfo/zone.tab"):
        try:
            with open(tab, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("#"):
                        continue
                    cols = line.rstrip("\n").split("\t")
                    if len(cols) >= 3 and cols[2] == tz:
                        lat, lon = _parse_iso6709(cols[1])
                        return lat, lon, tz
        except (OSError, ValueError, IndexError):
            continue
    return None


def day_off_active(cfg, now=None):
    """True when the daytime-off option is on, a location is set and it is day."""
    if not cfg.get("day_off_enabled") or cfg.get("latitude") is None:
        return False
    return is_daytime(cfg["latitude"], cfg["longitude"], now)


# Config semantics:
#   color            -> saved static RGB hex used for host/manual restore
#   percent          -> current intended brightness, may be 0 after `off`
#   last_on_percent  -> last known non-zero brightness for restore behavior
#   autonomous       -> whether firmware/autonomous mode should be preserved
#   profiles         -> named snapshots of color / percent / autonomous

def get_saved_static_state(cfg):
    r, g, b = hex_to_rgb(cfg["color"])

    p = int(cfg.get("percent", 100))
    if p <= 0:
        p = int(cfg.get("last_on_percent", 100))
        if p <= 0:
            p = 100

    p = clamp(p, 0, 100)
    intensity = percent_to_intensity(p)

    return r, g, b, p, intensity


# ===== Kernel Modules =====


def module_loaded(name: str) -> bool:
    # Linux exposes module names under /sys/module with hyphens converted to underscores.
    # Example: asus-nb-wmi -> /sys/module/asus_nb_wmi
    return Path(f"/sys/module/{name.replace('-', '_')}").exists()


def ensure_required_modules(devinfo):
    missing = [
        module
        for module in devinfo.get("required_modules", [])
        if not module_loaded(module)
    ]

    if not missing:
        return

    mods = " ".join(missing)
    first = missing[0]

    die(
        "Required kernel module missing: "
        + ", ".join(missing)
        + "\n\nThis device may ignore HID LampArray commands until the module is loaded."
        + "\n\nLoad once:\n"
        + f"  sudo modprobe {mods}"
        + "\n\nLoad at boot:\n"
        + f"  echo {first} | sudo tee /etc/modules-load.d/{first}.conf"
    )


# ===== HID =====


def find_device():
    base = Path("/sys/class/hidraw")

    debug(f"Config file: {CONFIG_FILE}")

    if not base.exists():
        die("No hidraw devices found")

    best_match = None
    best_score = -1
    best_reason = "no match"

    for dev in sorted(base.iterdir()):
        uevent = dev / "device" / "uevent"

        if not uevent.exists():
            debug(f"{dev.name}: missing uevent")
            continue

        txt = uevent.read_text(errors="ignore")

        hid_id = None
        hid_name = None

        for line in txt.splitlines():
            if line.startswith("HID_ID="):
                hid_id = line.split("=", 1)[1].strip()
            elif line.startswith("HID_NAME="):
                hid_name = line.split("=", 1)[1].strip()

        score = -1
        reason = "no match"
        profile = None

        if hid_id in SUPPORTED_DEVICES:
            profile = SUPPORTED_DEVICES[hid_id]
            score = 100
            reason = "exact HID_ID match"
        else:
            for supported_hid_id, supported in SUPPORTED_DEVICES.items():
                if hid_name == supported["hid_name"]:
                    profile = supported
                    score = 90
                    reason = f"exact HID_NAME match ({supported_hid_id})"
                    break

        debug(
            f"{dev.name}: hid_id={hid_id} hid_name={hid_name} "
            f"score={score} reason={reason}"
        )

        if score > best_score and profile is not None:
            best_score = score
            best_reason = reason
            best_match = {
                "path": f"/dev/{dev.name}",
                "hid_id": hid_id,
                "hid_name": hid_name,
                "model": profile["model"],
                "confirmed_models": profile.get("confirmed_models", []),
                "firmware_report_id": profile["firmware_report_id"],
                "color_report_id": profile["color_report_id"],
                "rainbow_supported": profile.get("rainbow_supported", False),
                "required_modules": profile.get("required_modules", []),
            }

    if best_match:
        debug(f"Selected device: {best_match['path']} ({best_reason})")
        debug(
            "Using report IDs: "
            f"firmware=0x{best_match['firmware_report_id']:02X} "
            f"color=0x{best_match['color_report_id']:02X}"
        )
        debug(f"Matched model: {best_match['model']}")
        if best_match.get("required_modules"):
            debug("Required modules: " + ", ".join(best_match["required_modules"]))
        ensure_required_modules(best_match)
        return best_match

    die("VRGB HID device not found")


def hid_set_feature(dev_path, report_id, payload_bytes):
    buf = bytes([report_id]) + payload_bytes
    debug(
        f"hid_set_feature dev={dev_path} report=0x{report_id:02X} "
        f"payload={payload_bytes.hex()}"
    )
    fd = os.open(dev_path, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.ioctl(fd, HIDIOCSFEATURE(len(buf)), buf)
    finally:
        os.close(fd)


def set_firmware_mode(devinfo, enabled: bool):
    debug(f"set_firmware_mode enabled={enabled}")
    hid_set_feature(
        devinfo["path"],
        devinfo["firmware_report_id"],
        bytes([FIRMWARE_BYTE if enabled else HOST_BYTE]),
    )


def set_color(devinfo, r, g, b, intensity):
    debug(f"set_color r={r} g={g} b={b} intensity={intensity}")

    payload = bytes(
        [
            0x01,
            0x00,
            0x00,
            0x00,
            0x00,
            clamp(r, 0, 255),
            clamp(g, 0, 255),
            clamp(b, 0, 255),
            clamp(intensity, 0, 255),
        ]
    )

    hid_set_feature(devinfo["path"], devinfo["color_report_id"], payload)


# ===== OEM Rainbow =====


def asus_wmi_write(method_id: str, dev_id: str, ctrl_param: str):
    ASUS_WMI_METHOD_ID.write_text(method_id)
    ASUS_WMI_DEV_ID.write_text(dev_id)
    ASUS_WMI_CTRL_PARAM.write_text(ctrl_param)

    try:
        _ = ASUS_WMI_DEVS.read_text(errors="ignore")
    except OSError as e:
        debug(f"ASUS WMI devs read failed: {e}")
        die("OEM rainbow not available: ASUS WMI exposed no usable device.")


def asus_wmi_rainbow(enable: bool):
    debug(f"asus_wmi_rainbow enable={enable}")

    if not ASUS_WMI_BASE.exists():
        die("OEM rainbow not supported on this system.")

    for p in (
        ASUS_WMI_METHOD_ID,
        ASUS_WMI_DEV_ID,
        ASUS_WMI_CTRL_PARAM,
        ASUS_WMI_DEVS,
    ):
        if not p.exists():
            die("OEM rainbow interface incomplete.")

    asus_wmi_write(
        "0x00000001",
        "0x0005002f",
        "0x00000000" if enable else "0x00000001",
    )


# ===== Profiles =====


def normalize_profile_name(name):
    name = name.strip()
    if not name:
        die("Profile name cannot be empty")
    return name


def get_profiles(cfg):
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict):
        cfg["profiles"] = {}
        profiles = cfg["profiles"]
    return profiles


def apply_profile(cfg, devinfo, profile, save=True):
    color = profile["color"]
    percent = clamp(int(profile["percent"]), 0, 100)
    autonomous = bool(profile["autonomous"])

    debug(f"apply_profile color={color} percent={percent} autonomous={autonomous}")

    cfg["color"] = color
    cfg["percent"] = percent
    if percent > 0:
        cfg["last_on_percent"] = percent
    cfg["autonomous"] = autonomous

    if autonomous:
        set_firmware_mode(devinfo, True)
    else:
        r, g, b = hex_to_rgb(color)
        intensity = percent_to_intensity(percent)
        set_firmware_mode(devinfo, False)
        set_color(devinfo, r, g, b, intensity)

    if save:
        save_config(cfg)


def cmd_profile_save(cfg, name):
    name = normalize_profile_name(name)
    profiles = get_profiles(cfg)

    profiles[name] = {
        "color": cfg["color"],
        "percent": cfg["percent"],
        "autonomous": cfg["autonomous"],
    }

    save_config(cfg)
    print(f"Saved profile: {name}")


def cmd_profile_load(cfg, devinfo, name):
    name = normalize_profile_name(name)
    profiles = get_profiles(cfg)

    if name not in profiles:
        die(f"Profile not found: {name}")

    apply_profile(cfg, devinfo, profiles[name], save=True)
    print(f"Loaded profile: {name}")


def cmd_profile_list(cfg):
    profiles = get_profiles(cfg)

    if not profiles:
        print("No profiles saved.")
        return

    print("Profiles:")
    for name in sorted(profiles):
        print(f"  {name}")


def cmd_profile_delete(cfg, name):
    name = normalize_profile_name(name)
    profiles = get_profiles(cfg)

    if name not in profiles:
        die(f"Profile not found: {name}")

    del profiles[name]
    save_config(cfg)
    print(f"Deleted profile: {name}")


# ===== Commands =====


def cmd_about():
    print(
        r"""
                 _
__   ___ __ __ _| |__
\ \ / / '__/ _` | '_ \
 \ V /| | | (_| | |_) |
  \_/ |_|  \__, |_.__/
           |___/

RGB control for ASUS HID LampArray keyboards

Version: """
        + VERSION
        + """
"""
        + PROJECT_URL
        + " (maintained fork)\nOriginal project: "
        + UPSTREAM_URL
        + """

No kernel mods. No daemon. Just HID.
"""
    )


def cmd_status(cfg, devinfo):
    print("Device:", devinfo["path"])
    print("Model:", devinfo["model"])
    print("HID ID:", devinfo["hid_id"])

    confirmed_models = devinfo.get("confirmed_models", [])
    if confirmed_models:
        print("Confirmed on:", ", ".join(confirmed_models))

    print(
        "OEM rainbow:",
        "supported" if devinfo.get("rainbow_supported", False) else "not supported / unknown",
    )

    required_modules = devinfo.get("required_modules", [])
    if required_modules:
        print("Required modules:", ", ".join(required_modules))

    print("Saved color:", "#" + cfg["color"])
    print("Saved brightness:", cfg["percent"], "%")
    print("Last-on brightness:", cfg["last_on_percent"], "%")
    print("Saved mode:", "firmware/autonomous" if cfg["autonomous"] else "host/static")
    debug("status complete")


def cmd_set(cfg, devinfo, color, percent=None):
    r, g, b = hex_to_rgb(color)

    if percent is None:
        percent = cfg["percent"]

    percent = clamp(int(percent), 0, 100)
    intensity = percent_to_intensity(percent)
    debug(f"cmd_set color={color} percent={percent} intensity={intensity}")

    set_firmware_mode(devinfo, False)
    set_color(devinfo, r, g, b, intensity)

    cfg["color"] = color.replace("#", "").lower()
    cfg["percent"] = percent
    if percent > 0:
        cfg["last_on_percent"] = percent
    cfg["autonomous"] = False
    save_config(cfg)


def cmd_brightness(cfg, devinfo, percent):
    r, g, b = hex_to_rgb(cfg["color"])

    percent = clamp(int(percent), 0, 100)
    intensity = percent_to_intensity(percent)
    debug(f"cmd_brightness percent={percent} intensity={intensity}")

    set_firmware_mode(devinfo, False)
    set_color(devinfo, r, g, b, intensity)

    cfg["percent"] = percent
    if percent > 0:
        cfg["last_on_percent"] = percent
    cfg["autonomous"] = False
    save_config(cfg)


def cmd_auto(cfg, devinfo, state):
    firmware_on = state == "on"
    debug(f"cmd_auto state={state}")

    if firmware_on:
        set_firmware_mode(devinfo, True)
        cfg["autonomous"] = True
        save_config(cfg)
    else:
        r, g, b, p, intensity = get_saved_static_state(cfg)
        debug(f"cmd_auto off -> restore percent={p} intensity={intensity}")
        set_firmware_mode(devinfo, False)
        set_color(devinfo, r, g, b, intensity)
        cfg["percent"] = p
        cfg["autonomous"] = False
        save_config(cfg)


def cmd_rainbow(cfg, devinfo, state):
    enable = state == "on"
    debug(f"cmd_rainbow state={state}")

    if not devinfo.get("rainbow_supported", False):
        if enable:
            die(
                "OEM rainbow is not supported for this device mapping. "
                "Static HID color control should still work."
            )

        r, g, b, p, intensity = get_saved_static_state(cfg)
        debug(
            "cmd_rainbow off on unsupported device -> "
            f"restore percent={p} intensity={intensity}"
        )
        set_firmware_mode(devinfo, False)
        set_color(devinfo, r, g, b, intensity)
        cfg["percent"] = p
        cfg["autonomous"] = False
        save_config(cfg)
        print("OEM rainbow is not supported for this device mapping; restored saved static state.")
        return

    if enable:
        set_firmware_mode(devinfo, True)
        asus_wmi_rainbow(True)
        cfg["autonomous"] = True
        save_config(cfg)
    else:
        asus_wmi_rainbow(False)
        r, g, b, p, intensity = get_saved_static_state(cfg)
        debug(f"cmd_rainbow off -> restore percent={p} intensity={intensity}")
        set_firmware_mode(devinfo, False)
        set_color(devinfo, r, g, b, intensity)
        cfg["percent"] = p
        cfg["autonomous"] = False
        save_config(cfg)


def cmd_off(cfg, devinfo):
    r, g, b = hex_to_rgb(cfg["color"])
    debug("cmd_off")

    p = int(cfg.get("percent", 100))
    if p > 0:
        cfg["last_on_percent"] = p

    set_firmware_mode(devinfo, False)
    set_color(devinfo, r, g, b, 0)

    cfg["percent"] = 0
    cfg["autonomous"] = False
    save_config(cfg)


def cmd_restore(cfg, devinfo):
    if cfg.get("autonomous", False):
        debug("cmd_restore autonomous=True -> keep firmware mode")
        set_firmware_mode(devinfo, True)
        return

    r, g, b, p, intensity = get_saved_static_state(cfg)
    debug(f"cmd_restore percent={p} intensity={intensity}")

    set_firmware_mode(devinfo, False)
    set_color(devinfo, r, g, b, intensity)

    cfg["percent"] = p
    cfg["autonomous"] = False
    save_config(cfg)


def cmd_startup(cfg):
    """Login handler: restore the saved lighting, honouring the daytime-off option.

    If "day_off_enabled" is set and the sun is up at the configured location, the
    backlight is switched off (remembered via "day_forced_off" so it comes back at
    sunset / next night login). Otherwise the saved state is restored.
    """
    devinfo = find_device()
    if cfg.get("autonomous", False):
        cmd_restore(cfg, devinfo)
        return

    if day_off_active(cfg):
        print("[vrgb-startup] DAY: backlight off (daytime-off option)")
        # Only remember "we turned it off" if it was on; a user-chosen 0 % stays 0 %.
        forced = cfg.get("day_forced_off") or cfg.get("percent", 0) > 0
        cmd_off(cfg, devinfo)
        cfg["day_forced_off"] = forced
        save_config(cfg)
    else:
        print("[vrgb-startup] restoring saved state")
        cfg["day_forced_off"] = False
        cmd_restore(cfg, devinfo)

    s = load_config()
    print(f"Saved color: #{s.get('color', '??????')}")
    print(f"Saved brightness: {s.get('percent', 0)} %")
    print(f"Last-on brightness: {s.get('last_on_percent', 0)} %")


# ===== Main =====


def main():
    global DEBUG

    args = sys.argv[1:]

    if args and args[0] == "--debug":
        DEBUG = True
        args = args[1:]

    if len(args) < 1:
        print(
            """Usage:
  vrgb status
  vrgb set RRGGBB [percent]
  vrgb brightness 0-100
  vrgb auto on|off
  vrgb rainbow on|off
  vrgb off
  vrgb restore
  vrgb startup          # login restore; off while the sun is up if day-off is enabled
  vrgb profile save NAME
  vrgb profile load NAME
  vrgb profile list
  vrgb profile delete NAME
  vrgb about

----------------------------------------
Tip: use --debug before the command for diagnostic output
Example: vrgb --debug status
"""
        )
        sys.exit(1)

    cfg = load_config()
    cmd = args[0]

    known_commands = {
        "status",
        "set",
        "brightness",
        "auto",
        "rainbow",
        "off",
        "restore",
        "profile",
        "startup",
        "about",
    }

    if cmd not in known_commands:
        die("Unknown command")

    if cmd == "status":
        devinfo = find_device()
        cmd_status(cfg, devinfo)

    elif cmd == "set":
        if len(args) < 2:
            die("Missing color")
        devinfo = find_device()
        percent = args[2] if len(args) > 2 else None
        cmd_set(cfg, devinfo, args[1], percent)

    elif cmd == "brightness":
        if len(args) < 2:
            die("Missing percent")
        devinfo = find_device()
        cmd_brightness(cfg, devinfo, args[1])

    elif cmd == "auto":
        if len(args) < 2 or args[1] not in ["on", "off"]:
            die("auto requires 'on' or 'off'")
        devinfo = find_device()
        cmd_auto(cfg, devinfo, args[1])

    elif cmd == "rainbow":
        if len(args) < 2 or args[1] not in ["on", "off"]:
            die("rainbow requires 'on' or 'off'")
        devinfo = find_device()
        cmd_rainbow(cfg, devinfo, args[1])

    elif cmd == "off":
        devinfo = find_device()
        cmd_off(cfg, devinfo)

    elif cmd == "restore":
        devinfo = find_device()
        cmd_restore(cfg, devinfo)

    elif cmd == "profile":
        if len(args) < 2:
            die("profile requires a subcommand: save, load, list, or delete")

        subcmd = args[1]

        if subcmd == "save":
            if len(args) < 3:
                die("profile save requires a name")
            cmd_profile_save(cfg, args[2])
        elif subcmd == "load":
            if len(args) < 3:
                die("profile load requires a name")
            devinfo = find_device()
            cmd_profile_load(cfg, devinfo, args[2])
        elif subcmd == "list":
            cmd_profile_list(cfg)
        elif subcmd == "delete":
            if len(args) < 3:
                die("profile delete requires a name")
            cmd_profile_delete(cfg, args[2])
        else:
            die("profile requires a subcommand: save, load, list, or delete")

    elif cmd == "startup":
        cmd_startup(cfg)

    elif cmd == "about":
        cmd_about()

    else:
        die("Unknown command")


if __name__ == "__main__":
    try:
        main()
    except PermissionError as e:
        path = getattr(e, "filename", None)
        if path and str(path).startswith(str(ASUS_WMI_BASE)):
            die("Permission denied to ASUS WMI debugfs. OEM rainbow requires sudo/root.")
        die("Permission denied to HID device. Run with sudo or install a udev rule.")
