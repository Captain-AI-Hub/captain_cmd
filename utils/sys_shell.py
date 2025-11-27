import subprocess
import sys
import locale
from utils.utils import get_workspace_path
from pathlib import Path

def _get_shell_encoding() -> str:
    """Get the appropriate encoding for shell output."""
    if sys.platform == 'win32':
        # On Windows, use the console output code page (usually GBK for Chinese Windows)
        import ctypes
        try:
            return f'cp{ctypes.windll.kernel32.GetOEMCP()}'
        except Exception:
            return locale.getpreferredencoding(False)
    return 'utf-8'

def sys_shell(
    command: str
) -> str:
    try:
        encoding = _get_shell_encoding()
        result = subprocess.run(
            command,
            shell=True,
            cwd=Path(get_workspace_path()).resolve(),   # 使用绝对路径
            capture_output=True,
            text=True,
            encoding=encoding,
            errors='replace',  # Handle encoding errors gracefully
            timeout=30
        )
        if result.returncode == 0:
            return result.stdout if result.stdout else "(no output)"
        else:
            return f"Error: {result.stderr}" if result.stderr else f"Error: Command failed with code {result.returncode}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr}"
    except Exception as e:
        return f"Error: {str(e)}"