from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient
import json
from typing import Optional, Any
from utils.utils import (
    get_mcp_servers, cprint, Colors,
)

async def build_sub_agent(
    model_name: str,
    base_url: str,
    api_key: str,
    mcp_tools: list[str] | None = None,
    inside_tools: list[Any] | None = None,
    system_prompt: str | None = None,
) -> Optional[Any]:
    """build sub agent"""

    mcp_tools_list = []
    
    # 加载 MCP 工具
    for tool_name in mcp_tools if mcp_tools else []:
        try:
            config = json.loads(get_mcp_servers())
            
            if tool_name not in config.get("mcpServers", {}):
                cprint(
                    f"[build_sub_agent] Warning: tool '{tool_name}' not found in mcpServers", 
                    Colors.WARNING
                )
                continue
            
            mcp_client = MultiServerMCPClient({
                tool_name: config["mcpServers"][tool_name]
            })
            
            fetched_tools = await mcp_client.get_tools()
            if fetched_tools:
                mcp_tools_list.extend(fetched_tools)
                cprint(
                    f"[build_sub_agent] Loaded {len(fetched_tools)} tools for '{tool_name}'", 
                    Colors.OKGREEN
                )
        except Exception as e:
            cprint(
                f"[build_sub_agent] Warning: failed to load MCP tool '{tool_name}': {e}. Continuing...", 
                Colors.WARNING
            )
    if inside_tools:
        mcp_tools_list.extend(inside_tools)
    try:
        model = init_chat_model(
            model=model_name,
            base_url=base_url,
            api_key=api_key
        )

        agent = create_agent(
            model=model,
            tools=mcp_tools_list if mcp_tools_list else None,
            system_prompt=system_prompt,
        )
        
        return agent
    
    except Exception as e:
        cprint(f"[build_sub_agent] Error creating agent: {e}", Colors.FAIL)
        import traceback
        cprint(traceback.format_exc(), Colors.FAIL)
        return None