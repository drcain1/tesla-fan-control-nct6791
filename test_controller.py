import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import tesla_fan_control as controller


class ControllerTests(unittest.TestCase):
    def test_curve_clamps(self):
        self.assertEqual(controller.calculate_pwm(20), 170)
        self.assertEqual(controller.calculate_pwm(80), 255)
        self.assertEqual(controller.calculate_pwm(57.5), 212)

    def test_controller_discovery_ignores_hwmon_index(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            device = root / 'hwmon9'
            device.mkdir()
            (device / 'name').write_text('nct6791')
            self.assertEqual(controller.find_controller(root), device)

    def test_temperature_failure_full_speed_and_exit_restores_mode(self):
        with tempfile.TemporaryDirectory() as d:
            device = Path(d)
            for name, value in [('pwm1','173'), ('pwm1_enable','5'), ('pwm1_mode','1')]:
                (device/name).write_text(value)
            writes = []
            original = controller.write
            def record(path, value):
                writes.append((path.name, str(value)))
                original(path, value)
            with patch('sys.argv', ['controller', '--apply']), \
                 patch.object(controller, 'find_controller', return_value=device), \
                 patch.object(controller, 'temperature', side_effect=[65, ValueError('missing')]), \
                 patch.object(controller, 'write', side_effect=record), \
                 patch.object(controller.signal, 'signal'), \
                 patch.object(controller.time, 'sleep', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    controller.main()
            self.assertEqual(writes[:2], [('pwm1_enable','1'), ('pwm1','255')])
            self.assertEqual(writes[2], ('pwm1','255'))
            self.assertEqual((device/'pwm1_enable').read_text(), '5')

    def test_repeated_temperature_failures_log_once(self):
        with tempfile.TemporaryDirectory() as d:
            device = Path(d)
            for name, value in [('pwm1','173'), ('pwm1_enable','5'), ('pwm1_mode','1')]:
                (device/name).write_text(value)
            with patch('sys.argv', ['controller', '--apply']), \
                 patch.object(controller, 'find_controller', return_value=device), \
                 patch.object(controller, 'temperature', side_effect=[65, ValueError('x'), ValueError('x')]), \
                 patch.object(controller.LOG, 'exception') as log_error, \
                 patch.object(controller.signal, 'signal'), \
                 patch.object(controller.time, 'sleep', side_effect=[None, KeyboardInterrupt]):
                with self.assertRaises(KeyboardInterrupt):
                    controller.main()
            self.assertEqual(log_error.call_count, 1)


if __name__ == '__main__':
    unittest.main()
