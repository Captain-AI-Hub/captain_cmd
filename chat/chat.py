from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from agent.agent import build_sub_agent
from tools.shell_exec import shell_exec
from tools.web_search import internet_search
import json
from typing import Optional, Any, AsyncGenerator, cast
from langchain_core.messages import HumanMessage
from pathlib import Path
from utils.utils import (
    cprint, Colors,
    get_database_path, get_local_file_store_path,
    get_major_config, get_model_config,
    get_major_agent_config, get_sub_agents_config
)
from tools.utils import ErrorHandlingMiddleware

from langchain.agents.middleware import (
    TodoListMiddleware,
)

from deepagents.middleware import (
    FilesystemMiddleware,
    SubAgentMiddleware,
    CompiledSubAgent
)

from deepagents.backends import (
    CompositeBackend,
    StoreBackend,
    FilesystemBackend
)

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore
import aiosqlite

_store = None
_checkpoint = None
_major_agent = None

async def init_resources():
    """初始化数据库连接"""
    global _store, _checkpoint
    
    try:
        # 创建异步连接
        store_conn = await aiosqlite.connect(get_local_file_store_path())
        checkpoint_conn = await aiosqlite.connect(get_database_path())
        
        # 创建存储对象
        _store = AsyncSqliteStore(conn=store_conn)
        _checkpoint = AsyncSqliteSaver(conn=checkpoint_conn)
        
        # 初始化数据库模式
        await _store.setup()
        await _checkpoint.setup()
        return True
    except Exception as e:
        cprint(f"[init_resources] Failed to initialize resources: {e}", Colors.FAIL)
        return False

async def build_agent(
    model_name: str,
    base_url: str,
    api_key: str,
    system_prompt: str,
    workspace_path: str
) -> Optional[Any]:
    """构建 deep agent"""
    
    global _store, _checkpoint, _major_agent, _llm_tool_selector_model, _summarization_model
    
    # 获取 sub agents 配置 (新的 TOML 格式)
    sub_agents_config = get_sub_agents_config()
       
    sub_agent = []
    for sub_agent_name, sub_agent_config in sub_agents_config.items():
        try:
            sub_model_name = sub_agent_config["model_name"]
            sub_base_url = sub_agent_config["base_url"]
            sub_api_key = sub_agent_config["api_key"]
            sub_system_prompt = sub_agent_config.get("system_prompt", "")
            mcp_tools = sub_agent_config.get("mcp_tools", [])
            inside_tools = sub_agent_config.get("inside_tools", [])
        except Exception as e:
            cprint(
                f"[build_agent] Sub agent '{sub_agent_name}' config error: {e}", 
                Colors.FAIL
            )
            continue

        agent = await build_sub_agent(
            model_name=sub_model_name,
            base_url=sub_base_url,
            api_key=sub_api_key,
            system_prompt=sub_system_prompt,
            mcp_tools=mcp_tools,
            inside_tools=inside_tools,
        )
        if agent is not None:
            sub_agent.append(
                CompiledSubAgent(
                    name=sub_agent_name,
                    description=sub_agent_config.get("description", ""),
                    runnable=agent
                )
            )
        else:
            cprint(
                f"[build_agent] Sub agent '{sub_agent_name}' build failed", 
                Colors.FAIL
            )

    try:
        # 初始化模型
        model = init_chat_model(
            model=model_name,
            base_url=base_url,
            api_key=api_key
        )
                
        # 确保资源已初始化
        if _store is None or _checkpoint is None:
            if not await init_resources():
                raise RuntimeError("Failed to initialize database resources")
        
        # 创建代理
        agent = create_agent(
            model=model,
            tools=[shell_exec, internet_search],
            store=_store,
            checkpointer=_checkpoint,
            system_prompt=system_prompt,
            middleware=[
                TodoListMiddleware(),
                FilesystemMiddleware(
                    backend=lambda rt: CompositeBackend(
                        default=FilesystemBackend(
                                root_dir=Path(workspace_path).resolve(), 
                                virtual_mode=True
                        ),
                        routes={
                            "/memories/": StoreBackend(rt),
                        }
                    ),
                ),
                SubAgentMiddleware(
                    default_model=model,
                    default_tools=[],
                    subagents=sub_agent,
                ),
                ErrorHandlingMiddleware(),
            ]
        )

        _major_agent = agent
        return agent
        
    except Exception as e:
        cprint(f"[build_agent] Error creating agent: {e}", Colors.FAIL)
        import traceback
        cprint(traceback.format_exc(), Colors.FAIL)
        return None

async def process_agent(agent: Any, message: str):
    """处理代理流式输出"""
    try:
        messages = [HumanMessage(content=message)]
        async for stream_mode, chunk in agent.astream(
            {"messages": messages},
            stream_mode=["updates", "messages"],
            config=get_major_config()
        ):
            try:
                # ============ messages 模式：流式 token ============
                if stream_mode == "messages":
                    token, metadata = chunk
                    
                    if metadata is None or token is None:
                        continue
                    
                    node_name = metadata.get("langgraph_node", "")
                    
                    # 检查 token 是否有 content_blocks
                    if not hasattr(token, 'content_blocks') or not token.content_blocks:
                        continue
                    
                    for block in token.content_blocks:
                        # 模型的文本输出
                        if block.get("type") == "text" and node_name == "model":
                            yield {
                                "type": "model_answer",
                                "content": block.get('text', ''),
                            }
                        # 模型的思考过程
                        elif block.get("type") == "reasoning":
                            yield {
                                "type": "model_thinking",
                                "content": block.get('reasoning', ''),
                            }
                
                # ============ updates 模式：状态更新 ============
                elif stream_mode == "updates":
                    if chunk is None:
                        continue
                    
                    # chunk 是 dict: {node_name: {state_updates}}
                    for node_name, node_data in chunk.items():
                        if node_data is None:
                            continue
                        
                        # 获取 messages 列表
                        messages_list = node_data.get("messages", [])
                        
                        for msg in messages_list:
                            # ---- 处理工具调用 ----
                            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    yield {
                                        "type": "tool_call",
                                        "name": tc.get('name') or tc['name'],  # 兼容不同格式
                                        "args": tc.get('args', {}),
                                        "id": tc.get('id')
                                    }
                            
                            # ---- 处理工具结果 ----
                            if msg.__class__.__name__ == "ToolMessage":
                                yield {
                                    "type": "tool_result",
                                    "content": msg.content,
                                    "id": msg.tool_call_id,
                                }
                            
                            if msg.__class__.__name__ == "ToolMessage":
                                tool_name = getattr(msg, 'name', '')
                                if tool_name == "task":  # SubAgentMiddleware 使用 'task' 作为工具名
                                    yield {
                                        "type": "sub_agent",
                                        "content": msg.content,
                                    }
 
            except Exception as e:
                import traceback
                yield {
                    "type": "error",
                    "content": f'[process_agent] Inner exception: {e}\n[process_agent] Traceback:\n{traceback.format_exc()}',
                }
    
    except Exception as e:
        import traceback
        yield {
            "type": "error",
            "content": f'[process_agent] Error: {e}\n[process_agent] Traceback: {traceback.format_exc()}',
        }

async def ChatStream(
    model_name: str,
    base_url: str,
    api_key: str,
    system_prompt: str = "you are a helpful assistant", 
    human_message: str = "", 
    workspace_path: str = ".",
):
    """chat stream"""
    
    try:
        # 验证输入
        if not model_name or not base_url or not api_key or not human_message:
            yield {
                "type": "error", 
                "content": "Invalid request: missing required fields"
            }
            return    
        # 初始化资源
        global _store, _checkpoint, _major_agent
        if _store is None or _checkpoint is None:
            if not await init_resources():
                yield {
                    "type": "error", 
                    "content": "Failed to initialize database"
                }
                return
        
        agent = None

        if _major_agent is not None:
            agent = _major_agent
        else:
            agent = await build_agent(
                model_name, 
                base_url, 
                api_key, 
                system_prompt, 
                workspace_path
            )
        
        if not agent:
            yield {
                "type": "error", 
                "content": "Failed to build agent"
            }
            return
        
        # 处理代理流
        async for message in process_agent(agent, human_message):
            if message["type"] == "model_answer":
                yield {
                    "type": "model_answer",
                    "content": message["content"]
                }
            elif message["type"] == "model_thinking":
                yield {
                    "type": "model_thinking",
                    "content": message["content"]
                }
            elif message["type"] == "tool_call":
                yield {
                    "type": "tool_call",
                    "content": json.dumps({
                        "name": message["name"],
                        "args": message["args"],
                        "id": message["id"]
                    }, ensure_ascii=False)
                }
            elif message["type"] == "tool_result":
                yield {
                    "type": "tool_result",
                    "content": json.dumps({
                        "content": message["content"],
                        "id": message["id"]
                    }, ensure_ascii=False)
                }
            elif message["type"] == "sub_agent":
                yield {
                    "type": "sub_agent",
                    "content": message["content"]
                }
            elif message["type"] == "error":
                yield {
                    "type": "error",
                    "content": message["content"]
                }
                
    except Exception as e:
        import traceback
        yield {
            "type": "error", 
            "content": f'[ChatStream] Error: {e}\n[ChatStream] Traceback:\n{traceback.format_exc()}',
        }

async def cleanup_resources():
    """清理数据库资源"""
    global _store, _checkpoint
    try:
        # 关闭 store
        if _store:
            try:
                if hasattr(_store, "_task") and _store._task:
                    _store._task.cancel()
                    try:
                        await _store._task
                    except:
                        pass
                if hasattr(_store, "conn") and _store.conn:
                    await _store.conn.close()
                    cprint("[cleanup] Store connection closed", Colors.OKGREEN)
            except Exception as e:
                cprint(f"[cleanup] Error closing store: {e}", Colors.WARNING)
        
        # 关闭 checkpoint
        if _checkpoint:
            try:
                if hasattr(_checkpoint, "conn") and _checkpoint.conn:
                    await _checkpoint.conn.close()
                    cprint("[cleanup] Checkpoint connection closed", Colors.OKGREEN)
            except Exception as e:
                cprint(f"[cleanup] Error closing checkpoint: {e}", Colors.WARNING)
        
        # 重置全局变量
        _store = None
        _checkpoint = None
            
    except Exception as e:
        cprint(f"[cleanup] Error during cleanup: {e}", Colors.WARNING)