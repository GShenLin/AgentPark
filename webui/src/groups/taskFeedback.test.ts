import { describe, expect, it } from 'vitest'
import { taskDelivery, taskFeedback } from './taskFeedback'
import type { GroupDelivery, GroupEvent, GroupTask } from './groupApi'

const task: GroupTask = { id: 'task', title: 'Question', description: '', status: 'todo', owner_id: 'Animation',
  dependencies: [], evidence: '', revision: 2, created_at: 'now', updated_at: 'now' }
const delivery: GroupDelivery = { event_seq: 3, node_id: 'Animation', state: 'pending', attempts: 0, last_error: null }
const event: GroupEvent = { seq: 3, group_id: 'team', kind: 'task_updated', actor_id: null,
  payload: { action_tasks: { Animation: ['task'] } }, created_at: 'now' }

describe('task save feedback', () => {
  it('matches the current task owner and newest actual notification, not unrelated progress', () => {
    expect(taskDelivery(task, [event], [delivery, { ...delivery, node_id: 'UI' }])).toEqual(delivery)
    expect(taskDelivery({ ...task, owner_id: 'UI' }, [event], [delivery])).toBeUndefined()
    expect(taskDelivery(task, [event, { ...event, seq: 4, payload: { action_tasks: {} } }],
      [delivery, { ...delivery, event_seq: 4 }])).toEqual(delivery)
  })
  it('shows queued, paused and actually started states without waiting for the model to claim the task', () => {
    expect(taskFeedback(task, [task], delivery)).toContain('已加入 Animation 的队列')
    expect(taskFeedback(task, [task], delivery, 'stop')).toContain('暂停中')
    expect(taskFeedback(task, [task], delivery, 'working')).toContain('等待当前工作结束')
    expect(taskFeedback(task, [task], { ...delivery, started_at: 'now' })).toBe('Animation 正在处理这条任务')
  })
  it('shows dependencies, missing owner, failures and completion distinctly', () => {
    expect(taskFeedback({ ...task, dependencies: ['first'] }, [task])).toContain('等待 1 个前置任务')
    expect(taskFeedback({ ...task, owner_id: null }, [task])).toContain('尚未指定负责人')
    expect(taskFeedback(task, [task], { ...delivery, last_error: 'queue failure' })).toContain('queue failure')
    expect(taskFeedback({ ...task, status: 'done' }, [task], delivery)).toContain('任务已完成')
    expect(taskFeedback(task, [task], { ...delivery, state: 'delivered' })).toContain('任务仍为待处理')
  })
})
