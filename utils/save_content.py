import os
import json
from datetime import datetime
from typing import Union, Dict, Any, List

def save_content(file_path: str, content_type: str, content: Union[str, Dict[str, Any], List[Any]]):
    """
    保存对话内容到指定文件，使用 Markdown 格式以提高可读性
    
    Args:
        file_path (str): 保存文件的路径
        content_type (str): 内容类型 ('think', 'tool_call', 'tool_result', 'answer')
        content (Union[str, Dict, List]): 要保存的内容
    """
    # 确保目录存在
    if os.path.dirname(file_path):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    markdown_content = ""

    # 根据类型格式化 Markdown
    if content_type == "think":
        markdown_content = f"### 🤔 Thought ({timestamp})\n\n> {str(content).replace(chr(10), chr(10) + '> ')}"
        
    elif content_type == "tool_call":
        # 预期 content 是 dict: {'name': 'tool_name', 'args': {...}}
        if isinstance(content, dict):
            tool_name = content.get('name', 'Unknown Tool')
            args = content.get('args', {})
            try:
                args_str = json.dumps(args, ensure_ascii=False, indent=2)
            except:
                args_str = str(args)
            
            markdown_content = f"### 🛠️ Tool Call: `{tool_name}` ({timestamp})\n\n**Arguments:**\n```json\n{args_str}\n```"
        else:
             markdown_content = f"### 🛠️ Tool Call ({timestamp})\n\n```json\n{content}\n```"

    elif content_type == "tool_result":
        # 尝试解析 JSON 以便漂亮打印
        content_str = str(content)
        try:
            if isinstance(content, (dict, list)):
                 content_str = json.dumps(content, ensure_ascii=False, indent=2)
            else:
                # 尝试将字符串解析为 JSON
                parsed = json.loads(content_str)
                content_str = json.dumps(parsed, ensure_ascii=False, indent=2)
            code_block_type = "json"
        except:
            code_block_type = "text"
            
        markdown_content = f"### 🏁 Tool Result ({timestamp})\n\n```{code_block_type}\n{content_str}\n```"

    elif content_type == "answer":
        markdown_content = f"### 🤖 Answer ({timestamp})\n\n{content}"
        
    else:
        # 默认处理
        if isinstance(content, (dict, list)):
            try:
                content_str = json.dumps(content, ensure_ascii=False, indent=2)
                markdown_content = f"### {content_type.capitalize()} ({timestamp})\n\n```json\n{content_str}\n```"
            except:
                markdown_content = f"### {content_type.capitalize()} ({timestamp})\n\n{content}"
        else:
            markdown_content = f"### {content_type.capitalize()} ({timestamp})\n\n{content}"

    mode = 'a' if os.path.exists(file_path) else 'w'
    
    try:
        with open(file_path, mode, encoding='utf-8') as f:
            # 如果文件是新的，或者是空的，不加分隔符，否则加
            if mode == 'a' and f.tell() > 0:
                f.write("\n---\n\n")
            f.write(markdown_content)
            f.write("\n")
    except Exception as e:
        print(f"Error saving content to {file_path}: {e}")
