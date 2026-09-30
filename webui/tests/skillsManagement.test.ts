import { describe, expect, it } from 'vitest'
import { moveTargets, skillView, type SkillEntry } from '../src/skillsApi'
import { renderSkillDocument } from '../src/components/settings/skillMarkdown'

const entry = (path: string, kind: 'folder' | 'skill', description = ''): SkillEntry => ({
  root_id: 'project', shadowed_by: '', path, parent: path.split('/').slice(0, -1).join('/'), kind, name: path.split('/').slice(-1)[0]!,
  description, version: '', error: '', skill_count: 0, folder_count: 0, used_by: [],
})
const entries = [entry('Game', 'folder'), entry('Game/Design', 'folder'), entry('Game/Design/combat', 'skill', '设计战斗系统'), entry('mail', 'skill', '发送邮件')]

describe('skill organization views', () => {
  it('browses one level at a time and sorts category blocks before skills', () => {
    expect(skillView(entries, '', '').map(e => e.path)).toEqual(['Game', 'mail'])
    expect(skillView(entries, 'Game', '').map(e => e.path)).toEqual(['Game/Design'])
  })
  it('searches name, description and paths across every folder', () => {
    expect(skillView(entries, '', '战斗').map(e => e.path)).toEqual(['Game/Design/combat'])
    expect(skillView(entries, 'Game', 'MAIL').map(e => e.path)).toEqual(['mail'])
    expect(skillView(entries, '', 'design combat').map(e => e.path)).toEqual(['Game/Design/combat'])
  })
  it('never offers the source, descendants or skill bundles as move destinations', () => {
    expect(moveTargets(entries, 'Game')).toEqual([])
    expect(moveTargets(entries, 'mail').map(e => e.path)).toEqual(['Game', 'Game/Design'])
  })
})

describe('skill document preview', () => {
  it('renders the complete body without YAML metadata', () => {
    const html = renderSkillDocument('---\nname: demo\ndescription: Test\n---\n# 完整说明\n\n**内容**')
    expect(html).toContain('<h1>完整说明</h1>')
    expect(html).toContain('<strong>内容</strong>')
    expect(html).not.toContain('description:')
  })
  it('does not execute embedded HTML, javascript links or fetch embedded images', () => {
    const html = renderSkillDocument('<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n![picture](https://example.com/tracker.png)')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('href=')
    expect(html).not.toContain('<img')
    expect(html).toContain('picture')
  })
})
