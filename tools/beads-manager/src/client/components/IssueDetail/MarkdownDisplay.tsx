/**
 * Simple markdown renderer for displaying formatted text.
 * Converts basic markdown syntax to styled HTML.
 */
interface MarkdownDisplayProps {
  content: string;
  className?: string;
}

export function MarkdownDisplay({ content, className = '' }: MarkdownDisplayProps) {
  if (!content) return null;

  const renderMarkdown = (text: string): string => {
    let html = text
      // Escape HTML
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      // Code blocks (must be before inline code)
      .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="bg-slate-900 rounded p-3 my-2 overflow-x-auto"><code class="text-sm font-mono text-indigo-300">$2</code></pre>')
      // Headers
      .replace(/^### (.+)$/gm, '<h3 class="text-base font-semibold text-slate-200 mt-3 mb-1">$1</h3>')
      .replace(/^## (.+)$/gm, '<h2 class="text-lg font-semibold text-slate-200 mt-4 mb-2">$1</h2>')
      .replace(/^# (.+)$/gm, '<h1 class="text-xl font-bold text-slate-100 mt-4 mb-2">$1</h1>')
      // Bold and italic
      .replace(/\*\*(.+?)\*\*/g, '<strong class="font-bold text-slate-200">$1</strong>')
      .replace(/\*(.+?)\*/g, '<em class="italic">$1</em>')
      .replace(/__(.+?)__/g, '<strong class="font-bold text-slate-200">$1</strong>')
      .replace(/_(.+?)_/g, '<em class="italic">$1</em>')
      // Inline code
      .replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 bg-slate-700 rounded text-sm font-mono text-indigo-300">$1</code>')
      // Links
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" class="text-indigo-400 hover:text-indigo-300 underline" target="_blank" rel="noopener noreferrer">$1</a>')
      // Task lists
      .replace(/^- \[x\] (.+)$/gm, '<div class="flex items-start gap-2 my-1"><span class="text-green-400">✓</span><span class="line-through text-slate-500">$1</span></div>')
      .replace(/^- \[ \] (.+)$/gm, '<div class="flex items-start gap-2 my-1"><span class="text-slate-500">○</span><span>$1</span></div>')
      // Unordered lists
      .replace(/^- (.+)$/gm, '<li class="ml-4 my-0.5">• $1</li>')
      .replace(/^\* (.+)$/gm, '<li class="ml-4 my-0.5">• $1</li>')
      // Ordered lists
      .replace(/^(\d+)\. (.+)$/gm, '<li class="ml-4 my-0.5">$1. $2</li>')
      // Blockquotes
      .replace(/^> (.+)$/gm, '<blockquote class="border-l-2 border-indigo-500 pl-3 text-slate-400 italic my-2">$1</blockquote>')
      // Horizontal rule
      .replace(/^---$/gm, '<hr class="border-slate-600 my-3" />')
      // Paragraphs (double newline)
      .replace(/\n\n/g, '</p><p class="my-2">')
      // Single line breaks
      .replace(/\n/g, '<br />');

    return `<p class="my-1">${html}</p>`;
  };

  return (
    <div
      className={`prose prose-sm prose-invert max-w-none ${className}`}
      dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
    />
  );
}
