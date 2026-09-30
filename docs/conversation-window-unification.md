# Shared Node and Group conversation windows

Node and Group conversations now share these UI responsibilities:

- `ConversationWindow.vue`: modal surface, backdrop dismissal, desktop dimensions from `agentPanel` settings, mobile viewport layout, and reconnect inert state. Non-floating node memory remains in its dock without remounting its contents.
- `ConversationHeader.vue`: title, subtitle, action slots, and the existing project `DialogCloseButton`.
- `ConversationComposerDock.vue`: constrained footer, input spacing, overflow and shared composer appearance. Node actions and group broadcast keep their existing handlers.
- `useDialogLifecycle.ts`: initial focus without scrolling or opening the mobile keyboard, Escape dismissal regardless of the previously focused element, nested modal ordering, Tab containment, and focus restoration. The expanded text editor uses this lifecycle too. Unmanaged existing dialogs block outer dismissal. Suspended cloud Board windows cannot handle keyboard dismissal.

The former workspace-specific Memory Escape branch and Group-local Escape handler were removed. The desktop workspace retains settings-back handling. Conversation surfaces remain below existing save/file dialogs and the cloud reconnect overlay. No backdrop blur was introduced.

`DesktopWorkspace.vue` already exceeds 400 lines; new responsibilities were extracted into the small shared files above and old surface CSS removed, rather than expanding its orchestration. Node messages and Group events retain separate data contracts and rendering, including existing Process loading, delivery status, task editing, and broadcast behavior.

## Verification — 2026-09-28

- TypeScript/Vue typecheck and production build passed.
- 18 existing location/session/workspace keyboard tests passed with the workspace Escape contract updated.
- Actual Chrome against the local service passed 10 checks: immediate Group Escape, nested editor Escape, preserved unsent draft, second Escape closing the outer window, common close button, backdrop dismissal, identical configured Node/Group dimensions and button styling, real history loading at the bottom, keyboard containment, and mobile viewport/close behavior. No JavaScript page errors. Productive agents received no test messages.
- Both local and public cloud frontends were updated. Cloud installation verified 67 files and retained old fingerprinted assets for existing browser sessions. Backup: `/opt/agentpark-coordinator/backups/webui-20260927T171750Z`.
- Local browser evidence: `.runtime/conversation-window/results.json`, `node.png`, `group.png`. Public Board verification: `.runtime/mobile-group/cloud-results.json`.

Physical-phone keyboard behavior is not claimed from desktop Chrome mobile emulation. No Agent runtime restart is needed for these frontend changes.
