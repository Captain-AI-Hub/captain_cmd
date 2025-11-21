import tomllib
import os

_toml_path = ""
_captain_db_path = ""
_local_file_store_path = ""

_major_config = {
    "configurable": {
        "thread_id": "major_thread"
    }
}

def get_major_config():
    """
    获取major配置
    Returns:
        major_config: major配置
    """
    return _major_config

def set_toml_path(path: str):
    """
    设置toml路径
    Args:
        path: toml路径
    """
    global _toml_path
    _toml_path = path

def get_mcp_servers():
    """
    获取mcpServers配置
    Returns:
        mcp_servers: mcpServers配置
    """
    if not _toml_path:
        return "Error: toml_path is None"
    with open(_toml_path, "rb") as f:
        config = tomllib.load(f)
    return config["mcp_servers"]["content"]

def get_model_config():
    """
    获取模型配置
    Returns:
        model_config: 模型配置
    """
    if not _toml_path:
        return "Error: toml_path is None"
    with open(_toml_path, "rb") as f:
        config = tomllib.load(f)
    return config["model_config"]


def set_database_path(path: str):
    """
    设置工作空间路径
    Args:
        path: 工作空间路径
    """
    if not path:
        return "Error: database_path is None"
    
    base_path = path
    db_path = os.path.join(base_path, ".captain", "checkpoint.db")
    if not os.path.exists(db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with open(db_path, "w") as f:
            f.write("")
    global _captain_db_path
    _captain_db_path = db_path

    store_path = os.path.join(base_path, ".captain", "store.db")
    if not os.path.exists(store_path):
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        with open(store_path, "w") as f:
            f.write("")
    global _local_file_store_path
    _local_file_store_path = store_path

def get_database_path():
    """
    获取工作空间路径
    Returns:
        database_path: 数据库路径
    """
    return _captain_db_path

def get_local_file_store_path():
    """
    获取本地文件存储路径
    Returns:
        local_file_store_path: 本地文件存储路径
    """
    return _local_file_store_path

class Colors:
    """ANSI颜色代码"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def cprint(text: str, color: str = Colors.ENDC):
    """
    带颜色的打印函数
    Args:
        text: 要打印的文本
        color: 颜色代码 (从Colors类获取)
    """
    print(f"{color}{text}{Colors.ENDC}")
