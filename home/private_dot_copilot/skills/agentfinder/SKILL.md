---
name: agentfinder
description: >-
  Discover installable MCP servers, tools, skills, and agents through GitHub
  Agent Finder. Use when the user wants to find a tool, MCP server, skill,
  agent, connector, or integration for a task or third-party service.
argument-hint: <what you want to find>
---

# Agent Finder

Use this skill when the user asks to find an MCP server, tool, skill, agent, connector, or integration for a task.
Agent Finder implements Agentic Resource Discovery (ARD) and searches GitHub's public Agent Finder catalog.

Do not use this skill for purely local tasks such as editing files, writing code without external integrations, running git, shell work, or math.

## Built-in discovery endpoint

Use GitHub Agent Finder unless the user explicitly names another ARD service.

```text
https://agentfinder.github.com/api/v1/search
```

Do not ask the user for this URL.
No authentication is required for the default endpoint.

If the user explicitly gives another ARD service base URL such as `https://host/api/v1`, derive endpoints from it:

- Search endpoint: append `/search`
- MCP endpoint: append `/mcp`

## Search workflow

Invoke this skill as `/agentfinder <query>`, where `<query>` is the task or integration the user wants to find.

Send the task as an ARD `query` object:

```bash
curl -s https://agentfinder.github.com/api/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query":{"text":"<the user task in plain language>"},"pageSize":5}'
```

Use `query.filter` only when the user asks for a specific resource type.

```json
{
  "query": {
    "text": "find a PostgreSQL MCP server",
    "filter": {
      "type": ["application/mcp-server+json"]
    }
  },
  "pageSize": 5
}
```

## Presenting results

The response shape is `{ "results": [ ... ] }`.
For each result, show a numbered list with:

- `displayName`
- `mediaType`
- `url`
- `identifier`
- `source`
- `score`

State that `score` is relevance only.
It is not a trust, security, or safety rating.

## Installation rule

Never install, add, enable, or connect a returned resource automatically.
Installation requires an explicit user request after the user chooses a result.

When the user chooses a result, explain the next step for that resource type:

| Resource type | Next step |
|---|---|
| `application/mcp-server+json` | Add the returned `url` as an MCP server through the client's MCP server configuration flow. |
| `application/ai-skill` | Install the skill from the returned `url`. |
| Other media types | Connect to the returned `url` using that resource's protocol or documentation. |

Stop after giving the installation instruction unless the user explicitly asks you to make the change.

## Reference

- GitHub Docs: https://docs.github.com/en/copilot/concepts/mcp-management#agent-finder
- Catalog browser: https://github.com/agentfinder
