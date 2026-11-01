import unittest
from unittest.mock import patch


class FakeProcess:
    def __init__(self, stdout_lines):
        self.stdout = iter(stdout_lines)
        self.stderr = iter(())
        self.returncode = 0

    def wait(self):
        return self.returncode


class FfmpegProgressTests(unittest.TestCase):
    def test_progress_details_include_media_time_speed_and_percent(self):
        from dji_graft import parse_ffmpeg_progress

        details = parse_ffmpeg_progress(
            {'out_time': '00:00:02.000000', 'speed': '1.25x'}, 4)

        self.assertEqual(details['out_time_seconds'], 2)
        self.assertEqual(details['speed'], 1.25)
        self.assertEqual(details['percent'], 50)
        self.assertEqual(details['duration_seconds'], 4)

    def test_progress_details_accept_unknown_speed(self):
        from dji_graft import parse_ffmpeg_progress

        details = parse_ffmpeg_progress(
            {'out_time': '00:00:02.000000', 'speed': 'N/A'}, 4)

        self.assertIsNone(details['speed'])
        self.assertEqual(details['percent'], 50)

    def test_run_ffmpeg_preserves_percent_callback_and_reports_speed(self):
        from dji_graft import run_ffmpeg_with_progress

        proc = FakeProcess([
            'out_time=00:00:02.000000\n',
            'speed=1.25x\n',
            'progress=continue\n',
            'out_time=00:00:04.000000\n',
            'speed=2.00x\n',
            'progress=end\n',
        ])
        percentages = []
        details = []

        with patch('dji_graft.subprocess.Popen', return_value=proc):
            run_ffmpeg_with_progress(
                ['ffmpeg', '-i', 'input.mp4', 'output.mp4'], 4,
                progress_callback=percentages.append,
                progress_details_callback=details.append)

        self.assertEqual(percentages, [50, 100, 100])
        self.assertEqual([item['speed'] for item in details], [1.25, 2.0])
        self.assertEqual([item['percent'] for item in details], [50, 100])

    def test_hardware_conversion_forwards_detailed_progress_callback(self):
        import hardware_accel

        details = []
        command = ['ffmpeg', '-i', 'input.mp4', 'output.mp4']
        with patch('dji_graft.run_ffmpeg_with_progress') as run_progress:
            hardware_accel.run_conversion(
                command, 4, 'encode', None, False, details.append)

        run_progress.assert_called_once_with(
            command, 4, 'encode', None, details.append)


if __name__ == '__main__':
    unittest.main()
