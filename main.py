from utils.utils import (
    set_toml_path, get_model_config, 
    set_database_path, get_database_path, 
    get_local_file_store_path
)
import argparse
from chat.chat import ChatStream, cleanup_resources
import asyncio
import sys
import os
import json
import time
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich import box
# from prompt_toolkit import PromptSession
# from prompt_toolkit.styles import Style

async def main():
    """主程序入口"""
    
    # 创建 Rich Console
    console = Console()
    
    parser = argparse.ArgumentParser(description="Captain Cmd Tools")
    parser.add_argument(
        "--config", 
        type=str, 
        default="config.toml", 
        required=True, 
        help="Path to config file"
    )
    parser.add_argument(
        "--workspace", 
        type=str, 
        default="workspace", 
        required=True, 
        help="Path to workspace directory"
    )
    args = parser.parse_args()

    # 初始化配置
    set_toml_path(args.config)
    model_config = get_model_config()
    
    if model_config == "Error: toml_path is None":
        console.print(f"[bold red]❌ Failed to load model config: {model_config}[/bold red]")
        sys.exit(1)
    
    set_database_path(args.workspace)
    
    # 显示欢迎信息
    console.print("\n[bold cyan]🚀 Welcome to Captain Cmd Tools[/bold cyan]")
    
    # 创建配置信息表格
    config_table = Table(show_header=False, box=box.SIMPLE)
    config_table.add_column("Key", style="cyan")
    config_table.add_column("Value", style="green")
    
    config_table.add_row("Model", model_config['model_name'])
    config_table.add_row("Tools", f"{len(model_config['tool_names'])} loaded")
    
    for tool in model_config['tool_names']:
        config_table.add_row("  →", tool)
    
    config_table.add_row("Workspace", args.workspace)
    config_table.add_row("CheckpointDB", get_database_path())
    config_table.add_row("StoreDB", get_local_file_store_path())
    
    console.print(config_table)
    console.print("\n[dim]Type 'exit' or 'quit' to exit[/dim]\n")

    # 全局 Live 显示控制
    current_live = None
    
    def update_live(renderable, transient=False):
        """统一更新 Live 显示"""
        nonlocal current_live
        
        if current_live is None:
            current_live = Live(
                renderable,
                console=console,
                refresh_per_second=12,
                transient=transient
            )
            current_live.start()
        else:
            current_live.update(renderable)

    def stop_current_live():
        """停止当前 Live"""
        nonlocal current_live
        if current_live is not None:
            current_live.stop()
            current_live = None
        
    try:
        while True:
            try:
                # 获取用户输入
                # 使用原生 input 避开 rich/prompt_toolkit 对中文光标计算的干扰
                # 先打印带颜色的提示符
                console.print("\n[bold blue]>[/bold blue] ", end="")
                # 使用原生 input 获取输入
                query_msg = input().strip()
                
                # 检查退出命令
                if query_msg.lower() in ["exit", "quit", "q"]:
                    console.print("[bold green]👋 Goodbye![/bold green]")
                    break
                
                # 忽略空输入
                if not query_msg:
                    continue
                
                console.print()
                
                # 状态管理
                tool_calls = {}     # {tool_id: {"name": str, "args": dict, "args_str": str}}
                tool_results = {}   # {tool_id: result_content}
                thinking_buffer = []
                answer_buffer = []
                
                # 流式处理响应
                async for response in ChatStream(
                    model_name=model_config["model_name"],
                    base_url=model_config["base_url"],
                    api_key=model_config["api_key"],
                    list_mcp_tools=model_config["tool_names"],
                    system_prompt=model_config["system_prompt"],
                    human_message=query_msg,
                    workspace_path=args.workspace
                ):
                    response_type = response.get("type")
                    content = response.get("content", "")
                    
                    if response_type == "model_thinking":
                        thinking_buffer.append(content)
                        thinking_text = "".join(thinking_buffer)
                        
                        update_live(
                            Panel(
                                thinking_text,
                                title="[bold yellow]🤔 Model Thinking[/bold yellow]",
                                border_style="yellow",
                                box=box.ROUNDED
                            ),
                            transient=False
                        )
                        
                    elif response_type == "model_answer":
                        # 如果之前是 Thinking，停止它（保留在屏幕上）
                        if thinking_buffer and current_live:
                            stop_current_live()
                            thinking_buffer = []
                        
                        answer_buffer.append(content)
                        answer_text = "".join(answer_buffer)
                        
                        try:
                            md_content = Markdown(answer_text)
                        except Exception:
                            md_content = answer_text
                        
                        update_live(
                            Panel(
                                md_content,
                                title="[bold green]💬 Model Answer[/bold green]",
                                border_style="green",
                                box=box.ROUNDED
                            ),
                            transient=False
                        )
                        
                    elif response_type == "tool_call":
                        # 收到工具调用，停止当前的 Answer Live
                        stop_current_live()
                        
                        try:
                            tool_data = json.loads(content)
                            tool_id = tool_data.get('id', '')
                            tool_name = tool_data.get('name', '')
                            tool_args = tool_data.get('args', {})
                            
                            try:
                                args_str = json.dumps(tool_args, ensure_ascii=False, indent=2)
                            except:
                                args_str = str(tool_args)
                                
                            tool_calls[tool_id] = {
                                "name": tool_name,
                                "args": tool_args,
                                "args_str": args_str
                            }
                            
                            # 检查是否有缓存的结果
                            if tool_id in tool_results:
                                tool_result = tool_results[tool_id]
                                del tool_results[tool_id]
                                
                                result_str = str(tool_result)
                                if len(result_str) > 1000:
                                    result_str = result_str[:1000] + "\n... (truncated)"
                                    
                                console.print(Panel(
                                    Text.assemble(
                                        ("🔧 ", "bold cyan"),
                                        (f"{tool_name}\n", "bold"),
                                        ("Args: ", "dim"),
                                        (args_str, "cyan"),
                                        ("\n\n", ""),
                                        ("✅ Result:\n", "bold green"),
                                        (result_str, "green")
                                    ),
                                    title=f"[bold green]✅ {tool_name} - Complete[/bold green]",
                                    border_style="green",
                                    box=box.ROUNDED
                                ))
                                del tool_calls[tool_id]
                                
                            else:
                                # 显示 Processing 状态 (Transient=True)
                                stop_current_live()
                                current_live = Live(
                                    Panel(
                                        Text.assemble(
                                            ("🔧 ", "bold cyan"),
                                            (f"{tool_name}\n", "bold"),
                                            ("Args: ", "dim"),
                                            (args_str, "cyan"),
                                            ("\n\n", ""),
                                            ("⏳ ", "yellow"),
                                            ("Processing...", "yellow italic")
                                        ),
                                        title=f"[bold cyan]🔧 Tool Call: {tool_name}[/bold cyan]",
                                        border_style="cyan",
                                        box=box.ROUNDED
                                    ),
                                    console=console,
                                    refresh_per_second=12,
                                    transient=True
                                )
                                current_live.start()
                            
                        except json.JSONDecodeError:
                            console.print(Panel(f"Error parsing tool call: {content}", style="red"))
                        
                    elif response_type == "tool_result":
                        try:
                            result_data = json.loads(content)
                            tool_id = result_data.get('id', '')
                            tool_result = result_data.get('content', content)
                            
                            if tool_id in tool_calls:
                                # 停止 Processing Live (它会消失)
                                stop_current_live()
                                
                                tool_info = tool_calls[tool_id]
                                tool_name = tool_info["name"]
                                args_str = tool_info["args_str"]
                                
                                result_str = str(tool_result)
                                if len(result_str) > 1000:
                                    result_str = result_str[:1000] + "\n... (truncated)"
                                
                                console.print(Panel(
                                    Text.assemble(
                                        ("🔧 ", "bold cyan"),
                                        (f"{tool_name}\n", "bold"),
                                        ("Args: ", "dim"),
                                        (args_str, "cyan"),
                                        ("\n\n", ""),
                                        ("✅ Result:\n", "bold green"),
                                        (result_str, "green")
                                    ),
                                    title=f"[bold green]✅ {tool_name} - Complete[/bold green]",
                                    border_style="green",
                                    box=box.ROUNDED
                                ))
                                
                                del tool_calls[tool_id]
                            else:
                                tool_results[tool_id] = tool_result
                                
                        except json.JSONDecodeError:
                            console.print(Panel(f"Error parsing tool result: {content}", style="red"))

                    elif response_type == "error":
                        stop_current_live()
                        console.print(Panel(
                            content,
                            title="[bold red]❌ Error[/bold red]",
                            border_style="red",
                            box=box.ROUNDED
                        ))
                
                stop_current_live()
                
                # 清理状态
                tool_calls.clear()
                tool_results.clear()
                thinking_buffer.clear()
                answer_buffer.clear()
                
            except KeyboardInterrupt:
                stop_current_live()
                
                console.print("\n\n[bold yellow]⚠️  Interrupted by user (Press Ctrl+C again to exit)[/bold yellow]")
                # 询问是否真的要退出
                try:
                    console.print("[yellow]Do you want to exit? (y/n): [/yellow]", end="")
                    confirm = input().strip().lower()
                    if confirm in ["y", "yes"]:
                        console.print("[bold green]👋 Goodbye![/bold green]")
                        break
                except KeyboardInterrupt:
                    # 第二次 Ctrl+C 直接退出
                    console.print("\n[bold green]👋 Goodbye![/bold green]")
                    break
            except EOFError:
                # 处理 EOF（比如在某些终端中按 Ctrl+D）
                console.print("\n[bold green]👋 Goodbye![/bold green]")
                break
            except Exception as e:
                console.print(Panel(
                    f"{e}",
                    title="[bold red]❌ Error processing request[/bold red]",
                    border_style="red",
                    box=box.ROUNDED
                ))
                import traceback
                console.print(traceback.format_exc())
                continue
    
    except KeyboardInterrupt:
        console.print("\n\n[bold green]👋 Goodbye![/bold green]")
    except Exception as e:
        console.print(Panel(
            f"{e}",
            title="[bold red]❌ Fatal error[/bold red]",
            border_style="red",
            box=box.ROUNDED
        ))
        import traceback
        console.print(traceback.format_exc())
        sys.exit(1)
    finally:
        # 清理资源
        await cleanup_resources()

if __name__ == "__main__":
    # Windows 平台特定设置
    # if sys.platform == "win32":
    #     # 强制设置 Python IO 编码
    #     os.environ["PYTHONIOENCODING"] = "utf-8"
    #     try:
    #         # 设置控制台代码页为 UTF-8
    #         os.system('chcp 65001 >NUL')
    #     except Exception:
    #         pass

    console = Console()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[bold green]👋 Goodbye![/bold green]")
    except Exception as e:
        console.print(Panel(
            f"{e}",
            title="[bold red]❌ Fatal error[/bold red]",
            border_style="red",
            box=box.ROUNDED
        ))
        import traceback
        console.print(traceback.format_exc())
    finally:
        time.sleep(0.1)