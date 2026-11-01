import os
from pathlib import Path


# Generated desktop design tokens.
LIGHT_COLORS = {
    'bg': '#f6fbfd', 'surface': '#ffffff', 'text': '#11121f',
    'secondary': '#494e62', 'muted': '#5c6479', 'border': '#d3dee4',
    'action': '#0a7d33', 'hover': '#067329', 'tint': '#ebfff9',
    'error': '#b3261e', 'success': '#168f4b',
}
DARK_COLORS = {
    'bg': '#171d1a', 'surface': '#222a26', 'text': '#eef4f0',
    'secondary': '#c5d0c9', 'muted': '#9eada4', 'border': '#3b4941',
    'action': '#67cf83', 'hover': '#83e29d', 'tint': '#2a3a30',
    'error': '#ff9389', 'success': '#78d894',
}
COLORS = dict(LIGHT_COLORS)
FONT = 'Microsoft YaHei UI'


def colors_for(theme):
    return dict(DARK_COLORS if theme == 'dark' else LIGHT_COLORS)


def _preference_path():
    appdata = os.environ.get('APPDATA')
    root = Path(appdata) if appdata else Path.home() / '.djigraft'
    return root / 'DJI Graft' / 'ui-theme.txt' if appdata else root / 'ui-theme.txt'


def load_theme_preference(path=None):
    try:
        theme = Path(path or _preference_path()).read_text(encoding='utf-8').strip().lower()
    except OSError:
        return 'light'
    return theme if theme in ('light', 'dark') else 'light'


def save_theme_preference(theme, path=None):
    selected = theme if theme in ('light', 'dark') else 'light'
    preference = Path(path or _preference_path())
    preference.parent.mkdir(parents=True, exist_ok=True)
    preference.write_text(selected, encoding='utf-8')
