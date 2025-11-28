import subprocess
import sys
import locale
from utils.utils import get_workspace_path
from pathlib import Path
from typing import Optional, Tuple

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

def parse_shell_command(query: str) -> Tuple[bool, Optional[str]]:
    """
    解析是否为 shell 命令
    Args:
        query: 用户输入的查询字符串
    Returns:
        (is_shell_cmd, shell_command): 是否是 shell 命令，以及实际的命令
    """
    if query.startswith("shell "):
        command = query[6:].strip()
        return True, command if command else None
    return False, None

def execute_shell_command(command: str) -> dict:
    """
    执行 shell 命令并返回结构化结果
    Args:
        command: shell 命令
    Returns:
        {
            "success": bool,
            "command": str,
            "output": str
        }
    """
    result = sys_shell(command)
    is_error = result.startswith("Error:")
    return {
        "success": not is_error,
        "command": command,
        "output": result
    }