# Shared node/group composer — 2026-09-27

NodeInputDock and GroupComposer now render the same MessageComposer. Shared
useMessageAttachments owns file selection uploads, clipboard image/file uploads,
mixed clipboard text insertion, internal/native drops, deduplication and upload
status. MessageComposer supplies previews/removal, expanded editing, recording
controls and IME-aware Enter handling. Group-specific sending and node-specific
Goal behavior stay with their respective callers.

PublishMessage now has a strict typed attachments list and requires text or at
least one resource. The event and idempotency record retain attachment metadata.
The durable queue still contains references only. GroupNotificationRun resolves
authorized events and adds real resource parts to the normal node input envelope;
the existing provider adapter sends local image bytes and exposes document paths.
Private recipients and membership revocation apply to attachments as to text.

## Verification

- vue-tsc and canonical Vite production build passed. Deployed instance
  `83eaa4a6e9834754967e7d232d44c88b`, PID4048; restart worker13780. All graph runners
  had zero active work before restart; checkpoint captured zero nodes.
- 36 focused domain/API/delivery tests passed. Added attachment-only/invalid input,
  attachment-sensitive idempotency, restored outbox delivery to both members,
  real image-byte provider adaptation and private/left-member exclusion checks.
- Installed Chrome against the deployed service: real uploads from file picker,
  image/file paste and mixed text, file drop, removal, loaded image preview,
  history links/previews, attachment-only send, upload-time Enter/button guard,
  IME confirmation, injected503 preserving draft/resources and same-ID retry.
  Node dock picker/paste regression also passed. No page errors.
- Clipboard tests dispatch browser DataTransfer/ClipboardEvent objects with real
  File data; this does not certify every Windows Explorer/browser clipboard format.
- Two actual GPT_Official/gpt-6-astra members received the final image and document
  broadcast. Both described the red square, green circle and42 and read token
  GROUP-FILE-7319 from brief.txt. Their persisted user messages contain image/doc
  resource parts. Initial isolated UI-test nodes lacked a provider; that test setup
  was corrected explicitly before the successful model run, not masked as delivery.
- Test group dissolved afterward; existing test nodes preserved, paused, and their
  original provider/model/tools/instruction fields restored. No game task changes.

Evidence: `.runtime/group-attachments/browser.cjs`, `browser.json`,
`group-composer.png`, `live-receipt.json`; `.runtime/restart-worker-13780.log` and
`.runtime/restart-build-13780-1.log`. Microphone capture was not exercised in this
run; it reuses the existing recorder and shared upload path.
