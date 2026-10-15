#!/usr/bin/env python3
"""Temperature-based external fan controller, adapted from gwvr/tesla-fan-control."""
import argparse
import logging
import math
from pathlib import Path
import signal
import subprocess
import time

LOG = logging.getLogger(__name__)


def find_controller(root=Path('/sys/class/hwmon')):
    matches = [p for p in root.glob('hwmon*')
               if (p / 'name').read_text().strip() == 'nct6791']
    if len(matches) != 1:
        raise RuntimeError(f'Expected one nct6791 controller, found {len(matches)}')
    return matches[0]


def temperature(gpu):
    output = subprocess.check_output([
        'nvidia-smi', f'--id={gpu}', '--query-gpu=temperature.gpu',
        '--format=csv,noheader,nounits'], text=True, timeout=5)
    value = float(output.strip())
    if not math.isfinite(value) or not 0 <= value <= 120:
        raise ValueError(f'Invalid GPU temperature: {output!r}')
    return value


def calculate_pwm(temp, min_temp=50, max_temp=65, min_pwm=170):
    fraction = max(0, min(1, (temp - min_temp) / (max_temp - min_temp)))
    return int(min_pwm + fraction * (255 - min_pwm))


def write(path, value):
    path.write_text(str(value))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', type=int, choices=range(1, 7), default=1,
                        help='Verified Linux PWM channel for CHA_FAN1')
    parser.add_argument('--gpu', default='0',
                        help='nvidia-smi GPU index or UUID (default: 0)')
    parser.add_argument('--min-pwm', type=int, default=170,
                        help='Conservative initial floor; calibrate for the installed fan')
    parser.add_argument('--min-temp', type=float, default=50)
    parser.add_argument('--max-temp', type=float, default=65)
    parser.add_argument('--failsafe', action='store_true', help='Set selected fan to full speed and exit')
    parser.add_argument('--apply', action='store_true', help='Enable actual fan writes')
    parser.add_argument('--once', action='store_true', help='Preview one reading and exit')
    args = parser.parse_args()
    if not (1 <= args.min_pwm <= 255 and
            0 <= args.min_temp < args.max_temp <= 100):
        parser.error('Invalid fan curve')
    if args.apply and args.once:
        parser.error('--once is only supported for read-only previews')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    controller = find_controller()
    pwm = controller / f'pwm{args.channel}'
    enable = controller / f'pwm{args.channel}_enable'
    mode = controller / f'pwm{args.channel}_mode'
    for path in (pwm, enable, mode):
        if not path.is_file():
            raise RuntimeError(f'Missing control: {path}')
    if mode.read_text().strip() != '1':
        raise RuntimeError('Selected header is not configured for PWM mode')
    if args.failsafe:
        write(enable, 0)
        LOG.info('Selected fan set to full speed')
        return
    previous_pwm = pwm.read_text().strip()
    previous_enable = enable.read_text().strip()
    # Validate GPU access before modifying any control.
    temperature(args.gpu)
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    touched = False
    try:
        if args.apply:
            touched = True
            # This driver rejects PWM writes while in automatic mode.
            write(enable, 1)
            write(pwm, 255)
        if args.apply:
            LOG.info('Controlling GPU fan on channel %d', args.channel)
        failing = False
        last_error_log = 0
        while not stopping:
            try:
                temp = temperature(args.gpu)
            except (subprocess.SubprocessError, OSError, ValueError):
                if args.apply:
                    write(pwm, 255)
                now = time.monotonic()
                if not failing or now - last_error_log >= 300:
                    LOG.exception('Temperature unavailable; requesting full fan speed')
                    last_error_log = now
                failing = True
                if args.once:
                    raise
            else:
                target = calculate_pwm(temp, args.min_temp, args.max_temp, args.min_pwm)
                if args.apply:
                    write(pwm, target)
                if failing:
                    LOG.info('GPU temperature readings recovered')
                    failing = False
                if args.once:
                    LOG.info('%s channel=%d GPU=%.1fC PWM=%d',
                             'APPLY' if args.apply else 'PREVIEW', args.channel, temp, target)
            if args.once:
                break
            time.sleep(1)
    finally:
        if touched:
            # Restore firmware control on normal stop, SIGTERM, or exceptions.
            try:
                write(pwm, 255)
                try:
                    if previous_enable == '1':
                        write(pwm, previous_pwm)
                finally:
                    write(enable, previous_enable)
            except OSError:
                LOG.exception('Could not restore original fan control')
                raise


if __name__ == '__main__':
    main()
