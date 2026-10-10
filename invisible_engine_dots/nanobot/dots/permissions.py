"""Which permission of architecture section 7 each tool of the Dot exercises.

This is the one list of the Dot's tools. The policy gate decides a call by it
(gate.py), the projection offers the model only the tools in it whose
permission is not denied (projection.py), and `tool.called` reports the
permission and its target (what of the call may be shown, targets.py) from it.
A tool that is not in the table is neither offered nor allowed, and reports an
empty permission and no target. The table also says which arguments of a call
an approval request may carry (`tool_arguments`).

The browser tools are rows like the others. Every one of them is served by the
BrowserManager (browser.py) and so by `invisible-playwright-mcp`, the only
browser of a Dot: a tool that browses another way has no row to be in.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from nanobot.dots import targets
from nanobot.dots.protocol import TOOL_TARGET_MAX

if TYPE_CHECKING:
    from nanobot.agent.tools.base import Tool
    from nanobot.agent.tools.exec_session import ExecSessionManager
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.cron.service import CronService
    from nanobot.dots.browser import BrowserManager
    from nanobot.dots.computer import Computer


@dataclass(frozen=True)
class ToolDeps:
    """Dependencies required to instantiate the Dot's tools."""

    computer: Computer
    exec_session_manager: ExecSessionManager
    cron_service: CronService
    browser: BrowserManager


@dataclass(frozen=True)
class ToolEntry:
    """What the contract knows of one tool.

    permission: the key of the host's permission map the tool exercises.
    build: factory taking ToolDeps to instantiate the Tool.
    target: from the call's arguments, the one line `tool.called` shows of it (None: nothing).
    starts_terminal: from the call's arguments, whether it starts a terminal session.
    arguments: from the call's arguments, the ones an `approval.requested` shows the person.
    """

    permission: str
    build: Callable[[ToolDeps], Tool]
    target: Callable[[Mapping[str, Any]], str | None]
    # Whether the call starts a terminal session, which `tool.called` marks (`tty`); no other tool does.
    starts_terminal: Callable[[Mapping[str, Any]], bool] = targets.never_starts_terminal
    arguments: Callable[[Mapping[str, Any]], dict[str, Any]] = targets.all_arguments


def _build_exec(deps: ToolDeps) -> Tool:
    from nanobot.agent.tools.shell import ExecTool

    return ExecTool(computer=deps.computer, session_manager=deps.exec_session_manager)


def _build_exec_session(deps: ToolDeps) -> Tool:
    from nanobot.agent.tools.exec_session import ExecSessionTool

    return ExecSessionTool(manager=deps.exec_session_manager)


def _build_list_exec_sessions(deps: ToolDeps) -> Tool:
    from nanobot.agent.tools.exec_session import ListExecSessionsTool

    return ListExecSessionsTool(manager=deps.exec_session_manager)


def _build_read_file(deps: ToolDeps) -> Tool:
    from nanobot.agent.tools.filesystem import ReadFileTool

    return ReadFileTool(computer=deps.computer)


def _build_list_dir(deps: ToolDeps) -> Tool:
    from nanobot.agent.tools.filesystem import ListDirTool

    return ListDirTool(computer=deps.computer)


def _build_find_files(deps: ToolDeps) -> Tool:
    from nanobot.agent.tools.search import FindFilesTool

    return FindFilesTool(computer=deps.computer)


def _build_grep(deps: ToolDeps) -> Tool:
    from nanobot.agent.tools.search import GrepTool

    return GrepTool(computer=deps.computer)


def _build_write_file(deps: ToolDeps) -> Tool:
    from nanobot.agent.tools.filesystem import WriteFileTool

    return WriteFileTool(computer=deps.computer)


def _build_edit_file(deps: ToolDeps) -> Tool:
    from nanobot.agent.tools.filesystem import EditFileTool

    return EditFileTool(computer=deps.computer)


def _build_apply_patch(deps: ToolDeps) -> Tool:
    from nanobot.agent.tools.apply_patch import ApplyPatchTool

    return ApplyPatchTool(computer=deps.computer)


def _build_cron(deps: ToolDeps) -> Tool:
    from nanobot.agent.tools.cron import CronTool

    return CronTool(cron_service=deps.cron_service)


def _build_browser_identity_list(deps: ToolDeps) -> Tool:
    from nanobot.dots.browser_tools import BrowserIdentityListTool

    return BrowserIdentityListTool(deps.browser)


def _build_browser_identity_create(deps: ToolDeps) -> Tool:
    from nanobot.dots.browser_tools import BrowserIdentityCreateTool

    return BrowserIdentityCreateTool(deps.browser)


def _build_browser_identity_delete(deps: ToolDeps) -> Tool:
    from nanobot.dots.browser_tools import BrowserIdentityDeleteTool

    return BrowserIdentityDeleteTool(deps.browser)


def _build_browser_identity_launch(deps: ToolDeps) -> Tool:
    from nanobot.dots.browser_tools import BrowserIdentityLaunchTool

    return BrowserIdentityLaunchTool(deps.browser)


def _build_browser_identity_close(deps: ToolDeps) -> Tool:
    from nanobot.dots.browser_tools import BrowserIdentityCloseTool

    return BrowserIdentityCloseTool(deps.browser)


def _build_page_tool(name: str) -> Callable[[ToolDeps], Tool]:
    """The builder of a page tool: browser_tools.PAGE_TOOLS says what it calls."""

    def build(deps: ToolDeps) -> Tool:
        from nanobot.dots.browser_tools import PAGE_TOOLS, BrowserPageTool

        return BrowserPageTool(deps.browser, PAGE_TOOLS[name])

    return build


def _build_computer_screenshot(deps: ToolDeps) -> Tool:
    from nanobot.dots.browser_tools import ComputerScreenshotTool

    return ComputerScreenshotTool(deps.computer)


TOOL_PERMISSIONS: Mapping[str, ToolEntry] = MappingProxyType(
    {
        "exec": ToolEntry("computer.exec", _build_exec, targets.exec_target, starts_terminal=targets.exec_starts_terminal),
        "exec_session": ToolEntry("computer.exec", _build_exec_session, targets.exec_session_target),
        "list_exec_sessions": ToolEntry("computer.exec", _build_list_exec_sessions, targets.no_target),
        "read_file": ToolEntry("files.read", _build_read_file, targets.path_target),
        "list_dir": ToolEntry("files.read", _build_list_dir, targets.path_target),
        "find_files": ToolEntry("files.read", _build_find_files, targets.find_files_target),
        "grep": ToolEntry("files.read", _build_grep, targets.grep_target),
        "write_file": ToolEntry("files.write", _build_write_file, targets.path_target),
        "edit_file": ToolEntry("files.write", _build_edit_file, targets.path_target),
        "apply_patch": ToolEntry("files.write", _build_apply_patch, targets.apply_patch_target),
        "cron": ToolEntry("automations", _build_cron, targets.cron_target),
        "computer_screenshot": ToolEntry("computer.screenshot", _build_computer_screenshot, targets.no_target),
        "browser_identity_list": ToolEntry("browser.identity.list", _build_browser_identity_list, targets.no_target),
        "browser_identity_create": ToolEntry("browser.identity.create", _build_browser_identity_create, targets.identity_name_target, arguments=targets.identity_create_arguments),
        "browser_identity_delete": ToolEntry("browser.identity.delete", _build_browser_identity_delete, targets.identity_target),
        "browser_identity_launch": ToolEntry("browser.identity.launch", _build_browser_identity_launch, targets.identity_target),
        "browser_identity_close": ToolEntry("browser.identity.close", _build_browser_identity_close, targets.identity_target),
        "browser_navigate": ToolEntry("browser.navigate", _build_page_tool("browser_navigate"), targets.browser_navigate_target, arguments=targets.navigate_arguments),
        "browser_snapshot": ToolEntry("browser.read", _build_page_tool("browser_snapshot"), targets.browser_identity_only_target),
        "browser_read_text": ToolEntry("browser.read", _build_page_tool("browser_read_text"), targets.browser_selector_target),
        "browser_screenshot": ToolEntry("browser.read", _build_page_tool("browser_screenshot"), targets.browser_identity_only_target),
        "browser_click": ToolEntry("browser.act", _build_page_tool("browser_click"), targets.browser_selector_target),
        "browser_click_at": ToolEntry("browser.act", _build_page_tool("browser_click_at"), targets.browser_click_at_target),
        "browser_type": ToolEntry("browser.act", _build_page_tool("browser_type"), targets.browser_selector_target),
        "browser_press_key": ToolEntry("browser.act", _build_page_tool("browser_press_key"), targets.browser_press_key_target),
        "browser_select_option": ToolEntry("browser.act", _build_page_tool("browser_select_option"), targets.browser_selector_target),
        "browser_scroll": ToolEntry("browser.act", _build_page_tool("browser_scroll"), targets.browser_scroll_target),
    }
)


def tool_permission(tool_name: str) -> str:
    """The permission a tool exercises, or "" for a tool that is not the Dot's."""
    entry = TOOL_PERMISSIONS.get(tool_name)
    return entry.permission if entry else ""


def tool_target(tool_name: str, params: Any) -> str | None:
    """The line `tool.called` shows of a call: at most TOOL_TARGET_MAX characters, or None.

    None for a tool that is not the Dot's, for arguments that are not an object and for a call with
    nothing to name.
    """
    entry = TOOL_PERMISSIONS.get(tool_name)
    if entry is None or not isinstance(params, Mapping):
        return None
    target = entry.target(params)
    return targets.clip(target, TOOL_TARGET_MAX) if target else None


def tool_starts_terminal(tool_name: str, params: Any) -> bool:
    """Whether the call starts a terminal session (false for a tool that is not the Dot's, or odd arguments)."""
    entry = TOOL_PERMISSIONS.get(tool_name)
    if entry is None or not isinstance(params, Mapping):
        return False
    return entry.starts_terminal(params)


def tool_arguments(tool_name: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """The arguments of a call as an `approval.requested` may carry them: all of them, bar a secret the table redacts."""
    entry = TOOL_PERMISSIONS.get(tool_name)
    return entry.arguments(params) if entry else dict(params)


def offered_tools(permissions: Mapping[str, str]) -> list[str]:
    """The tools the model is offered, sorted: those whose permission is allow or ask (a permission missing
    from the map is deny)."""
    return sorted(name for name, entry in TOOL_PERMISSIONS.items() if permissions.get(entry.permission) in ("allow", "ask"))


def tool_table(registry: ToolRegistry, offered: Collection[str]) -> list[dict[str, Any]]:
    """One row per tool of the table, as `GET /tools` shows it: the name, the permission it exercises,
    whether the model is offered it now (`offered` is what the projection offers) and what its schema says
    it does. The rows are in the table's order, which groups the tools by permission."""
    rows: list[dict[str, Any]] = []
    for name, entry in TOOL_PERMISSIONS.items():
        tool = registry.get(name)
        if tool is None:
            raise LookupError(f'the registry has no tool "{name}" of the permission table')
        rows.append(
            {"name": name, "permission": entry.permission, "offered": name in offered, "description": tool.description}
        )
    return rows


def build_registry(deps: ToolDeps) -> ToolRegistry:
    """Register exactly the tools of the permission table on a new registry."""
    from nanobot.agent.tools.registry import ToolRegistry

    registry = ToolRegistry()
    for entry in TOOL_PERMISSIONS.values():
        registry.register(entry.build(deps))
    return registry

