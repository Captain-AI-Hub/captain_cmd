"""
Shell Prompt utilities using prompt_toolkit
提供命令补全、历史记录等功能
"""
import os
import sys
from pathlib import Path
from typing import List, Optional, Callable, Set

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import (
    Completer, Completion, WordCompleter, 
    NestedCompleter, merge_completers
)
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding import KeyBindings

from utils.utils import get_workspace_path, list_prompt_templates


def get_system_commands() -> Set[str]:
    """
    从系统 PATH 环境变量获取可执行命令列表
    支持 Windows/Linux/Mac
    """
    commands = set()
    
    # Windows 可执行文件扩展名
    if sys.platform == "win32":
        pathext = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").lower().split(";")
    else:
        pathext = [""]
    
    # 遍历 PATH 中的目录
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    
    for path_dir in path_dirs:
        if not path_dir or not os.path.isdir(path_dir):
            continue
        
        try:
            for entry in os.scandir(path_dir):
                if not entry.is_file():
                    continue
                
                name = entry.name
                
                if sys.platform == "win32":
                    # Windows: 检查是否有可执行扩展名
                    name_lower = name.lower()
                    for ext in pathext:
                        if name_lower.endswith(ext):
                            # 去掉扩展名
                            cmd_name = name[:len(name) - len(ext)] if ext else name
                            commands.add(cmd_name.lower())
                            break
                else:
                    # Linux/Mac: 检查是否有执行权限
                    if os.access(entry.path, os.X_OK):
                        commands.add(name)
        except (PermissionError, OSError):
            # 跳过无法访问的目录
            continue
    
    return commands


# 缓存系统命令，避免每次补全都扫描
_system_commands_cache: Optional[Set[str]] = None


def get_cached_system_commands() -> Set[str]:
    """获取缓存的系统命令列表"""
    global _system_commands_cache
    if _system_commands_cache is None:
        _system_commands_cache = get_system_commands()
    return _system_commands_cache


def refresh_system_commands():
    """刷新系统命令缓存"""
    global _system_commands_cache
    _system_commands_cache = get_system_commands()


def get_captain_dir() -> Path:
    """获取 .captain 目录路径"""
    workspace = get_workspace_path()
    if not workspace:
        workspace = "."
    captain_dir = Path(workspace).resolve() / ".captain"
    captain_dir.mkdir(parents=True, exist_ok=True)
    return captain_dir


def get_history_file() -> Path:
    """获取历史记录文件路径"""
    return get_captain_dir() / "history.txt"


class CaptainCompleter(Completer):
    """
    Captain 命令补全器
    支持:
    - 内置命令: exit, quit, shell, /list
    - prompt 模板命令: /init, /audit 等
    - shell 命令补全
    """
    
    def __init__(self, get_templates_func: Optional[Callable] = None):
        self.get_templates_func = get_templates_func or list_prompt_templates
        self._builtin_commands = ["exit", "quit", "q", "shell ", "vector ", "/list"]
    
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        word = document.get_word_before_cursor()
        
        # 空输入或只有开头字符，显示所有可用命令
        if not text or text == word:
            # 内置命令
            for cmd in self._builtin_commands:
                if cmd.startswith(text.lower()):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display_meta="built-in"
                    )
            
            # prompt 模板命令
            if text.startswith("/") or not text:
                templates = self.get_templates_func()
                for name, info in templates.items():
                    cmd = f"/{name}"
                    if cmd.startswith(text) or not text:
                        args_hint = " ".join(f'{a}=""' for a in info.get("args", []))
                        display = f"/{name} {args_hint}".strip()
                        yield Completion(
                            display,
                            start_position=-len(text),
                            display=f"/{name}",
                            display_meta=f"args: {', '.join(info.get('args', [])) or 'none'}"
                        )
        
        # / 开头，补全 prompt 模板
        elif text.startswith("/"):
            templates = self.get_templates_func()
            prefix = text[1:]  # 去掉 /
            
            for name, info in templates.items():
                if name.startswith(prefix):
                    args_hint = " ".join(f'{a}=""' for a in info.get("args", []))
                    display = f"/{name} {args_hint}".strip()
                    yield Completion(
                        display,
                        start_position=-len(text),
                        display=f"/{name}",
                        display_meta=f"args: {', '.join(info.get('args', [])) or 'none'}"
                    )
            
            # /list 命令
            if "list".startswith(prefix):
                yield Completion(
                    "/list",
                    start_position=-len(text),
                    display_meta="list all templates"
                )
        
        # shell 命令补全 - 使用系统 PATH 中的命令
        elif text.startswith("shell "):
            shell_part = text[6:]  # 去掉 "shell "
            if shell_part:
                # 只在有输入时才补全，避免显示太多命令
                system_cmds = get_cached_system_commands()
                shell_part_lower = shell_part.lower()
                
                # 优先显示前缀匹配的命令
                matches = []
                for cmd in system_cmds:
                    if cmd.lower().startswith(shell_part_lower):
                        matches.append(cmd)
                
                # 限制显示数量，按字母排序
                for cmd in sorted(matches)[:50]:
                    yield Completion(
                        cmd,
                        start_position=-len(shell_part),
                        display_meta="system"
                    )
        
        # vector 命令补全
        elif text.startswith("vector "):
            vector_part = text[7:]  # 去掉 "vector "
            parts = vector_part.split()
            
            if len(parts) == 0 or (len(parts) == 1 and not vector_part.endswith(" ")):
                # 补全 action: list, store, rag
                action_part = parts[0] if parts else ""
                for action, meta in [("list", "list collections"), ("store", "store markdown"), ("rag", "RAG query")]:
                    if action.startswith(action_part.lower()):
                        yield Completion(
                            action,
                            start_position=-len(action_part),
                            display_meta=meta
                        )
            
            # vector list - 无需更多参数
            elif parts[0].lower() == "list":
                pass  # list 命令完成
            
            # vector rag 补全
            elif parts[0].lower() == "rag":
                if len(parts) == 1 and vector_part.endswith(" "):
                    yield Completion(
                        "",
                        start_position=0,
                        display="{collection}",
                        display_meta="collection name (required)"
                    )
                elif len(parts) == 2 and vector_part.endswith(" "):
                    yield Completion(
                        "",
                        start_position=0,
                        display="{query}",
                        display_meta="your question (required)"
                    )
                elif len(parts) == 3 and vector_part.endswith(" "):
                    yield Completion(
                        "5",
                        start_position=0,
                        display="[top_k]",
                        display_meta="optional, default: 5"
                    )
            
            # vector store 补全
            elif parts[0].lower() == "store":
                if len(parts) == 1 or (len(parts) == 2 and not vector_part.endswith(" ")):
                    target_part = parts[1] if len(parts) > 1 else ""
                    if "markdown".startswith(target_part.lower()):
                        yield Completion(
                            "markdown",
                            start_position=-len(target_part),
                            display_meta="target"
                        )
                elif len(parts) >= 2 and parts[1].lower() == "markdown":
                    if len(parts) == 2 and vector_part.endswith(" "):
                        yield Completion(
                            "",
                            start_position=0,
                            display="{Path}",
                            display_meta="file path (required)"
                        )
                    elif len(parts) == 3 and vector_part.endswith(" "):
                        yield Completion(
                            "",
                            start_position=0,
                            display="[collection_name]",
                            display_meta="optional, default: filename"
                        )
                    elif len(parts) == 4 and vector_part.endswith(" "):
                        yield Completion(
                            "600",
                            start_position=0,
                            display="[chunk_size]",
                            display_meta="optional, default: 600"
                        )
                    elif len(parts) == 5 and vector_part.endswith(" "):
                        yield Completion(
                            "100",
                            start_position=0,
                            display="[chunk_overlap]",
                            display_meta="optional, default: 100"
                        )


def create_prompt_style() -> Style:
    """创建 prompt 样式"""
    return Style.from_dict({
        "prompt": "bold ansiblue",
        "prompt.arg": "ansicyan",
        # 补全菜单样式
        "completion-menu": "bg:ansiblack ansiwhite",
        "completion-menu.completion": "",
        "completion-menu.completion.current": "bg:ansiblue ansiwhite",
        "completion-menu.meta": "bg:ansiblack ansigray italic",
        "completion-menu.meta.current": "bg:ansiblue ansiwhite",
        # 自动建议样式
        "auto-suggest": "ansigray italic",
    })


def create_key_bindings() -> KeyBindings:
    """创建自定义快捷键绑定"""
    kb = KeyBindings()
    
    @kb.add("c-l")
    def clear_screen(event):
        """Ctrl+L 清屏"""
        event.app.renderer.clear()
    
    @kb.add("c-u")
    def clear_line(event):
        """Ctrl+U 清除当前行"""
        event.current_buffer.delete_before_cursor(len(event.current_buffer.text))
    
    return kb


def create_prompt_session(
    history_file: Optional[Path] = None,
    enable_history: bool = True,
    enable_auto_suggest: bool = True,
    enable_completion: bool = True
) -> PromptSession:
    """
    创建配置好的 PromptSession
    
    Args:
        history_file: 历史记录文件路径，默认为 .captain/history.txt
        enable_history: 是否启用历史记录
        enable_auto_suggest: 是否启用自动建议
        enable_completion: 是否启用命令补全
    
    Returns:
        配置好的 PromptSession
    """
    kwargs = {
        "style": create_prompt_style(),
        "key_bindings": create_key_bindings(),
    }
    
    # 历史记录
    if enable_history:
        if history_file is None:
            history_file = get_history_file()
        kwargs["history"] = FileHistory(str(history_file))
    
    # 自动建议（基于历史记录）
    if enable_auto_suggest and enable_history:
        kwargs["auto_suggest"] = AutoSuggestFromHistory()
    
    # 命令补全
    if enable_completion:
        kwargs["completer"] = CaptainCompleter()
        kwargs["complete_while_typing"] = True
    
    return PromptSession(**kwargs)


def get_prompt_message() -> FormattedText:
    """获取格式化的 prompt 消息"""
    return FormattedText([
        ("", "\n"),
        ("class:prompt", "> "),
    ])


class CaptainShell:
    """
    Captain Shell 封装类
    提供完整的命令行交互功能
    """
    
    def __init__(
        self,
        enable_history: bool = True,
        enable_auto_suggest: bool = True,
        enable_completion: bool = True
    ):
        self.session = create_prompt_session(
            enable_history=enable_history,
            enable_auto_suggest=enable_auto_suggest,
            enable_completion=enable_completion
        )
        self.prompt_message = get_prompt_message()
        self.style = create_prompt_style()
    
    async def prompt_async(self) -> str:
        """异步获取用户输入"""
        return await self.session.prompt_async(
            self.prompt_message,
            style=self.style
        )
    
    def prompt(self) -> str:
        """同步获取用户输入"""
        return self.session.prompt(
            self.prompt_message,
            style=self.style
        )
    
    def get_history(self) -> List[str]:
        """获取历史记录列表"""
        history_file = get_history_file()
        if history_file.exists():
            with open(history_file, "r", encoding="utf-8") as f:
                # FileHistory 格式: 每行一个命令，+ 开头
                lines = f.readlines()
                return [line[1:].strip() for line in lines if line.startswith("+")]
        return []
    
    def clear_history(self):
        """清除历史记录"""
        history_file = get_history_file()
        if history_file.exists():
            history_file.unlink()
    
    def add_to_history(self, command: str):
        """手动添加命令到历史记录"""
        if hasattr(self.session, "history") and self.session.history:
            self.session.history.append_string(command)

