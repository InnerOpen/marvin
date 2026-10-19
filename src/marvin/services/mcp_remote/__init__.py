"""Marvin's remote MCP server with OAuth sign-in (tasks/mcp-oauth-plan.md).

Built in slices behind the `remote_mcp` platform switch (services/platform_policy.py), off by default. So far:
the policy and the discovery metadata (`policy.py`); the authorization server, the consent page and `/mcp` follow.
"""
