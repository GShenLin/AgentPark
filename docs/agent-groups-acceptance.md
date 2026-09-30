# Agent group delivery audit

Audit date: 2026-09-27, final readback after group event249. Requested group
capabilities and the substantial playable game are delivered and verified within
the evidence scopes below. All32 production/review/follow-up tasks are done.
Human pacing and broad device/accessibility certification remain disclosed limits.

## Requested collaboration behavior

| Requirement | Inspected evidence | Current conclusion |
| --- | --- | --- |
| Marquee + G creates a group; selecting the complete group + G dissolves it | `.runtime/group-trial/browser.cjs`, `ui-evidence.json`: actual installed Chrome interactions | Verified on deployed implementation |
| Graph sidebar lists and dissolves groups without deleting agents | Same UI run: list opens board; dissolve leaves all three original nodes | Verified |
| Rectangular group frame and blank-area board opening | Same UI run and `GroupFrames.vue`/`groupGeometry.ts` | Verified |
| Drag agents into/out of a group | Same UI run: QA joins, then leaves; persisted membership checked | Verified |
| Group is a shared task board, not another agent | `src/agent_groups` separate SQLite store; existing nodes execute work; live board events show distinct actors | Verified |
| Plan, task progress and member assignments visible | UI task creation/role edits; live Beaconfall board lists owned in-progress/done work; deployed Chrome plan-conflict test | Verified, including retained drafts and concurrent task changes |
| Composer broadcasts; agents know their group and teammates | UI broadcast persistence, identity-bound context/tools, actual seven-member production traces | Verified |
| Peer and broadcast messages, task creation/claim/update, automatic notices | Domain/API tests and live Producer/World/Narrative/Gameplay handoffs; task dependencies reject early QA start | Verified |
| Existing specialist capabilities remain independent | `test_group_tools_preserve_distinct_member_capabilities`: two registries retain callable distinct tools and provider/skill values; communication retains caller identity | Verified at integration boundary. Live game trial uses one provider and role instructions, not heterogeneous provider execution |
| Real provider-driven collaboration creates useful artifacts | Seven live nodes use GPT_Official / gpt-6-astra; actual game-owned modules, task evidence and independent playthrough | Verified; final independent follow-up and documentation reconciliation complete |

Additional evidence: `.runtime/group-trial/lifecycle-live.json` verifies rename,
delete/undo and cross-graph membership cleanup against the running backend.
Notification restart/recovery and strict identity/visibility checks are documented
in [the dated validation record](agent-groups-validation.md).

## Game artifact and scope

Project: `C:/Project/AgentParkGames/Beaconfall`. README supplies `npm start`,
`launch.ps1`, controls and save/export/import instructions. It uses native browser
modules with no downloaded runtime dependencies or remote assets.

| Requirement | Evidence | Remaining work |
| --- | --- | --- |
| Story, characters and complete ending | Authored journal/dialogue/epilogue modules; both visible endings reached in fresh Chrome full-route runs after the interlock change | Verified, including fresh visible-UI custodian replay; feedback/teaching fixes independently accepted |
| Levels and progression | Five chapters, 15 rooms, six puzzle boards, three learned abilities; legal campaign and hazard-route tests; root full UI routes after interlock change | Preserved in current integrated runtime |
| Actual playable complete game | Both `game-final-commons.json` and `game-final-custodian.json`: 696-command legal UI routes, three real interlock replies, explicit commit, visible ending and exploration reload, no page errors | Full browser campaigns, independent QA and visible-UI review completed; review-found reset-feedback correction independently accepted |
| Substantial content rather than a technical demo | Independent UI-only first play completed five chapters/six boards and eight optional testimonies; authored optional content and two narrative choices | Final-board variation implemented, QA accepted and independently played; stale reset feedback corrected and root-browser verified |
| Playtime evidence | `docs/FIRST_PLAY_REVIEW.md`: 30m07s AI-assisted fresh session, disclosed wrong submission/accidental hint and prior high-level context | Human first-play duration is unmeasured. 45–60min is a design target, not a verified promise or user-specified numeric gate |
| Address actual first-play friction | World/Narrative clue framing, Gameplay completed-conversation guidance and Interface journal/keyboard implementation; updated independent QA26 tests and five browser scripts passed | Existing polish and interlock engineering acceptance complete; manual review found stale reset feedback and an Anchor teaching ambiguity, now corrected and independently accepted |

Root independently exercised the new journal from a fresh Chrome session through
six legal visible-UI steps, without setting engine state or importing a save:
acquire `quay.brief`, read its exact focused/expanded entry, close, reload and read
again. No extra simulation beat and no horizontal overflow at 390px. Evidence:
`.runtime/group-trial/journal-polish.json` and `journal-polish-mobile.png`.
The initial test selected the background HUD duplicate underneath a modal;
correcting the locator to the active modal made the real interaction pass. This
was a test-driver issue, not evidence of a blocked user-facing read action.

Root final campaigns ran at `2026-09-27T11:39:18Z` and `11:39:23Z` through installed Chrome in
fresh contexts, using real keyboard/pointer actions and no imported or injected
game state. The traces are solution-aware legal playthroughs, not blind play or
human timing. Both runs checked pump guidance before/after the Anchor lesson,
each final reply remaining unsolved until explicit commit, visible ending,
Explore Dawn and normal/paused exploration reload. Evidence lives under
`.runtime/group-trial/game-final-{commons,custodian}.json` and matching PNGs;
`game_release_checks.cjs` is the driver. Both records include the same 37 runtime
JS/CSS/HTML file hashes, unchanged before/after the campaigns and on readback.

Root also measured actual authored content from the production bundle:
10 dialogue trees containing 33 nodes/48 choice entries, 26 journal entries
(10 optional), and two epilogues. Deduplicated dialogue/journal/epilogue bodies
contain 8,291 Unicode characters, including 7,242 Han characters. This includes
optional and alternate text; it excludes labels, IDs, code and puzzle/map
instructions. It is neither one-route reading volume nor a human duration
estimate. Evidence: `.runtime/group-trial/game-content-summary.json`.

## Final acceptance and disclosed limits

1. Final interlock implementation is complete as of group events 198–204:
   authored dependency metadata/prose, engine reducer/validation/ViewModel, and
   native reply UI. Root inspected the actual engine/UI modules and Interface's
   `src/ui/interlock-browser-results.json` (28 checks, no page errors, timestamp
   `2026-09-27T10:38:51.102Z`) plus the mobile screenshot. These are owner-run
   scoped checks using public import of a legal 613-command prefix, not root-run
   full-campaign or independent QA evidence. Third acceptance saves arrangement;
   explicit commit and subsequent beacon interaction remain separate.
2. Independent QA completed at event 217 (`2026-09-27T10:56:14Z`): 23 Node
   tests, zero failures/skips; Chrome interlock4 + smoke4 + regressions3 + polish5
   grouped checks passed without page errors. Root inspected the tests, raw log,
   browser JSON and revised QA_REPORT. Both generated routes use three replies,
   explicit commit and no legacy final-board setters; all 27 legacy assignments
   are checked separately. QA handed the legal 613-command checkpoint and
   solution-free public-import instructions to Playtester at event 218.
3. Playtester completed a fresh visible-UI replay through the custodian ending,
   without import or hidden state, at events 225–226. Report:
   `C:/Project/AgentParkGames/Beaconfall/docs/FIRST_PLAY_REVIEW.md`; evidence under
   `tests/first-play/rehearsal/`: 99 batches, 53 screenshots, 22m56.021s AI replay
   with prior knowledge, one observed storm hit and no hints/blocker. This is not
   a blind or human duration claim. Root inspected the mechanics-only driver,
   timing, final visible state and completed-but-uncommitted screenshot.
4. The review found a reproducible P2: clearing rehearsal retains the old third
   reply success feedback despite clearing accepted history (screenshot36).
   Root verified the missing reset event in `transition.js` and the narrower
   clear-feedback list in `main.js`. Event227 requests explicit reset-result
   feedback, unchanged state/save/beat rules, focused QA, and a small Narrative
   clarification that Q protects its own stationary action rather than the next
   move. The engine already behaves this way. Verbose persistence prose is a
   disclosed nonblocking P3; no panel redesign or extra full first-play gate.
   Gameplay and Narrative completed these changes at events240/242. Root actual
   Chrome check `reset-feedback-fixed.json` verifies replacement of the old message,
   retained saved arrangement/stats, identical persisted state on repeated empty
   clear, and distinct full reset. Both final campaigns were rerun after both fixes;
   all 37 runtime hashes match each other and current files. Independent QA task
   e4534e72ebd3484ab3bfe6a932e69924 completed at event247: focused3/full26 Node tests
   passed (zero failures/skips), Chrome followup4/interlock4/smoke4/regressions3/
   polish5 grouped checks all passed without page errors. Root inspected new
   follow-up tests, legal-checkpoint helper, raw26-test log, five browser JSONs and
   QA_REPORT. Reset identity/guards and visible replacement, exact lesson/journal
   plus reload, and actual Q-protection/next-move damage are explicitly covered.
   Producer README/PLAN reconciliation completed at event249. Root inspected both
   final documents: accepted fixes, latest26-test/5-script results, attributed root
   campaigns and human-pacing limits are accurate; no pending implementation gate.
5. Plan compare-and-swap deployment and full-board browser acceptance are now
   complete; see [release evidence](agent-groups-release-20260927.md).
6. Final readback confirms32/32 tasks done, current game service available, both
   current runtime manifests unchanged, and all specified collaboration/game
   requirements evidenced above. Snapshot: `.runtime/group-trial/final-delivery.json`.
   No required implementation or acceptance work remains. Repeated persistence
   prose is a nonblocking polish observation. Human45–60min, blind comprehension,
   all-browser/real-mobile and complete accessibility claims are not made.

## Delivery

- AgentPark local board: `http://127.0.0.1:8788/`; graph `beaconfall-studio` keeps
  the actual seven-member group, tasks and collaboration history.
- Running game: `http://127.0.0.1:52216/`. Source and durable launch instructions:
  `C:/Project/AgentParkGames/Beaconfall/README.md`; `npm start` serves port4173.
- User group instructions: [guide](agent-groups-guide.md).
- Group focused regression/build checks and staged fixes are dated separately in
  [validation](agent-groups-validation.md) and [release](agent-groups-release-20260927.md).
  This is not a claim that every unrelated repository test passes.
