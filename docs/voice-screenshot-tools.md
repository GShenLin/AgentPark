# Voice screenshot tools

`capture_execution_screen` captures one full display on the node's actual execution
device. An empty `display_id` selects that device's primary display. The result
includes the display catalog so the model can explicitly request another display.
There is no screen-sharing UI, browser display capture, video preview, frame timer
or RTC screen publisher. Voice start does not capture anything.

The authenticated call owner invokes `POST /api/nodes/instances/{node}/voice/{session}/screenshot`
with `{request_id, display_id}`. The tool call ID is the request ID: retries return
the same acknowledged receipt, and conflicting retries fail without recapturing.
The execution server delivers pixels directly into the existing Realtime call;
the browser receives only metadata, never a screenshot data URL.

The model can call `annotate_screen` with the returned `frame_id`. Its endpoint
accepts the drawing directly, starts the native overlay when needed, and uses the
captured display's physical geometry. No enable button, browser heartbeat or
sharing state is required. Clear requires no screenshot. Hangup closes the overlay;
the native process also exits when its execution server exits.

Each lease and provider context retain at most 20 screenshot identities. A capture
or delivery failure is a tool error; it does not close audio. Device changes during
capture cannot bind a stale result. A screenshot from another execution target or
changed display layout cannot be drawn on the current desktop; a fresh capture is
required. These are data/coordinate checks, not user approval steps.

`VoiceProvider.tools()` and `VoiceProvider.instructions()` own the common tool
catalog. All transports use the same `voiceTools` argument parser, task runner,
execution-device capture and annotation services. Providers only encode their
tool envelopes and results. Immediate server-side feedback uses the owned
`/tools/{call_id}/result` endpoint; background task progress still comes from the
node's authoritative task records. Tool errors do not close the audio session.

OpenAI Realtime inserts images through its server-side image sink. Volcengine RTC
enables vision and sends each JPEG directly to its AI bot using the documented RTS
`ctrl`/`ExternalTextToLLM` image protocol via `SendRoomUnicast`. Large images are
split into ordered Base64 fragments; only the final fragment triggers the image
prompt. No image bytes travel through the browser, no video track is published,
and no other node or model analyzes the image on the voice model's behalf.

RTC processes that image prompt after the pending function turn ends. Its result
adapter therefore acknowledges capture as pending visual input, instead of asking
the earlier text-only turn to describe an image it does not yet have. The image
message then answers the user's original question. `image_frame_id` is a typed
result field and must belong to the call's captured frames. This is message
sequencing, not an additional connection check or user confirmation.

The native Doubao speech adapter also inherits the common tools and feedback
path; it is a separate protocol from `Volcengine_RTC` and does not currently have
an image sink. Do not infer its image support from the RTC adapter or send OpenAI
image events to it. Current execution capture/native overlay support is Windows.
