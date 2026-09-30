# Task save and group reply feedback

## Observed incident, 2026-09-28

The user assigned Animation the task `3526c88a6b344346962c1f109bb36ab1`
(“动画和角色的替换是否已经完成？”) in the BBQ team.
Persisted event 163 assigned it at 17:17:52.772 local time. Its delivery started
at 17:17:54.283881, with one attempt and no error. Animation marked it in
progress in event 164 and done in event 165, then persisted its final node
answer at 17:19:00.695420. The answer said the actual replacement was incomplete.
This was a visibility failure, not a failure to dispatch the task.

The task form had no explicit queue feedback. The delivery completion path
published final answers for user message events only, omitting user task events.
The original node answer was restored once as group reply event 182, linking
request sequence 163, the task ID, original completion time and trace. It has
zero recipients and did not rerun the agent.

## Changes

- Task rows and save results derive feedback from actual task dependencies,
  delivery records and member state: unassigned, waiting for dependencies,
  queued, paused, processing, completed, or failed.
- Save feedback uses the returned revision until refreshed group data catches up.
- User task creation/update deliveries publish the final answer into the group
  exactly once, carrying request sequences and task IDs. Replies do not notify peers.
- A title change is actionable like a description change. An unchanged save
  produces no event or repeated execution.
- Ordinary peer progress and failed executions are not published as successful
  user task answers.

## Verification

- 44 focused routing, delivery and API tests passed; 3 feedback tests passed.
- Frontend type check and production build passed.
- Actual Chrome UI: create a task, assign TargetA, save. The UI displayed
  “已加入 TargetA 的队列，成员暂停中，恢复后处理”. Exactly one delivery targeted
  TargetA; TargetB received none. Saving again unchanged created no extra event.
  The paused test graph was deleted through the application API. No page errors.
- Public cloud mobile Chrome: the original recovered answer and “任务答复” label
  rendered in the real BBQ group. No messages were sent by this check.
- Local and cloud frontend artifacts: `index-DHNJTtn7.js`, `index-Du8I4koQ.css`.
  Cloud deployment verified 67 file hashes and retained backup
  `/opt/agentpark-coordinator/backups/webui-20260928T092740Z`.

Runtime evidence is in `.runtime/task-save-tests.xml`,
`.runtime/task-save-ui-result.json`, `.runtime/task-save-ui.png`,
`.runtime/task-save-cloud.png` and `.runtime/task-save-original-answer.json`.
Backend deployment must occur at a safe boundary; productive BBQ agent work
was still running when frontend verification completed.
