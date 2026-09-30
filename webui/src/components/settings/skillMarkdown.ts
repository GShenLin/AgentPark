import { Marked } from 'marked'

const escape = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
// Installed skill documents are data, including any embedded HTML or image URLs.
const markdown = new Marked({ renderer: {
  html: ({ text }) => escape(text),
  image: ({ text }) => `<span>${escape(text)}</span>`,
  link({ href, tokens }) {
    const text = this.parser.parseInline(tokens)
    return /^https?:\/\//i.test(href)
      ? `<a href="${escape(href)}" target="_blank" rel="noopener noreferrer">${text}</a>` : text
  },
} })

export function renderSkillDocument(content: string): string {
  const body = content.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, '')
  return markdown.parse(body, { async: false })
}
