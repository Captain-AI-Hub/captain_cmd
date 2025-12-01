"""
统一命令解析器
处理所有内置命令：shell, vector, prompt 模板等
"""

from typing import Optional
from dataclasses import dataclass
from enum import Enum

from utils.sys_shell import execute_shell_command
from utils.utils import get_prompt, list_prompt_templates
from tools.mod_vector import cli_store_markdown, cli_list_collections, cli_rag


class CommandType(Enum):
    """命令类型"""
    EXIT = "exit"           # 退出命令
    SHELL = "shell"         # shell 命令
    VECTOR = "vector"       # 向量命令
    VECTOR_RAG = "rag"      # RAG 命令（需要传递给 agent）
    PROMPT_LIST = "list"    # 列出 prompt 模板
    PROMPT = "prompt"       # prompt 模板命令
    PASSTHROUGH = "pass"    # 传递给 agent 处理
    EMPTY = "empty"         # 空输入


class ResultStyle(Enum):
    """结果样式"""
    SUCCESS = "success"     # 绿色
    ERROR = "error"         # 红色
    WARNING = "warning"     # 黄色
    INFO = "info"           # 青色
    PROMPT = "prompt"       # 紫色（prompt 模板）


@dataclass
class CommandResult:
    """命令解析结果"""
    cmd_type: CommandType
    success: bool
    title: str
    output: str
    style: ResultStyle
    passthrough_msg: Optional[str] = None  # 传递给 agent 的消息


def parse_command(query: str) -> CommandResult:
    """
    统一解析用户输入的命令
    
    Args:
        query: 用户输入的原始字符串
    
    Returns:
        CommandResult 包含命令类型、执行结果等信息
    """
    query = query.strip()
    
    # 空输入
    if not query:
        return CommandResult(
            cmd_type=CommandType.EMPTY,
            success=True,
            title="",
            output="",
            style=ResultStyle.INFO
        )
    
    # 退出命令
    if query.lower() in ["exit", "quit", "q"]:
        return CommandResult(
            cmd_type=CommandType.EXIT,
            success=True,
            title="👋 Goodbye!",
            output="",
            style=ResultStyle.SUCCESS
        )
    
    # Shell 命令
    if query.lower() == "shell" or query.lower().startswith("shell "):
        command = query[6:].strip()
        if not command:
            return CommandResult(
                cmd_type=CommandType.SHELL,
                success=False,
                title="⚠️ Shell Command",
                output="Please provide a command after 'shell'",
                style=ResultStyle.WARNING
            )
        
        result = execute_shell_command(command)
        return CommandResult(
            cmd_type=CommandType.SHELL,
            success=result["success"],
            title=f"🖥️ Shell: {result['command']}",
            output=result["output"],
            style=ResultStyle.SUCCESS if result["success"] else ResultStyle.ERROR
        )
    
    # Vector 命令
    if query.lower() == "vector" or query.lower().startswith("vector "):
        result = _parse_vector_command(query)
        return result
    
    # Prompt 模板命令
    if query.startswith("/"):
        prompt_cmd = query[1:].strip()
        
        # /list 列出所有模板
        if prompt_cmd == "list":
            templates = list_prompt_templates()
            if templates:
                lines = ["Available prompt templates:\n"]
                for name, info in templates.items():
                    args_str = ", ".join(info["args"]) if info["args"] else "none"
                    lines.append(f"  /{name}  (args: {args_str})")
                    lines.append(f"    {info['prompt_preview']}\n")
                return CommandResult(
                    cmd_type=CommandType.PROMPT_LIST,
                    success=True,
                    title="📋 Prompt Templates",
                    output="\n".join(lines),
                    style=ResultStyle.INFO
                )
            else:
                return CommandResult(
                    cmd_type=CommandType.PROMPT_LIST,
                    success=False,
                    title="⚠️ Prompt Templates",
                    output="No prompt templates found",
                    style=ResultStyle.WARNING
                )
        
        # 解析 prompt 模板
        result = get_prompt(prompt_cmd)
        if result is None:
            return CommandResult(
                cmd_type=CommandType.PROMPT,
                success=False,
                title=f"⚠️ Unknown Template: {prompt_cmd.split()[0]}",
                output="Use /list to see available templates",
                style=ResultStyle.WARNING
            )
        elif result.startswith("Error:"):
            return CommandResult(
                cmd_type=CommandType.PROMPT,
                success=False,
                title="❌ Prompt Error",
                output=result,
                style=ResultStyle.ERROR
            )
        
        # 成功解析 prompt，传递给 agent
        return CommandResult(
            cmd_type=CommandType.PROMPT,
            success=True,
            title=f"📝 Prompt: {prompt_cmd.split()[0]}",
            output=result,
            style=ResultStyle.PROMPT,
            passthrough_msg=result
        )
    
    # 其他输入传递给 agent
    return CommandResult(
        cmd_type=CommandType.PASSTHROUGH,
        success=True,
        title="",
        output="",
        style=ResultStyle.INFO,
        passthrough_msg=query
    )


def _parse_vector_command(command: str) -> CommandResult:
    """解析 vector 命令"""
    parts = command.split(maxsplit=3)  # 最多分割3次，保留 rag 的查询文本
    
    if len(parts) < 2:
        return CommandResult(
            cmd_type=CommandType.VECTOR,
            success=False,
            title="📖 Vector Command Usage",
            output="""Usage:
  vector list
      List all collections in vector database.

  vector store markdown {Path} <collection_name> <chunk_size> <chunk_overlap>
      Store a Markdown file into vector database.
      - {Path}             : Markdown file path (required)
      - <collection_name>  : Collection name (default: filename)
      - <chunk_size>       : Chunk size in chars (default: 600)
      - <chunk_overlap>    : Overlap size in chars (default: 100)

  vector rag {collection} {query} <top_k>
      RAG: Retrieve relevant context and ask AI.
      - {collection} : Collection name to search
      - {query}      : Your question
      - <top_k>      : Number of results (default: 5)""",
            style=ResultStyle.WARNING
        )
    
    action = parts[1].lower()
    
    # vector list - 列出所有集合
    if action == "list":
        result = cli_list_collections()
        is_error = result.startswith("Error") or result.startswith("No vector")
        return CommandResult(
            cmd_type=CommandType.VECTOR,
            success=not is_error,
            title="📋 Vector Collections" if not is_error else "⚠️ Vector Collections",
            output=result,
            style=ResultStyle.INFO if not is_error else ResultStyle.WARNING
        )
    
    # vector rag {collection} {query} [top_k] - RAG 检索
    if action == "rag":
        if len(parts) < 4:
            return CommandResult(
                cmd_type=CommandType.VECTOR,
                success=False,
                title="📖 RAG Usage",
                output="""Usage: vector rag {collection_name} {query} <top_k>
  - {collection_name} : Collection name to search
  - {query}           : Your question
  - <top_k>           : Number of results (default: 5)""",
                style=ResultStyle.WARNING
            )
        
        collection_name = parts[2]
        # 重新分割以获取 query 和 top_k
        rag_parts = command.split(maxsplit=4)
        query = rag_parts[3] if len(rag_parts) > 3 else ""
        
        # 解析 top_k
        top_k = 5
        if len(rag_parts) > 4:
            try:
                top_k = int(rag_parts[4])
            except ValueError:
                return CommandResult(
                    cmd_type=CommandType.VECTOR,
                    success=False,
                    title="❌ RAG Error",
                    output=f"Invalid top_k: {rag_parts[4]} (must be integer)",
                    style=ResultStyle.ERROR
                )
        
        success, context, enhanced_prompt = cli_rag(collection_name, query, top_k)
        
        if not success:
            return CommandResult(
                cmd_type=CommandType.VECTOR_RAG,
                success=False,
                title="❌ RAG Error",
                output=enhanced_prompt,  # 包含错误信息
                style=ResultStyle.ERROR
            )
        
        # 成功检索，只显示 collection 名称
        return CommandResult(
            cmd_type=CommandType.VECTOR_RAG,
            success=True,
            title=f"🔍 RAG: {collection_name}",
            output=f"Searching in collection '{collection_name}'...",
            style=ResultStyle.INFO,
            passthrough_msg=enhanced_prompt
        )
    
    # vector store markdown {path} ... - 存储 markdown
    if action == "store":
        # 重新分割以获取所有参数
        store_parts = command.split()
        
        if len(store_parts) < 4:
            return CommandResult(
                cmd_type=CommandType.VECTOR,
                success=False,
                title="📖 Vector Store Usage",
                output="""Usage: vector store markdown {Path} <collection_name> <chunk_size> <chunk_overlap>
  - {Path}             : Markdown file path (required)
  - <collection_name>  : Collection name (default: filename)
  - <chunk_size>       : Chunk size in chars (default: 600)
  - <chunk_overlap>    : Overlap size in chars (default: 100)""",
                style=ResultStyle.WARNING
            )
        
        target = store_parts[2].lower()
        if target != "markdown":
            return CommandResult(
                cmd_type=CommandType.VECTOR,
                success=False,
                title="❌ Vector Command Error",
                output=f"Unknown target: {target}\nSupported: vector store markdown",
                style=ResultStyle.ERROR
            )
        
        file_path = store_parts[3]
        collection_name = store_parts[4] if len(store_parts) > 4 else None
        
        try:
            chunk_size = int(store_parts[5]) if len(store_parts) > 5 else 600
        except ValueError:
            return CommandResult(
                cmd_type=CommandType.VECTOR,
                success=False,
                title="❌ Vector Command Error",
                output=f"Invalid chunk_size: {store_parts[5]} (must be integer)",
                style=ResultStyle.ERROR
            )
        
        try:
            chunk_overlap = int(store_parts[6]) if len(store_parts) > 6 else 100
        except ValueError:
            return CommandResult(
                cmd_type=CommandType.VECTOR,
                success=False,
                title="❌ Vector Command Error",
                output=f"Invalid chunk_overlap: {store_parts[6]} (must be integer)",
                style=ResultStyle.ERROR
            )
        
        result = cli_store_markdown(file_path, collection_name, chunk_size, chunk_overlap)
        
        if result.startswith("Error"):
            return CommandResult(
                cmd_type=CommandType.VECTOR,
                success=False,
                title="❌ Vector Store Error",
                output=result,
                style=ResultStyle.ERROR
            )
        
        return CommandResult(
            cmd_type=CommandType.VECTOR,
            success=True,
            title="✅ Vector Store Success",
            output=result,
            style=ResultStyle.SUCCESS
        )
    
    # 未知子命令
    return CommandResult(
        cmd_type=CommandType.VECTOR,
        success=False,
        title="❌ Vector Command Error",
        output=f"Unknown action: {action}\nSupported: list, store, rag",
        style=ResultStyle.ERROR
    )

