# Contributing to VRGB

Thanks for helping. Bug fixes, hardware reports, and new device mappings are all welcome.

## Ground rules

- **Core (`vrgb.py`) stays a single file using only the Python standard library**, and must keep working on Python 3.8. Anything that needs a GUI, desktop integration, or a third-party dependency belongs in the Suite (`suite/vrgb_suite/`).
- The Suite builds on Core and never changes how Core behaves. HID protocol, report IDs, and config logic live only in Core.

## Development

Run from a checkout without installing:

```sh
python3 vrgb.py --debug status
PYTHONPATH=.:suite python3 -m vrgb_suite
```

Run the tests (no keyboard needed, HID writes are captured):

```sh
pip install pytest
pytest                                   # all tests
pytest tests/test_core.py -k find_device # a subset
```

CI runs the tests on Python 3.8 to 3.13, checks that Core and Suite versions match, and runs `shellcheck -S warning` on the install scripts.

## Commit messages and releases

Releases are fully automated with semantic-release. Every push to `main` is analyzed, and commit messages following [Conventional Commits](https://www.conventionalcommits.org/) decide the next version:

| Commit | Release |
| --- | --- |
| `fix: ...` | patch (0.3.5 → 0.3.6) |
| `feat: ...` | minor (0.3.5 → 0.4.0) |
| `feat!: ...` | major (0.3.5 → 1.0.0) |
| `docs:`, `test:`, `ci:`, `chore:`, `refactor:` … | no release |

Commits that do not follow the format do not fail CI; they are simply ignored when computing the version. The release job stamps the version into `vrgb.py` and `vrgb_suite/__init__.py`, builds the packages with `scripts/build-release.sh`, and attaches them to the GitHub release, so do not bump versions by hand.

## Adding a new device

VRGB already drives any HID LampArray keyboard it finds, reading the report IDs from the device's report descriptor; `vrgb status` shows such a device as unverified. A verified mapping adds what the descriptor cannot tell: the confirmed models, required kernel modules, and OEM rainbow support. It needs a report from someone who has tested it on a real laptop.

1. Collect the device identifiers:

   ```sh
   grep -H . /sys/class/hidraw/*/device/uevent | grep -E 'HID_ID|HID_NAME'
   vrgb --debug status
   ```

2. Add an entry to `SUPPORTED_DEVICES` in `vrgb.py` with the firmware and color report IDs printed by `vrgb --debug status`, the confirmed models, and any required kernel modules.
3. Add the device's exact report bytes to `test_verified_device_bytes` in `tests/test_core.py`. The table-driven tests cover the new entry automatically. If you can, also add its descriptor (`/sys/class/hidraw/hidrawN/device/report_descriptor`) to `tests/data/` with a parser test.
4. List it under "Verified mappings" in `README.md`.

## Reporting hardware results

Open an issue with your laptop model, the `HID_ID` and `HID_NAME` lines above, the output of `vrgb --debug status`, and which commands worked (static color, brightness, `auto`, `rainbow`, `rainbow-oem`).
