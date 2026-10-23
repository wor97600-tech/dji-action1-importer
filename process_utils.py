"""Process display settings only; leave commands, pipes and errors unchanged."""
import subprocess
import sys


def hidden_process_options():
    if sys.platform == 'win32':
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    return {}
