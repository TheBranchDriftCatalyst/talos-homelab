import { useCallback, useState, useRef, useEffect } from 'react';

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  minHeight?: number;
}

/**
 * Simple markdown editor with live preview.
 * Shows raw markdown while editing, renders preview when blurred.
 *
 * TODO: Integrate Milkdown for true WYSIWYG experience.
 * For now, using a split view that auto-switches.
 */
export function MarkdownEditor({
  value,
  onChange,
  placeholder = 'Write markdown...',
  minHeight = 100,
}: MarkdownEditorProps) {
  const [isEditing, setIsEditing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current && isEditing) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.max(textareaRef.current.scrollHeight, minHeight)}px`;
    }
  }, [value, isEditing, minHeight]);

  const handleFocus = useCallback(() => {
    setIsEditing(true);
  }, []);

  const handleBlur = useCallback(() => {
    setIsEditing(false);
  }, []);

  // Simple markdown to HTML conversion (basic)
  const renderMarkdown = (text: string): string => {
    if (!text) return '';

    let html = text
      // Escape HTML
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      // Headers
      .replace(/^### (.+)$/gm, '<h3 class="text-base font-semibold text-slate-200 mt-3 mb-1">$1</h3>')
      .replace(/^## (.+)$/gm, '<h2 class="text-lg font-semibold text-slate-200 mt-4 mb-2">$1</h2>')
      .replace(/^# (.+)$/gm, '<h1 class="text-xl font-bold text-slate-100 mt-4 mb-2">$1</h1>')
      // Bold and italic
      .replace(/\*\*(.+?)\*\*/g, '<strong class="font-bold text-slate-200">$1</strong>')
      .replace(/\*(.+?)\*/g, '<em class="italic">$1</em>')
      .replace(/__(.+?)__/g, '<strong class="font-bold text-slate-200">$1</strong>')
      .replace(/_(.+?)_/g, '<em class="italic">$1</em>')
      // Code
      .replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 bg-slate-700 rounded text-sm font-mono text-indigo-300">$1</code>')
      // Links
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" class="text-indigo-400 hover:text-indigo-300 underline" target="_blank">$1</a>')
      // Task lists
      .replace(/^- \[x\] (.+)$/gm, '<div class="flex items-start gap-2"><span class="text-green-400">✓</span><span class="line-through text-slate-500">$1</span></div>')
      .replace(/^- \[ \] (.+)$/gm, '<div class="flex items-start gap-2"><span class="text-slate-500">○</span><span>$1</span></div>')
      // Unordered lists
      .replace(/^- (.+)$/gm, '<li class="ml-4">• $1</li>')
      .replace(/^\* (.+)$/gm, '<li class="ml-4">• $1</li>')
      // Ordered lists
      .replace(/^(\d+)\. (.+)$/gm, '<li class="ml-4">$1. $2</li>')
      // Blockquotes
      .replace(/^> (.+)$/gm, '<blockquote class="border-l-2 border-indigo-500 pl-3 text-slate-400 italic">$1</blockquote>')
      // Horizontal rule
      .replace(/^---$/gm, '<hr class="border-slate-600 my-3" />')
      // Line breaks
      .replace(/\n\n/g, '</p><p class="my-2">')
      .replace(/\n/g, '<br />');

    return `<p class="my-2">${html}</p>`;
  };

  if (isEditing) {
    return (
      <div className="relative">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={handleBlur}
          placeholder={placeholder}
          className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none font-mono"
          style={{ minHeight }}
          autoFocus
        />
        <div className="absolute top-2 right-2 text-xs text-slate-500">
          Markdown
        </div>
      </div>
    );
  }

  return (
    <div
      onClick={handleFocus}
      className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-slate-300 cursor-text hover:border-slate-500 transition-colors"
      style={{ minHeight }}
    >
      {value ? (
        <div
          className="prose prose-sm prose-invert max-w-none"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(value) }}
        />
      ) : (
        <span className="text-slate-500">{placeholder}</span>
      )}
    </div>
  );
}
