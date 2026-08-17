---
name: smart-data-agent-report
description: Use the once-installed Universal Bridge to discover systems, read authorized context, synchronize analyses, execute allowlisted configuration actions, and return review-only learning evidence.
---

# Universal Bridge for WorkBuddy

Bridge is installed once. Before every task involving a backend system, run:

```sh
SDA bridge --channel workbuddy systems --json
```

Match the user's words to an exact system `id`, `label`, or `aliases`. Never
choose the first/default system or infer a tenant, URL, path, token or action.
Ask the user when the match is absent or ambiguous.

Every registered system exposes four stable modules:

1. Synchronize analysis with `sync --system <id> --operation-id <run-id>
   --input <file>`.
2. Perform backend configuration such as canvas creation only through an exact
   allowlisted action using `action --system <id> --action <name>
   --operation-id <stable-id> --input <file>`.
3. Read authorized data/content/policy by calling `context --system <id>` and
   then `read --system <id> --resource <name> --input <file>`. SDA raw-table
   reads use exact source keys, required columns and at most 500 rows.
4. After every successful analysis, sync or configuration operation,
   automatically call `evidence --system <id> --operation-id <same-id>
   --input <file>`. Evidence is review-only memory/Skill material and is never
   activated automatically.

Packages may contain exact references, used fields, question, method, logic
steps, findings, assumptions and limitations. Never include transcripts,
original files, raw/unused rows, credentials, local paths or client-selected
identity. Remove temporary files after success and report only the target
system, result ID and candidate acceptance state.

When an administrator registers another system in the server-side Bridge, this
installed plugin discovers it on the next task. Do not reinstall the plugin.
