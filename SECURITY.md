# Security

This repository is a teaching lab, not a service: nothing here is deployed, and its helpdesk, staff and customers are invented. It does teach guardrails, though, and a guard that doesn't hold what it claims is a real problem, for the lab and for anyone who copies it.

## Reporting a vulnerability

Please report it privately, not in a public issue: on the repository's GitHub page, open the Security tab and choose "Report a vulnerability". Say what the problem is, the commit or tag you found it at, and the commands that show it.

Worth reporting, for example: a check or a hook that can be passed without the fix it asks for; one of the destructive-command guard's rules that a command slips past (`tools/hooks/guard-rules.mjs`); a way for a customer's text to act as an instruction to the triage assistant (chapter 20); the MCP server's front door accepting a token it should refuse (chapter 13); or a download that isn't checked against its hash (chapter 20).

## Credentials

The lab never needs a credential to set up, check or run on the mock. Only a command given `--real` does, and it reads one from your environment, such as `ANTHROPIC_API_KEY`. Never commit a key, a token or a password here, even a fake-looking one; if you ever do, revoke it at the provider first, then remove it. The MCP server's test issuer makes its signing key when it runs, in a folder git ignores (python/.run).
