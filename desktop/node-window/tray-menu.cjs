function validateSnapshot(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.recent) || !Array.isArray(snapshot.working)) throw new Error('Invalid tray snapshot.')
  for (const node of [...snapshot.recent, ...snapshot.working]) {
    if (!node || !['graph_id', 'node_id', 'name'].every(key => typeof node[key] === 'string' && node[key].length)
        || !['idle', 'working', 'stop'].includes(node.state)
        || !(node.saved_at_ns === null || (Number.isFinite(node.saved_at_ns) && node.saved_at_ns > 0))) {
      throw new Error('Invalid tray node.')
    }
  }
  return snapshot
}

// Electron treats '&' as a mnemonic marker in native menus.
const label = value => value.replaceAll('&', '&&').replace(/[\r\n\t]/g, ' ')

function trayMenu(snapshot, actions) {
  validateSnapshot(snapshot)
  const section = (name, nodes, empty) => [
    { label: `${name} (${nodes.length})`, enabled: false },
    ...(nodes.length ? nodes.map(node => ({
      label: `  ${label(node.name)}  ·  ${label(node.graph_id)}`,
      click: () => actions.openNode(node),
    })) : [{ label: `  ${empty}`, enabled: false }]),
    { type: 'separator' },
  ]
  return [
    { label: '打开 AgentPark', click: actions.openApp },
    { label: 'NewNode · 创建节点…', click: actions.newNode },
    { type: 'separator' },
    ...section('Working', snapshot.working, '暂无正在工作的节点'),
    ...section('Recent', snapshot.recent, '暂无最近保存的会话'),
    { label: '显示 / 隐藏控制台', click: actions.console },
    { label: '重启 AgentPark', click: actions.restart },
    { label: '退出 AgentPark', click: actions.exit },
  ]
}

module.exports = { trayMenu, validateSnapshot }
