/**
 * LLM chat replies often omit newlines before markdown lists and numbered sections.
 * Insert breaks so remark-gfm can parse bullets and headings reliably.
 */
export function normalizeChatMarkdown(content: string): string {
  if (!content) return content

  let text = content.replace(/\r\n/g, '\n').trim()

  // Blank line before **N. Section title:** blocks
  text = text.replace(/([.!?:])\s+(\*\*\d+\.)/g, '$1\n\n$2')

  // List items after punctuation (e.g. "thinking: - In-app …")
  text = text.replace(/([.!?:])\s+-\s+/g, '$1\n- ')

  // List items mid-paragraph after a question mark
  text = text.replace(/\?\s+-\s+/g, '?\n- ')

  return text.replace(/\n{3,}/g, '\n\n')
}
