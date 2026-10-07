"""VRGB Suite: worker."""

import copy
import queue
import subprocess
import sys

from PyQt6.QtCore import QThread, pyqtSignal


from . import sun
from .core import pkexec_target
from .system import KbdBacklight


# ----------------------------------------------------------------------------
# Worker thread: serializes all device I/O off the UI thread
# ----------------------------------------------------------------------------

class DeviceWorker(QThread):
    op_done = pyqtSignal(str, bool, str)        # op name, ok, human message
    device_status = pyqtSignal(object, str)     # devinfo dict or None, error message
    config_updated = pyqtSignal(dict)           # fresh config snapshot

    def __init__(self, mod, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.pkexec_bin = pkexec_target()
        self.q: "queue.Queue" = queue.Queue()
        self._devinfo = None
        self._running = True
        self._proc = None  # tracked pkexec subprocess, for shutdown

    # -- public API (called from the UI thread) --
    def submit(self, op, *args):
        self.q.put((op, args))

    def stop(self):
        self._running = False
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass
        self.q.put(("quit", ()))

    # -- internals (run on the worker thread) --
    def run(self):
        while self._running:
            op, args = self.q.get()      # blocks; stop() enqueues "quit" to wake us
            if op == "quit":
                break
            try:
                self._dispatch(op, args)
            except Exception as exc:  # never let the worker die
                self.op_done.emit(op, False, f"{type(exc).__name__}: {exc}")

    def _ensure_device(self):
        if self._devinfo is not None:
            return self._devinfo
        try:
            self._devinfo = self.mod.find_device()
            self.device_status.emit(self._devinfo, "")
        except SystemExit:
            self.device_status.emit(None, "VRGB keyboard not found")
            raise
        return self._devinfo

    def _cfg(self):
        return self.mod.load_config()

    def _emit_cfg(self, cfg):
        snap = dict(cfg)
        snap["profiles"] = copy.deepcopy(cfg.get("profiles", {}))
        self.config_updated.emit(snap)

    def _run_cli(self, cli_args):
        """Privileged fallback via pkexec (Polkit GUI password prompt)."""
        if not self.pkexec_bin:
            raise RuntimeError(
                "Privileged fallback unavailable: install the vrgb CLI system-wide "
                "(distro package or ./install.sh), then log out and back in."
            )
        self._proc = subprocess.Popen(
            ["pkexec", self.pkexec_bin, *cli_args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            out, err = self._proc.communicate(timeout=120)
            rc = self._proc.returncode
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.communicate()
            raise RuntimeError("pkexec timed out waiting for authorization")
        finally:
            self._proc = None
        if rc != 0:
            raise RuntimeError((err or out or "pkexec failed").strip())

    def _start_cycle(self, mod, cfg):
        """Start the saved (or default) rainbow through Core's own `cycle` command in
        a separate process: Core hands it to vrgb-restore.service when that is
        enabled, otherwise the process keeps running the cycle on its own, so the
        rainbow outlives the GUI either way. Returns an error message or None."""
        cycle = cfg.get("cycle") if isinstance(cfg.get("cycle"), dict) else {}
        percent = mod.get_saved_static_state(cfg)[3]
        proc = subprocess.Popen(
            [sys.executable, mod.__file__, "cycle", str(percent),
             str(cycle.get("period", mod.RAINBOW_PERIOD)), str(cycle.get("fps", 20))],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        try:
            _out, err = proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            return None   # still running: this process is driving the cycle
        return None if proc.returncode == 0 else (err.strip() or "vrgb cycle failed")

    # -- per-op handlers --
    def _dispatch(self, op, args):
        handler = getattr(self, f"_op_{op}", None)
        if handler is None:
            self.op_done.emit(op, False, f"unknown op '{op}'")
            return
        handler(self.mod, *args)

    def _op_detect(self, mod):
        try:
            self._ensure_device()
        except SystemExit:
            pass

    def _op_fwlevel(self, mod, level):
        if not KbdBacklight.set_level(level):
            self.op_done.emit("fwlevel", False, "Could not set keyboard backlight level")

    def _op_color(self, mod, hexcol, percent, persist):
        try:
            dev = self._ensure_device()
        except SystemExit:
            return
        cfg = self._cfg()
        if isinstance(cfg.get("cycle"), dict):
            if hexcol == cfg["color"]:
                # Same color: a brightness change, which the running rainbow reads
                # from the config. Brightness 0 stops it, so bring it back after.
                was_off = cfg["percent"] <= 0
                mod.cmd_brightness(cfg, dev, percent)
                if persist:
                    if was_off and percent > 0:
                        self._start_cycle(mod, cfg)
                    self._emit_cfg(self._cfg())
                return
            persist = True   # a new color replaces the rainbow right away
        try:
            if persist:
                cfg = self._cfg()
                mod.cmd_set(cfg, dev, hexcol, str(percent))
                self._emit_cfg(cfg)
                self.op_done.emit("color", True, f"Set #{hexcol}")
            else:
                r, g, b = mod.hex_to_rgb(hexcol)
                intensity = mod.percent_to_intensity(percent)
                mod.set_firmware_mode(dev, False)
                mod.set_color(dev, r, g, b, intensity)
        except PermissionError:
            if persist:
                self._run_cli(["set", hexcol, str(percent)])
                self._emit_cfg(self._cfg())
                self.op_done.emit("color", True, f"Set #{hexcol} (pkexec)")

    def _op_power(self, mod, on):
        try:
            dev = self._ensure_device()
        except SystemExit:
            return
        cfg = self._cfg()
        if on and isinstance(cfg.get("cycle"), dict):
            err = self._start_cycle(mod, cfg)
            self._emit_cfg(self._cfg())
            self.op_done.emit("power", err is None, err or "Rainbow on")
            return
        try:
            if on:
                mod.cmd_restore(cfg, dev)
            else:
                mod.cmd_off(cfg, dev)
            self._emit_cfg(cfg)
            self.op_done.emit("power", True, "On" if on else "Off")
        except PermissionError:
            self._run_cli(["restore" if on else "off"])
            self._emit_cfg(self._cfg())
            self.op_done.emit("power", True, ("On" if on else "Off") + " (pkexec)")

    def _op_auto(self, mod, on):
        try:
            dev = self._ensure_device()
        except SystemExit:
            return
        cfg = self._cfg()
        try:
            mod.cmd_auto(cfg, dev, "on" if on else "off")
            self._emit_cfg(cfg)
            self.op_done.emit("auto", True, "Firmware mode " + ("on" if on else "off"))
        except PermissionError:
            self._run_cli(["auto", "on" if on else "off"])
            self._emit_cfg(self._cfg())
            self.op_done.emit("auto", True, "Firmware mode " + ("on" if on else "off") + " (pkexec)")

    def _op_rainbow(self, mod, on):
        try:
            dev = self._ensure_device()
        except SystemExit:
            return
        cfg = self._cfg()
        try:
            mod.cmd_rainbow(cfg, dev, "on" if on else "off")
            self._emit_cfg(cfg)
            self.op_done.emit("rainbow", True, "Rainbow " + ("on" if on else "off"))
        except PermissionError:
            # The deprecated spelling: the root-owned system CLI may predate rainbow-oem.
            self._run_cli(["rainbow", "on" if on else "off"])
            self._emit_cfg(self._cfg())
            self.op_done.emit("rainbow", True, "Rainbow " + ("on" if on else "off") + " (pkexec)")
        except SystemExit:
            self.op_done.emit("rainbow", False, "OEM rainbow not supported on this device")

    def _op_cycle(self, mod, on):
        try:
            dev = self._ensure_device()
        except SystemExit:
            return
        cfg = self._cfg()
        if on:
            err = self._start_cycle(mod, cfg)
            self._emit_cfg(self._cfg())
            self.op_done.emit("cycle", err is None, err or "Rainbow on")
            return
        if not isinstance(cfg.get("cycle"), dict):
            return
        # Back to the saved static color; cmd_set also stops the running cycle.
        percent = str(mod.get_saved_static_state(cfg)[3])
        try:
            mod.cmd_set(cfg, dev, cfg["color"], percent)
            self._emit_cfg(cfg)
            self.op_done.emit("cycle", True, "Rainbow off")
        except PermissionError:
            self._run_cli(["set", cfg["color"], percent])
            self._emit_cfg(self._cfg())
            self.op_done.emit("cycle", True, "Rainbow off (pkexec)")

    SETTING_KEYS = ("idle_enabled", "idle_timeout_seconds", "day_off_enabled",
                    "latitude", "longitude")

    def _op_settings(self, mod, values):
        cfg = self._cfg()
        cfg.update({k: v for k, v in values.items() if k in self.SETTING_KEYS})
        cfg.update(sun.settings(cfg))    # validate/clamp the Suite keys
        mod.save_config(cfg)
        self._emit_cfg(cfg)
        self.op_done.emit("settings", True, "Settings saved")

    # Idle dim/restore only drive the HID intensity; the saved config is untouched.
    # They do nothing while the rainbow is the saved mode: its process would
    # overwrite a dimmed frame right away.
    def _op_idle_dim(self, mod):
        cfg = self._cfg()
        if cfg.get("autonomous") or cfg.get("cycle") or cfg.get("percent", 0) <= 0:
            return
        try:
            dev = self._ensure_device()
            r, g, b = mod.hex_to_rgb(cfg["color"])
            mod.set_firmware_mode(dev, False)
            mod.set_color(dev, r, g, b, 0)
        except (SystemExit, PermissionError):
            pass

    def _op_idle_restore(self, mod):
        cfg = self._cfg()
        if cfg.get("autonomous") or cfg.get("cycle") or cfg.get("percent", 0) <= 0:
            return
        try:
            dev = self._ensure_device()
            r, g, b = mod.hex_to_rgb(cfg["color"])
            mod.set_firmware_mode(dev, False)
            mod.set_color(dev, r, g, b, mod.percent_to_intensity(cfg["percent"]))
        except (SystemExit, PermissionError):
            pass

    def _op_login(self, mod):
        cfg = self._cfg()
        try:
            dev = self._ensure_device()
            if sun.day_off_active(cfg) and not cfg.get("autonomous"):
                # Only remember "we turned it off" if it was on.
                forced = cfg.get("day_forced_off") or cfg.get("percent", 0) > 0
                mod.cmd_off(cfg, dev)
                cfg["day_forced_off"] = forced
                mod.save_config(cfg)
            elif isinstance(cfg.get("cycle"), dict):
                cfg["day_forced_off"] = False
                mod.save_config(cfg)   # before the cycle saves its own pid
                self._start_cycle(mod, cfg)
                cfg = self._cfg()
            else:
                cfg["day_forced_off"] = False
                mod.cmd_restore(cfg, dev)
                mod.save_config(cfg)
        except (SystemExit, PermissionError):
            return
        self._emit_cfg(cfg)

    # Daytime off persists (like the Off button) and remembers that it did so, so
    # sunset only brings back a backlight the user actually had on.
    def _op_day_off(self, mod):
        cfg = self._cfg()
        if cfg.get("autonomous") or cfg.get("percent", 0) <= 0:
            return
        try:
            dev = self._ensure_device()
            mod.cmd_off(cfg, dev)
        except (SystemExit, PermissionError):
            return
        cfg["day_forced_off"] = True
        mod.save_config(cfg)
        self._emit_cfg(cfg)
        self.op_done.emit("day_off", True, "Daytime: backlight off until sunset")

    def _op_day_on(self, mod):
        cfg = self._cfg()
        if not cfg.get("day_forced_off"):
            return
        cfg["day_forced_off"] = False
        if isinstance(cfg.get("cycle"), dict):
            mod.save_config(cfg)   # before the cycle saves its own pid
            self._start_cycle(mod, cfg)
            cfg = self._cfg()
        else:
            if cfg.get("percent", 0) <= 0:
                try:
                    dev = self._ensure_device()
                    mod.cmd_restore(cfg, dev)
                except (SystemExit, PermissionError):
                    pass
            mod.save_config(cfg)
        self._emit_cfg(cfg)
        self.op_done.emit("day_on", True, "Backlight restored")

    def _op_profile_save(self, mod, name):
        cfg = self._cfg()
        mod.cmd_profile_save(cfg, name)
        self._emit_cfg(cfg)
        self.op_done.emit("profile_save", True, f"Saved profile '{name}'")

    def _op_profile_delete(self, mod, name):
        cfg = self._cfg()
        try:
            mod.cmd_profile_delete(cfg, name)
            self._emit_cfg(cfg)
            self.op_done.emit("profile_delete", True, f"Deleted profile '{name}'")
        except SystemExit:
            self.op_done.emit("profile_delete", False, f"Profile '{name}' not found")

    def _op_profile_load(self, mod, name):
        try:
            dev = self._ensure_device()
        except SystemExit:
            return
        cfg = self._cfg()
        try:
            mod.cmd_profile_load(cfg, dev, name)
            self._emit_cfg(cfg)
            self.op_done.emit("profile_load", True, f"Loaded profile '{name}'")
        except PermissionError:
            self._run_cli(["profile", "load", name])
            self._emit_cfg(self._cfg())
            self.op_done.emit("profile_load", True, f"Loaded profile '{name}' (pkexec)")
        except SystemExit:
            self.op_done.emit("profile_load", False, f"Profile '{name}' not found")


