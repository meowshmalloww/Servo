"""Ask Servo MCP server — stdio JSON-RPC 2.0.

Exposes the 36 Ask tools + 13 resources + 3 prompts over Model Context Protocol.
Identical logic to HTTP /v1/ask/*; both transports call the same ask_servo/tools.py.

Run:
  python -m tools.realityci.ask_servo.mcp_server
MCP client config (.mcp.json):
  { "mcpServers": { "ask-servo": { "command": "python", "args": ["-m","tools.realityci.ask_servo.mcp_server"], "cwd": "D:\\Servo" } } }

The server never executes arbitrary code, never invents hashes, and never
overrides deterministic promotion. Every mutating tool validates paths via
_inside() and hashes via canonical_json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root on sys.path for imports when launched via `python -m`
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.realityci.ask_servo.tools import TOOL_DESCRIPTIONS, AskToolName  # noqa: E402
from tools.realityci.ask_servo.resources import RESOURCE_TEMPLATES  # noqa: E402
from tools.realityci.ask_servo.prompts import PROMPTS  # noqa: E402


SERVER_INFO = {"name": "ask-servo", "version": "0.2.0"}


def _tool_list() -> list[dict]:
    return [{"name": n.value, "description": TOOL_DESCRIPTIONS[n], "inputSchema": {"type": "object", "additionalProperties": False, "properties": {"campaign_id": {"type": "string"}, "simulation_id": {"type": "string"}, "world_id": {"type": "string"}, "arguments": {"type": "object"}}}} for n in AskToolName]


def _resource_list() -> list[dict]:
    return [{"uri": k, "name": k, "description": v, "mimeType": "application/json"} for k, v in RESOURCE_TEMPLATES.items()]


def _prompt_list() -> list[dict]:
    return [{"name": v["name"], "description": v["description"], "arguments": v.get("arguments", [])} for v in PROMPTS.values()]


def _handle(request: dict) -> dict | None:
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result} if req_id is not None else None

    def err(code, message):
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}} if req_id is not None else None

    if method == "initialize":
        return ok({"protocolVersion": "2024-11-05", "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False}, "prompts": {"listChanged": False}}, "serverInfo": SERVER_INFO})
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return ok({"tools": _tool_list()})
    if method == "tools/call":
        # In-process calls are not executed here; HTTP control plane is the authority.
        # Return a descriptor so the client routes via HTTP /v1/ask/execute.
        name = params.get("name")
        if name not in {n.value for n in AskToolName}:
            return err(-32602, f"unknown tool: {name}")
        return ok({"content": [{"type": "text", "text": json.dumps({"tool": name, "arguments": params.get("arguments", {}), "note": "Execute via POST /v1/ask/execute or POST /v1/assistant/execute with the same tool name and arguments. MCP is the catalog; HTTP is the authority."})}], "isError": False})
    if method == "resources/list":
        return ok({"resources": _resource_list()})
    if method == "resources/read":
        uri = params.get("uri", "")
        # Resources are served by HTTP GET servo:// -> /v1/... ; MCP returns a pointer.
        if not uri.startswith("servo://"):
            return err(-32602, f"unknown resource: {uri}")
        return ok({"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps({"uri": uri, "note": "Fetch via GET http://127.0.0.1:8000/v1/... mapping. See docs/ASK_SERVO_ARCHITECTURE.md §2.3."})}]})
    if method == "resources/templates/list":
        return ok({"resourceTemplates": [{"uriTemplate": k, "name": k, "description": v} for k, v in RESOURCE_TEMPLATES.items()]})
    if method == "prompts/list":
        return ok({"prompts": _prompt_list()})
    if method == "prompts/get":
        name = params.get("name")
        if name not in PROMPTS:
            return err(-32602, f"unknown prompt: {name}")
        return ok({"description": PROMPTS[name]["description"], "messages": [{"role": "user", "content": {"type": "text", "text": f"Run prompt {name}: {PROMPTS[name]['description']}"}}]})
    if method == "ping":
        return ok({})
    return err(-32601, f"Method not found: {method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}) + "\n")
            sys.stdout.flush()
            continue
        # Handle batch
        if isinstance(request, list):
            responses = [r for r in (_handle(r) for r in request) if r is not None]
            if responses:
                sys.stdout.write(json.dumps(responses) + "\n")
                sys.stdout.flush()
            continue
        response = _handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
