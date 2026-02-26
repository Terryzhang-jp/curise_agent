"""
MCP (Model Context Protocol) stdio 客户端

启动外部 MCP server 子进程，通过 stdin/stdout JSON-RPC 2.0 通信。
将 MCP 工具转换为 ToolDef 注册到 ToolRegistry。

协议版本: 2024-11-05
通信方式: JSON-RPC 2.0 over stdio (每行一条消息)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any

from services.agent.tool_registry import ToolDef


@dataclass
class MCPConnection:
    """一个 MCP server 连接"""
    name: str
    process: subprocess.Popen
    tools: list[dict] = field(default_factory=list)
    _request_id: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def send_request(self, method: str, params: dict | None = None) -> dict | None:
        """发送 JSON-RPC 2.0 请求，返回 result（通知不等待响应）"""
        is_notification = method.startswith("notifications/")

        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if not is_notification:
            msg["id"] = self._next_id()
        if params is not None:
            msg["params"] = params

        line = json.dumps(msg, ensure_ascii=False) + "\n"

        with self._lock:
            try:
                self.process.stdin.write(line.encode("utf-8"))
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                return {"error": {"code": -1, "message": f"写入失败: {e}"}}

            if is_notification:
                return None

            try:
                while True:
                    resp_line = self.process.stdout.readline()
                    if not resp_line:
                        return {"error": {"code": -1, "message": "server 已关闭连接"}}
                    resp_line = resp_line.decode("utf-8").strip()
                    if not resp_line:
                        continue
                    try:
                        resp = json.loads(resp_line)
                    except json.JSONDecodeError:
                        continue
                    if "id" not in resp:
                        continue
                    if resp.get("id") == msg["id"]:
                        if "error" in resp:
                            return {"error": resp["error"]}
                        return resp.get("result", {})
            except (OSError, ValueError) as e:
                return {"error": {"code": -1, "message": f"读取失败: {e}"}}

    def close(self):
        """关闭子进程"""
        try:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass


class MCPClientManager:
    """管理所有 MCP server 连接"""

    def __init__(self):
        self._connections: dict[str, MCPConnection] = {}

    def connect_all(self, config_path: str) -> list[ToolDef]:
        """读取 mcp.json，启动所有 server，返回 ToolDef 列表"""
        if not os.path.exists(config_path):
            return []

        with open(config_path, "r", encoding="utf-8") as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError as e:
                print(f"[MCP] mcp.json 解析失败: {e}", file=sys.stderr)
                return []

        servers = config.get("mcpServers", {})
        if not servers:
            return []

        all_tools: list[ToolDef] = []

        for server_name, server_config in servers.items():
            try:
                tools = self._connect_server(server_name, server_config)
                all_tools.extend(tools)
            except Exception as e:
                print(f"[MCP] 连接 server '{server_name}' 失败: {e}", file=sys.stderr)

        return all_tools

    def _connect_server(self, name: str, config: dict) -> list[ToolDef]:
        """连接单个 MCP server，返回其工具列表"""
        command = config.get("command", "")
        args = config.get("args", [])
        env_overrides = config.get("env", {})

        if not command:
            raise ValueError(f"server '{name}' 缺少 command 配置")

        env = os.environ.copy()
        env.update(env_overrides)

        full_cmd = [command] + args
        try:
            process = subprocess.Popen(
                full_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            raise RuntimeError(f"命令 '{command}' 未找到，请确保已安装")
        except Exception as e:
            raise RuntimeError(f"启动 '{command}' 失败: {e}")

        conn = MCPConnection(name=name, process=process)

        init_result = conn.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "cruise-agent", "version": "2.0.0"},
        })
        if init_result and "error" in init_result:
            conn.close()
            raise RuntimeError(f"initialize 失败: {init_result['error']}")

        conn.send_request("notifications/initialized")

        tools_result = conn.send_request("tools/list")
        if tools_result is None or "error" in (tools_result if isinstance(tools_result, dict) else {}):
            conn.close()
            raise RuntimeError(f"tools/list 失败: {tools_result}")

        raw_tools = tools_result.get("tools", []) if isinstance(tools_result, dict) else []
        conn.tools = raw_tools

        self._connections[name] = conn

        tool_defs = []
        for tool_info in raw_tools:
            td = self._mcp_tool_to_tooldef(name, tool_info)
            if td:
                tool_defs.append(td)

        print(f"[MCP] '{name}' 已连接，注册 {len(tool_defs)} 个工具", file=sys.stderr)
        return tool_defs

    def _mcp_tool_to_tooldef(self, server_name: str, tool_info: dict) -> ToolDef | None:
        """将 MCP 工具定义转换为 ToolDef"""
        mcp_name = tool_info.get("name", "")
        if not mcp_name:
            return None

        description = tool_info.get("description", "")
        input_schema = tool_info.get("inputSchema", {})

        safe_server = re.sub(r"[^a-zA-Z0-9]", "_", server_name)
        safe_tool = re.sub(r"[^a-zA-Z0-9]", "_", mcp_name)
        registered_name = f"mcp_{safe_server}_{safe_tool}"

        parameters = {}
        properties = input_schema.get("properties", {})
        required_list = input_schema.get("required", [])

        for param_name, param_info in properties.items():
            json_type = param_info.get("type", "string").upper()
            type_map = {
                "STRING": "STRING",
                "NUMBER": "NUMBER",
                "INTEGER": "INTEGER",
                "BOOLEAN": "BOOLEAN",
                "ARRAY": "STRING",
                "OBJECT": "STRING",
            }
            parameters[param_name] = {
                "type": type_map.get(json_type, "STRING"),
                "description": param_info.get("description", ""),
                "required": param_name in required_list,
            }

        _server_name = server_name
        _mcp_name = mcp_name

        def call_fn(**kwargs) -> str:
            return self.call_tool(_server_name, _mcp_name, kwargs)

        call_fn.__name__ = registered_name
        call_fn.__doc__ = description

        return ToolDef(
            name=registered_name,
            fn=call_fn,
            description=f"[MCP:{server_name}] {description}",
            parameters=parameters,
            group="mcp",
        )

    def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        """调用指定 server 的工具"""
        conn = self._connections.get(server_name)
        if conn is None:
            return f"Error: MCP server '{server_name}' not connected"

        result = conn.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        if result is None:
            return "Error: MCP server no response"
        if isinstance(result, dict) and "error" in result:
            return f"Error: MCP tool error: {result['error']}"

        if isinstance(result, dict):
            content = result.get("content", [])
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            texts.append(item.get("text", ""))
                        elif item.get("type") == "image":
                            texts.append("[image data]")
                        else:
                            texts.append(str(item))
                    else:
                        texts.append(str(item))
                return "\n".join(texts) if texts else str(result)
            return str(content)
        return str(result)

    def disconnect_all(self):
        """关闭所有 MCP server 子进程"""
        for name, conn in self._connections.items():
            try:
                conn.close()
                print(f"[MCP] '{name}' 已断开", file=sys.stderr)
            except Exception as e:
                print(f"[MCP] 关闭 '{name}' 时出错: {e}", file=sys.stderr)
        self._connections.clear()

    def list_connections(self) -> list[str]:
        """列出所有已连接的 server 名称"""
        return list(self._connections.keys())
