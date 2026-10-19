# Voice operation failure boundaries

The audio session owns microphone and transport lifetime. A failed optional
operation must report its outcome without releasing those resources.

| Failure | Scope and behavior |
| --- | --- |
| Malformed model tool arguments, including invalid annotation sizes | Strict validation rejects the invocation; a failed tool result with the original call ID explains how to correct it. No native drawing or draft mutation occurs. |
| Unavailable composer, conflicting edit, unavailable native overlays | Only that tool fails and returns its error to the model. |
| Duplicate call ID with different payload | Do not execute it again; show the conflict and retain the call. |
| Single response or transcription failure | Show the failure; the next utterance can continue. |
| Correlated context/result insertion rejection | Reject that delivery, keep its cursor unacknowledged, and display the error; retain audio. |
| Correlated screenshot delivery rejection | Fail that screenshot tool, retain audio; no browser image traffic or continuous capture exists. |
| Malformed application event during an established call | Reject the event and display a warning; never execute invalid input. |
| Session startup denied, transport closed/failed, microphone lost, explicit provider session failure | End the unusable call and release resources. |

Tool validation is separate from session event parsing in `realtimeTools.ts`.
Provider error correlation uses the event ID of the specific outbound request;
it does not infer scope from error-message wording. Rejected context insertion
never counts as successful delivery. Model coordinate constraints and endpoint
authorization remain enforced.

Regression tests cover invalid tool arguments followed by corrected calls and
subsequent speech, provider insertion failures, screenshot delivery, lazy native
overlay setup and capture routing. Ellipses beyond the display are clipped by the
renderer. Native drawing errors fail only that tool invocation.

## Voice transport and Board transport

The Board RPC connection and browser-to-provider audio connection are separate
WebRTC transports. A relayed Board does not imply relayed audio. The voice describe
endpoint returns configured STUN servers and the current short-lived TURN lease;
the browser supplies them to its own RTCPeerConnection with policy `all`. Local
setups with no configured ICE servers explicitly return an empty list. Provider
OAuth credentials remain server-side. The media startup timer starts only after
the SDP answer arrives, rather than including candidate gathering and provider
call creation. A timeout reports media and data-channel states, not an approval
requirement. Deployment requires the node runtime plus the portal frontend.
