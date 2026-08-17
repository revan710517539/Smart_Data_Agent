---
name: smart-data-agent-bridge
description: Use the once-installed Universal Bridge to discover backend systems, read authorized context, synchronize analyses, execute allowlisted configuration actions, and return review-only learning evidence. Use whenever the user names a connected system or asks to read, analyze, synchronize, configure, create, or update content in one.
---

# Universal Bridge for Codex

Use `$HOME/.local/bin/SDA` on macOS or
`%LOCALAPPDATA%\SmartDataAgentBridge\bin\SDA.cmd` on Windows. Always pass
`--token-keychain-service smart-data-agent-bridge-codex`.

The Bridge is installed once. At the beginning of every connected-system task,
run `SDA bridge --channel codex systems --json`. Resolve an exact system by its
`id`, `label`, or `aliases`. Never use the first system, a default system, a
guessed tenant, URL, file path, or credential. If the user's words match zero
or multiple systems, ask them to choose.

The manifest exposes the same four modules for every system:

1. `analysis_sync`: after a successful analysis, build a bounded package with
   a stable run ID and call `SDA bridge --channel codex sync --system <id>
   --operation-id <run-id> --input <file>`.
2. `configuration`: for requests such as creating a canvas or changing an
   approved backend configuration, use only an exact manifest action and call
   `SDA bridge --channel codex action --system <id> --action <name>
   --operation-id <stable-id> --input <file>`. Never invent an action.
3. `read`: call `context --system <id>` first, then read only an allowlisted
   resource with `read --system <id> --resource <name> --input <file>`. For
   SDA raw rows, use resource `raw_table.rows`, exact `source_key`, necessary
   columns, and at most 500 rows.
4. `learning`: after a successful analysis, synchronization, or configuration
   operation, automatically return a bounded evidence package with `evidence
   --system <id> --operation-id <same-id> --input <file>`. Evidence creates
   only review candidates; it never activates memory or a Skill.

Evidence may contain exact references, used fields, question, methodology,
logic steps, findings, assumptions and limitations. It must not contain a
conversation transcript, raw/unused rows, original files, credentials, local
paths or identity overrides. Remove temporary packages after success and tell
the user only the target system, result ID and candidate acceptance state.

When the server administrator adds a later system to the Bridge registry, this
same Skill discovers it automatically. Do not reinstall or edit the Skill.
