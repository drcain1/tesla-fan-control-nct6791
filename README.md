# Tesla external fan controller for Linux

Temperature-based PWM control for an external fan cooling a passively cooled NVIDIA
Tesla GPU. Inspired by [gwvr/tesla-fan-control](https://github.com/gwvr/tesla-fan-control).
This implementation uses the Linux `nct6791` hardware monitor and `nvidia-smi`.

The script finds the hardware monitor by its `name`, rather than relying on an
unstable `hwmonN` path. It uses only Python's standard library. By default it
prints a read-only preview; `--apply` is required to control a fan.

## Requirements

- Linux with an NCT6791D motherboard fan controller exposed as
  `/sys/class/hwmon/*/name = nct6791`
- NVIDIA driver with `nvidia-smi`
- Python 3
- Root privileges to change PWM settings
- An external GPU cooling fan connected to a controllable motherboard header

Some motherboards reserve the controller through ACPI. If the `nct6775` driver
detects the chip but exposes no PWM controls, investigate the kernel's ACPI
resource conflict before using `acpi_enforce_resources=lax`. That option permits
ACPI and the driver to access the same registers and should be evaluated for
the individual machine.

## Identify and preview

Find which `fanN_input` changes when the GPU fan changes speed, then verify
which `pwmN` controls it. **Do not assume the channel number from the header
label.** Verify the fan's PWM mode and minimum reliable running speed before
using the controller.

```sh
python3 tesla_fan_control.py --channel 1 --gpu 0 --once
```

`--gpu` accepts an `nvidia-smi` GPU index or UUID. The default is GPU index 0.
The default fan curve uses PWM 170 at or below 50°C, rising linearly to PWM 255
at 65°C. Adjust `--min-pwm`, `--min-temp`, and `--max-temp` for your hardware.

To run interactively after verifying the channel:

```sh
sudo python3 tesla_fan_control.py --channel 1 --gpu 0 --apply
```

On temperature-read failure, the controller requests full fan speed. On a
normal stop, SIGINT, SIGTERM, or Python exception, it restores the previous
control mode. A forced kill or system crash cannot execute cleanup; use the
systemd service's `ExecStopPost` as an additional fail-safe.

## Run at boot

Review and edit both example units for your GPU index, fan channel, fan curve,
and power limit **before enabling them**. The optional power-limit unit sets
GPU index 0 to 170 W; this value was chosen for one V100 installation and is
not a universal recommendation. Check the GPU's supported range with
`nvidia-smi -q -d POWER`.

```sh
sudo install -m 0755 tesla_fan_control.py /usr/local/bin/tesla_fan_control.py
sudo install -m 0644 tesla-fan-control.service /etc/systemd/system/
sudo install -m 0644 tesla-gpu-power-limit.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tesla-gpu-power-limit.service
sudo systemctl enable --now tesla-fan-control.service
```

The power-limit unit is ordered before the fan controller when both start in
the same boot transaction. The fan service restores full fan speed on stop or
failure, then restarts on failure. The program logs startup, recovery, and
temperature-read errors; repeated read errors are logged at most once every
five minutes. Check current temperature and RPM with `nvidia-smi` and
`sensors`.

Run the tests with:

```sh
python3 -m unittest discover -s . -p 'test_*.py'
```
