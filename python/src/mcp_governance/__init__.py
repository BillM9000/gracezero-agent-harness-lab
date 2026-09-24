"""Governing MCP servers across an organization (chapter 13).

Three questions, and the module that answers each one:

- Which servers may run at all? catalog.py checks the catalog of approved servers,
  catalog/servers.toml, against the rules' data in catalog/policy.toml, as agent_policy checks agent
  definitions (chapter 18), and turns the catalog into the allowlist a host enforces.
- As whom does a call run, and what may it do? tokens.py holds the checks an MCP server makes on
  every access token (issued by the issuer it trusts, for it alone, unexpired), and a test issuer
  that stands in for an authorization server. resource_server.py puts those checks, and the scopes
  each operation needs, in front of any MCP server that speaks Streamable HTTP.
- What happened? audit.py writes one record for every request, refused or not.

python -m mcp_governance checks the catalog; allowlist and audit are its other commands.
Nothing here imports the helpdesk: the helpdesk's MCP server (helpdesk/mcp_server.py) uses it.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

PYTHON = Path(__file__).resolve().parents[2]
CATALOG = PYTHON / "catalog"
SERVERS = CATALOG / "servers.toml"
POLICY = CATALOG / "policy.toml"


def run_dir() -> Path:
    """Where the lab keeps what it writes as it runs: the test issuer's key and the audit log.

    python/.run by default, which git ignores. HELPDESK_RUN_DIR moves it, so tests never touch it.
    """
    return Path(os.environ.get("HELPDESK_RUN_DIR") or PYTHON / ".run")


def load(path: Path) -> dict[str, Any]:
    """Parse one TOML file. Raises tomllib.TOMLDecodeError, with the line, if it isn't valid TOML."""
    return tomllib.loads(path.read_text(encoding="utf-8"))
