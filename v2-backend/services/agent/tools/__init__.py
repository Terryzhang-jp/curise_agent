"""
Agent general-purpose tools package — config-driven tool registration.

Usage:
    from services.agent.tools import create_default_registry
    registry = create_default_registry()

Supports:
- tool_config.yaml to enable/disable built-in tool groups
- mcp.json for external MCP tool servers
- Permission rules (allow/ask/deny)
"""

import os

from services.agent.tools import reasoning, search, filesystem, utility, todo, shell, web, skill

# Tool group name → module mapping
_GROUP_MODULES = {
    "reasoning": reasoning,
    "search": search,
    "filesystem": filesystem,
    "utility": utility,
    "todo": todo,
    "shell": shell,
    "web": web,
    "skill": skill,
}

# Default config: shell disabled for safety, everything else enabled
_DEFAULT_BUILTIN = {g: (g != "shell") for g in _GROUP_MODULES}

# Global MCP manager (needs cleanup on shutdown)
_mcp_manager = None


def _load_config(config_path: str | None = None) -> dict:
    """Load tool_config.yaml. Returns default (all enabled except shell) if file not found."""
    if config_path is None or not os.path.exists(config_path):
        return {"builtin_tools": dict(_DEFAULT_BUILTIN), "permissions": []}

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Simple YAML parser (supports key: value and list format)
    config = {"builtin_tools": {}, "permissions": []}
    current_section = None
    current_list_item = None

    def _strip_comment(s: str) -> str:
        idx = s.find("  #")
        if idx >= 0:
            return s[:idx].strip()
        idx = s.find(" #")
        if idx >= 0:
            return s[:idx].strip()
        return s.strip()

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not line.startswith(" ") and ":" in stripped:
            section_key = stripped.split(":", 1)[0].strip()
            section_val = stripped.split(":", 1)[1].strip()
            if not section_val or section_val == "[]":
                current_section = section_key
                current_list_item = None
                continue

        if current_section == "builtin_tools" and ":" in stripped:
            key, val = stripped.split(":", 1)
            config["builtin_tools"][key.strip()] = _strip_comment(val).lower() == "true"

        elif current_section == "permissions":
            if stripped.startswith("- "):
                current_list_item = {}
                config["permissions"].append(current_list_item)
                item_content = stripped[2:].strip()
                if ":" in item_content:
                    key, val = item_content.split(":", 1)
                    current_list_item[key.strip()] = _strip_comment(val).strip('"').strip("'")
            elif current_list_item is not None and ":" in stripped:
                key, val = stripped.split(":", 1)
                current_list_item[key.strip()] = _strip_comment(val).strip('"').strip("'")

    return config


def create_default_registry(config_path: str | None = None, ctx=None):
    """Create a ToolRegistry with general-purpose tools, driven by config.

    Args:
        config_path: Path to tool_config.yaml (optional).
        ctx: ToolContext instance for stateful tools (optional, creates default if None).

    Returns:
        ToolRegistry with general-purpose tools registered.
    """
    global _mcp_manager

    from services.agent.tool_registry import ToolRegistry

    registry = ToolRegistry()
    config = _load_config(config_path)
    builtin = config.get("builtin_tools", _DEFAULT_BUILTIN)

    # Register built-in tool groups
    for group_name, module in _GROUP_MODULES.items():
        if builtin.get(group_name, _DEFAULT_BUILTIN.get(group_name, True)):
            module.register(registry, ctx)

    # Load permission rules
    permissions = config.get("permissions", [])
    if permissions:
        registry.set_permissions(permissions)

    # MCP tool registration (disabled by default — only if mcp.json exists)
    mcp_config = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp.json")
    if os.path.exists(mcp_config):
        from services.agent.tools.mcp_client import MCPClientManager
        _mcp_manager = MCPClientManager()
        mcp_tools = _mcp_manager.connect_all(mcp_config)
        for td in mcp_tools:
            registry.register(td)

    return registry


def shutdown_mcp():
    """关闭所有 MCP 连接"""
    global _mcp_manager
    if _mcp_manager:
        _mcp_manager.disconnect_all()
        _mcp_manager = None
