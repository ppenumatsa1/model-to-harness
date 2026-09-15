from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class DiagnosticToolName(StrEnum):
    ORDER = "read_order"
    PAYMENT = "read_payment"
    INVENTORY = "read_inventory"
    DIAGNOSTIC = "read_diagnostic"


class ToolAccessDeniedError(PermissionError):
    pass


@dataclass(frozen=True)
class ReadOnlyDiagnosticTool:
    name: DiagnosticToolName
    invoke: Callable[[], dict[str, Any]]


class ReadOnlyDiagnosticToolRegistry:
    """A bounded local diagnostic surface; remediation never enters this registry."""

    def __init__(self, tools: tuple[ReadOnlyDiagnosticTool, ...]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @property
    def names(self) -> tuple[DiagnosticToolName, ...]:
        return tuple(sorted(self._tools, key=str))

    def call(self, name: str) -> dict[str, Any]:
        try:
            tool_name = DiagnosticToolName(name)
            tool = self._tools[tool_name]
        except (KeyError, ValueError) as error:
            raise ToolAccessDeniedError("diagnostic tool is not permitted") from error
        return tool.invoke()
