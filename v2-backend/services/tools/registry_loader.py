"""
Tool auto-discovery and metadata collection.

Convention: each tool module in services/tools/ and services/agent/tools/
exposes:
    - register(registry, ctx): registers tools onto the given registry
    - TOOL_META: dict[str, ToolMetaInfo] mapping tool_name -> metadata

This module scans both packages and collects all metadata, enabling:
    - Auto-registration (no manual if-branches in __init__.py)
    - Auto-seeding DB (tool_settings.py reads from here)
    - Auto prompt descriptions (chat.py reads from here)
    - Auto display summaries (chat_storage.py reads from here)
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class ToolMetaInfo:
    """Metadata for a single tool — single source of truth."""
    display_name: str                       # Frontend display: "数据库查询"
    group: str = "utility"                  # Group for DB seed: "business", "utility", etc.
    description: str = ""                   # DB seed description (long)
    prompt_description: str = ""            # Short desc for system prompt tool list
    summary: str | Callable[[str], str] = ""  # chat_storage display summary (string or callable)
    is_enabled_default: bool = True         # Default enabled state for DB seed
    auto_register: bool = True              # If False, only register when explicitly requested


# Modules to skip during auto-scan (e.g., this file, __init__)
_SKIP_MODULES = {"registry_loader", "__init__", "mcp_client"}


def _scan_package(package_path: str, package_name: str) -> dict[str, tuple]:
    """Scan a package directory for tool modules.

    Returns dict mapping module_name -> (module_object, TOOL_META dict).
    Only includes modules that have both `register` and `TOOL_META`.
    """
    found = {}
    try:
        package = importlib.import_module(package_name)
    except ImportError as e:
        logger.warning("Cannot import package %s: %s", package_name, e)
        return found

    for finder, name, ispkg in pkgutil.iter_modules(package.__path__):
        if name in _SKIP_MODULES or ispkg:
            continue
        full_name = f"{package_name}.{name}"
        try:
            mod = importlib.import_module(full_name)
        except ImportError as e:
            logger.warning("Cannot import tool module %s: %s", full_name, e)
            continue

        if hasattr(mod, "register") and hasattr(mod, "TOOL_META"):
            found[name] = (mod, mod.TOOL_META)

    return found


def discover_all_tool_meta() -> dict[str, ToolMetaInfo]:
    """Scan all tool packages and collect TOOL_META into a flat dict.

    Returns dict mapping tool_name -> ToolMetaInfo (merged from all packages).
    """
    all_meta: dict[str, ToolMetaInfo] = {}

    # Scan business tools (services/tools/)
    for name, (mod, meta) in _scan_package("services.tools", "services.tools").items():
        for tool_name, info in meta.items():
            all_meta[tool_name] = info

    # Scan agent general-purpose tools (services/agent/tools/)
    for name, (mod, meta) in _scan_package("services.agent.tools", "services.agent.tools").items():
        for tool_name, info in meta.items():
            all_meta[tool_name] = info

    return all_meta


def get_tool_summaries() -> dict[str, str | Callable[[str], str]]:
    """Build the summary map for chat_storage from TOOL_META.

    Returns dict mapping tool_name -> summary string or callable.
    """
    result = {}
    for tool_name, info in discover_all_tool_meta().items():
        if info.summary:
            result[tool_name] = info.summary
        elif info.display_name:
            result[tool_name] = info.display_name
    return result


def get_prompt_descriptions() -> dict[str, str]:
    """Build the tool description map for system prompt from TOOL_META.

    Returns dict mapping tool_name -> short description for prompt.
    """
    result = {}
    for tool_name, info in discover_all_tool_meta().items():
        result[tool_name] = info.prompt_description or info.display_name
    return result


def get_builtin_tools_seed() -> list[dict]:
    """Generate BUILTIN_TOOLS seed data from TOOL_META for tool_settings.py.

    Returns list of dicts ready for ToolConfig model creation.
    """
    result = []
    for tool_name, info in discover_all_tool_meta().items():
        result.append({
            "tool_name": tool_name,
            "group_name": info.group,
            "display_name": info.display_name,
            "description": info.description or info.prompt_description,
            "is_enabled": info.is_enabled_default,
        })
    return result


def auto_register_tools(registry, ctx, enabled_tools: set[str] | None = None):
    """Auto-register all discovered tools based on enabled_tools set.

    Args:
        registry: ToolRegistry instance.
        ctx: ToolContext instance.
        enabled_tools: If None, register all auto_register=True tools.
                       If set, only register tools in the set.
    """
    def _should_register(tool_name: str, meta: ToolMetaInfo) -> bool:
        if enabled_tools is None:
            return meta.auto_register
        return tool_name in enabled_tools

    # Scan business tools
    for name, (mod, meta_dict) in _scan_package("services.tools", "services.tools").items():
        should_load = any(_should_register(tn, mi) for tn, mi in meta_dict.items())
        if should_load:
            try:
                mod.register(registry, ctx)
            except Exception as e:
                logger.error("Failed to register tools from %s: %s", name, e)

    # Scan agent general-purpose tools
    for name, (mod, meta_dict) in _scan_package("services.agent.tools", "services.agent.tools").items():
        should_load = any(_should_register(tn, mi) for tn, mi in meta_dict.items())
        if should_load:
            try:
                mod.register(registry, ctx)
            except Exception as e:
                logger.error("Failed to register tools from %s: %s", name, e)

    # Post-registration filter: remove tools not in enabled_tools
    if enabled_tools is not None:
        for name in list(registry.names()):
            if name not in enabled_tools:
                registry.remove(name)
