import tempfile
import unittest
from pathlib import Path


class ThemePreferenceTests(unittest.TestCase):
    def test_dark_palette_is_distinct_from_default_light_palette(self):
        from ui_theme import colors_for

        self.assertNotEqual(colors_for('dark')['bg'], colors_for('light')['bg'])
        self.assertEqual(colors_for('invalid')['bg'], colors_for('light')['bg'])

    def test_theme_preference_defaults_to_light_and_persists_dark(self):
        from ui_theme import load_theme_preference, save_theme_preference

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'theme.txt'

            self.assertEqual(load_theme_preference(path), 'light')
            save_theme_preference('dark', path)
            self.assertEqual(load_theme_preference(path), 'dark')

    def test_invalid_theme_preference_falls_back_to_light(self):
        from ui_theme import load_theme_preference

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'theme.txt'
            path.write_text('blue', encoding='utf-8')

            self.assertEqual(load_theme_preference(path), 'light')


if __name__ == '__main__':
    unittest.main()
