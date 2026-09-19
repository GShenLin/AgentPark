# Node open diagnostics

Temporary measurements for investigating slow node selection. No history limits,
rendering policy, request ordering, or scrolling behavior are changed.

## Reproduce

1. For the initial timing instrumentation, restart the backend and refresh the
   browser. For the second-stage source attribution update, **only refresh the
   browser**: the existing backend file API saves the additional report, preserving
   the in-memory live output without a server restart.
2. Select another node, then left-click the affected node.
3. Keep the tab visible until it responds, then wait at least 15 seconds.
4. Optionally repeat for a small node for comparison.

Records are saved as UTF-8 JSON Lines in `logs/node-open-performance.jsonl` under
the runtime root (normally the repository). Each file rotates at 5 MiB with two
backups. Browser console records use the prefix `[NodeOpenPerformance]`.
If saving fails, the browser console reports the error. Server diagnostic disk
errors are printed to stderr without replacing the original API response.

## Correlation and scope

Each selection captures 10 seconds, with a maximum of 500 browser events. A new
selection closes and saves the previous capture; `capture_end.switched` identifies
this case. `dropped_events` identifies a capture that hit the limit. Timer delivery
can be delayed by a blocked main thread or background-tab throttling.

Browser and server records share `trace_id`; individual JSON requests share
`request_id`. Requests to save diagnostics do not trace themselves. Other JSON
requests during the capture window are included, so inspect the endpoint before
attributing work to the selected node. API URLs omit query strings; no message,
command, or live-output bodies are logged.

## Interpretation

- `board_selection_flush`, `board_focus`, `memory_shown`: stages before the memory
  requests, including the existing viewport focus and frame waits.
- `selection_watch`: the memory-selection watcher ran; the existing 70 ms settle
  timer still applies before the initial memory/live requests.
- Server phase `elapsed_ms`: time since the preceding checkpoint in that request.
  Handler entry includes dependency checks and thread-pool scheduling before entry.
  Memory phases separate config access, record loading, Markdown generation, and
  envelope/live payload assembly. `response_ready` includes the remaining handler
  work and framework serialization after the final handler checkpoint.
- Server `headers_ms`: request arrival to response headers. `body_bytes`: response
  body bytes handed to ASGI. `total_ms` also includes sending and middleware cleanup;
  it is not time until the browser displays the result.
- Browser `response_headers.elapsed_ms`: fetch start to its response continuation,
  including network time and any main-thread scheduling delay.
- `response_json.body_and_json_ms`: body consumption **plus** JSON parsing and
  scheduling delay. These are deliberately not reported as separate pure costs;
  the existing `Response.json()` path is preserved.
- `memory_applied`, `live_applied`: reactive values assigned, with content lengths.
- `vue_flush.duration_ms`: MemoryContentView before-update to updated hooks, not
  total application rendering or paint time.
- `scroll_layout.height_read_ms`: timing around the already-existing scrollHeight
  read; a large value indicates synchronous layout at that point.
- `scroll_write_ms`: timing around the already-existing scrollTop assignment.
- `frame_after_update`: two frame callbacks after the component update, a frame
  opportunity indicator, **not** a precise paint duration.
- `longtask` and `long_animation_frame`: native browser performance entries, only
  when supported. Long-frame render/style fields run to the frame end and include
  work after layout; `forced_layout_ms` sums reported script-forced layout time.
  Do not add overlapping long-task, long-frame, Vue, and scroll measurements.

The initial `selection` event records observer support and tab visibility. Compare
like-for-like runs: a restart may clear the previous live-output buffer, so always
check `live_chars` before comparing against a pre-restart stall.

## Second-stage source evidence

The frontend also writes one bounded source report per capture to
`logs/node-open-sources/<trace_id>.json` using the existing file export API. This
separate artifact shares the summary's trace ID and includes the loaded script
asset names, long-frame script entry points, source character positions, script
durations, forced layout, and explicit timings around SSE parsing and dispatch.
It does not record incoming event content. Query strings, fragments and embedded
URL credentials are omitted from source URLs. Data/blob script contents are not
included. Each report retains up to 100 frames, 50 scripts per frame, and 500 app
work measurements; dropped counts are explicit. Files remain until this temporary
investigation is cleaned up.

Source locations identify the callback entry point, not a sampled CPU stack or
necessarily the deepest expensive function. Empty script arrays are meaningful:
they must not be interpreted as proof that the application or an extension is
responsible. Chromium does not attribute isolated-world extension code or
cross-origin frame code through this API. See the
[Chrome Long Animation Frames documentation](https://developer.chrome.com/docs/web-platform/long-animation-frames).

## Live-text rendering fix and verification (2026-09-07)

The plain live answer and thinking text now use `VirtualLiveText.vue`, a separate
scroll viewport backed by TanStack Virtual. Only visible logical lines plus five
overscan lines are mounted; wrapped heights are measured by the browser. Original
text remains intact and is passed directly to the existing copy/save actions.
Changing width or wrap invalidates measured sizes while retaining the reading
anchor. New output follows the end only while the viewer is at the end. Each
graph/node has its own keyed viewer. This is line virtualization, so one unusually
large logical line is still rendered as one item. Browser find/selection operates
on mounted lines; use Copy all or Save all for the complete text.

The existing MemoryContentView exceeds 400 lines; this change extracts the new
rendering responsibility into its own component instead of expanding its scroll
implementation. Activity Markdown and stored conversation rendering remain
separate responsibilities.

The same in-memory Package1 output (1,136,463 characters, 21,355 logical lines)
was opened in the in-app browser without restarting the backend. Final trace
`016a97f6-0a7e-4352-a1e8-5ae0dda6511d` has a 103 ms longest task, versus the
earlier multi-second stalls. Update frame opportunities occurred at 242 and
263 ms after selection; these are not exact paint times. The settled DOM held
18 lines / 871 characters and was at the end (zero remaining scroll distance).

Validation: production TypeScript/Vite build and all 94 existing frontend tests
passed. A temporary browser harness exercised 21,355 generated lines, CRLF and
blank/trailing lines, Chinese/emoji text, appending new lines, growing the last
line, reading older output during append, narrow/wide resize, wrap toggling,
keyboard scrolling, text replacement, and complete copy/save event payloads.
The harness and its dev server were removed after validation. The production
bundle is served by the running backend; a page refresh loads this fix.
