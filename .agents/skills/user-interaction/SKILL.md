---
name: user-interaction
description: Notify or consult users through WebUI dialogs. Activate when user information, confirmation, or a decision is needed, or when repeated tool failures leave no meaningful progress and the user should be told or asked how to proceed.
---

# User Interaction

Use this skill when user involvement can clarify, unblock, or appropriately stop the current work.

- If the same failure recurs after applying the tool's prescribed recovery, do not continue the same retry loop. Briefly summarize what failed and the current blocker for the user.
- Use `tips` for a non-blocking notice when work can safely continue with a different productive approach.
- Use `ask_user` when progress requires information, confirmation, a choice, an external action, or a decision about whether to continue. State what was attempted, the exact blocker, and the concrete options or requested input.
- Do not interrupt the user for an ordinary recoverable error when a bounded, materially different next step remains.
- Act only on submitted responses, then close this skill when user interaction is no longer needed.
