import type { GroupDelivery, GroupEvent, GroupTask } from './groupApi'

export function taskDelivery(task: GroupTask, events: GroupEvent[], deliveries: GroupDelivery[]) {
  if (!task.owner_id) return undefined
  const eventIds = new Set(events.filter(event => {
    if (event.kind !== 'task_created' && event.kind !== 'task_updated') return false
    const actions = event.payload.action_tasks as Record<string, string[]> | undefined
    return actions?.[task.owner_id!]?.includes(task.id)
  }).map(event => event.seq))
  return deliveries.filter(item => item.node_id === task.owner_id && eventIds.has(item.event_seq))
    .sort((a, b) => b.event_seq - a.event_seq)[0]
}

export function taskFeedback(task: GroupTask, tasks: GroupTask[], delivery?: GroupDelivery, ownerState?: string) {
  if (!task.owner_id) return '已保存，尚未指定负责人'
  if (delivery?.last_error) return `${task.owner_id} 处理通知失败：${delivery.last_error}`
  if (task.status === 'done') return '任务已完成，查看完成证据或组内答复'
  const waiting = task.dependencies.filter(id => tasks.find(item => item.id === id)?.status !== 'done')
  if (waiting.length) return `等待 ${waiting.length} 个前置任务，完成后自动交给 ${task.owner_id}`
  if (delivery?.state === 'pending') {
    if (delivery.started_at) return `${task.owner_id} 正在处理这条任务`
    if (ownerState === 'stop') return `已加入 ${task.owner_id} 的队列，成员暂停中，恢复后处理`
    return ownerState === 'working' ? `已加入 ${task.owner_id} 的队列，等待当前工作结束`
      : `已加入 ${task.owner_id} 的队列，等待开始`
  }
  if (delivery?.state === 'cancelled') return '此前通知已失效；请查看当前负责人和任务状态'
  if (task.status === 'in_progress') return `${task.owner_id} 已将任务标为进行中`
  if (task.status === 'blocked') return '任务受阻，查看完成证据中的说明'
  if (delivery?.state === 'delivered') return '本轮处理已结束，任务仍为待处理；查看组内答复'
  return '任务已保存；投递状态会随组内动态更新'
}
