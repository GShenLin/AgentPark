import { expect, test } from 'vitest'
import { readWorkspaceNodeLink } from '../src/workspaceNodeLink'

test('decodes graph and node IDs without interpreting URL delimiters in their names', () => {
  const url = new URL('http://127.0.0.1:8788/')
  url.searchParams.set('graph', '画布 / A & B')
  url.searchParams.set('node', '节点 + #?中文')
  expect(readWorkspaceNodeLink(url.href)).toEqual({ graphId: '画布 / A & B', nodeId: '节点 + #?中文' })
})
test('ordinary URLs keep the existing startup selection', () => {
  expect(readWorkspaceNodeLink('http://127.0.0.1:8788/')).toBeNull()
})
test.each(['?graph=g', '?node=n', '?graph=&node=n', '?graph=g&node=%20'])('rejects incomplete links %s', query => {
  expect(() => readWorkspaceNodeLink(`http://127.0.0.1:8788/${query}`)).toThrow('节点链接不完整')
})
