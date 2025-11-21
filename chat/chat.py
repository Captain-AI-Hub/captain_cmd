from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient
import json
from typing import Optional, Any
from langchain_core.messages import HumanMessage
from utils.utils import (
    get_mcp_servers, cprint, Colors, 
    get_database_path, get_local_file_store_path,
    get_major_config
)

from langchain.agents.middleware import TodoListMiddleware
from deepagents.middleware import (
    FilesystemMiddleware,
    SubAgentMiddleware
)

from deepagents.backends import CompositeBackend, FilesystemBackend, StoreBackend
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
        
        cprint("[init_resources] Database resources initialized", Colors.OKGREEN)
        return True
    except Exception as e:
        cprint(f"[init_resources] Failed to initialize resources: {e}", Colors.FAIL)
        return False

async def build_agent(
    model_name: str, 
    base_url: str, 
    api_key: str, 
    tool_names: list[str], 
    system_prompt: str, 
    workspace_path: str
) -> Optional[Any]:
    """构建 deep agent"""
    
    global _store, _checkpoint, _major_agent
    
    mcp_tools: list[Any] = []
    
    # 加载 MCP 工具
    for tool_name in tool_names:
        try:
            config = json.loads(get_mcp_servers())
            
            if tool_name not in config.get("mcpServers", {}):
                cprint(
                    f"[build_agent] Warning: tool '{tool_name}' not found in mcpServers", 
                    Colors.WARNING
                )
                continue
            
            mcp_client = MultiServerMCPClient({
                tool_name: config["mcpServers"][tool_name]
            })
            
            fetched_tools = await mcp_client.get_tools()
            if fetched_tools:
                mcp_tools.extend(fetched_tools)
                cprint(
                    f"[build_agent] Loaded {len(fetched_tools)} tools for '{tool_name}'", 
                    Colors.OKGREEN
                )
        except Exception as e:
            cprint(
                f"[build_agent] Warning: failed to load MCP tool '{tool_name}': {e}. Continuing...", 
                Colors.WARNING
            )
    
    try:
        # 初始化模型
        model = init_chat_model(
            model=model_name,
            base_url=base_url,
            api_key=api_key
        )
        
        cprint(
            f"[build_agent] Initialized model '{model_name}' with base_url '{base_url}'", 
            Colors.OKCYAN
        )
        
        # 确保资源已初始化
        if _store is None or _checkpoint is None:
            if not await init_resources():
                raise RuntimeError("Failed to initialize database resources")
        
        # 创建代理
        agent = create_agent(
            model=model,
            tools=mcp_tools if mcp_tools else None,
            checkpointer=_checkpoint,
            store=_store,
            system_prompt=system_prompt,
            middleware=[
                TodoListMiddleware(
                    system_prompt="""You are given complex user tasks. Before acting, break the task into 3-6 actionable steps using the `write_todos` tool.
                    You are given complex user tasks. Before acting, break the task into 3-6 actionable steps using the `write_todos` tool.
                    For each step include: objective, priority (high/medium/low), and whether human approval is required.
                    When steps are complete, update the todo with status: pending/in_progress/done.
                    """,
                    tool_description="""
                    Use `write_todos` to create or update a structured to-do list. Provide JSON-like entries:
                    - title: short title
                    - objective: one-sentence goal
                    - priority: high|medium|low
                    - status: pending|in_progress|done
                    - requires_approval: true|false
                    """
                ),
                FilesystemMiddleware(
                    backend=lambda rt: CompositeBackend(
                        default=FilesystemBackend(
                            root_dir=workspace_path,
                            virtual_mode=True
                        ),
                        routes={
                            "/memories/": StoreBackend(rt)
                        }
                    )
                )
            ]
        )
        
        cprint(
            f"[build_agent] Agent created successfully with {len(mcp_tools)} tools", 
            Colors.OKGREEN
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
                if stream_mode == "messages":
                    token, metadata = chunk
                    node_name = metadata.get("langgraph_node", "")
                    
                    for block in token.content_blocks:
                        if block["type"] == "text" and node_name == "model":
                            yield {
                                "type": "model_answer", 
                                "content": block['text'],
                            }
                        elif block["type"] == "reasoning":
                            yield {
                                "type": "model_thinking", 
                                "content": block['reasoning'],
                            }
                
                elif stream_mode == "updates":
                    # 从 updates 获取完整的工具调用
                    for node_name, data in chunk.items():
                        messages = data.get("messages", [])
                        for msg in messages:
                            # 完整的工具调用
                            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    yield {
                                        "type": "tool_call",
                                        "name": tc['name'],
                                        "args": tc['args'],  # 完整参数
                                        "id": tc['id']
                                    }
                            
                            # 工具结果
                            if msg.__class__.__name__ == "ToolMessage":
                                # ToolMessage.tool_call_id 对应 tool_call 的 id
                                result_id = getattr(msg, 'tool_call_id', getattr(msg, 'id', ''))
                                yield {
                                    "type": "tool_result", 
                                    "content": msg.content, 
                                    "id": result_id,
                                }
            except Exception as e:
                yield {
                    "type": "error", 
                    "content": str(e),
                }
    except Exception as e:
        import traceback
        print(f"[process_agent] Error: {e}")
        print(f"[process_agent] Traceback: {traceback.format_exc()}")
        yield {
            "type": "error", 
            "content": str(e),
        }

async def ChatStream(
    model_name: str, 
    base_url: str, 
    api_key: str, 
    list_mcp_tools: list[str] | None = None, 
    system_prompt: str = "", 
    list_configs: list[str] | None = None, 
    human_message: str = "", 
    tool_names: list[str] | None = None, 
    workspace_path: str = "",

):
    """主聊天流"""
    
    try:
        # 验证输入
        if not model_name or not base_url or not api_key:
            yield {
                "type": "error", 
                "content": "Invalid request: missing required fields"
            }
            return
        
        # 使用 tool_names 或 list_mcp_tools
        tools_input = tool_names if tool_names is not None else (list_mcp_tools or [])
        
        cprint(
            f"[ChatStream] Request: model={model_name}, tools={len(tools_input)}", 
            Colors.OKBLUE
        )
        
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
                tools_input, 
                system_prompt, 
                workspace_path
            )
        
        if not agent:
            yield {"type": "error", "content": "Failed to build agent"}
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
            elif message["type"] == "error":
                yield {
                    "type": "error",
                    "content": message["content"]
                }
                
    except Exception as e:
        cprint(f"[ChatStream] Error: {e}", Colors.FAIL)
        import traceback
        cprint(traceback.format_exc(), Colors.FAIL)
        yield {"type": "error", "content": str(e)}

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