"use client";

import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { cn } from "@/lib/utils";

// ─── Shared markdown component config ───────────────────────

const remarkPlugins = [remarkGfm];
const rehypePlugins = [rehypeSanitize];

const markdownComponents = {
  table: ({ children }: { children?: React.ReactNode }) => (
    <div className="overflow-x-auto my-2 rounded-lg border border-border/50">
      <table className="w-full text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }: { children?: React.ReactNode }) => (
    <thead className="bg-muted/50">{children}</thead>
  ),
  th: ({ children }: { children?: React.ReactNode }) => (
    <th className="text-left px-3 py-1.5 text-xs font-medium text-muted-foreground border-b border-border/50">
      {children}
    </th>
  ),
  td: ({ children }: { children?: React.ReactNode }) => (
    <td className="px-3 py-1.5 text-xs border-b border-border/30">
      {children}
    </td>
  ),
  code: ({ className, children, ...props }: { className?: string; children?: React.ReactNode }) => {
    const isInline = !className;
    if (isInline) {
      return (
        <code className="px-1.5 py-0.5 rounded bg-muted text-xs font-mono" {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className="block bg-muted/50 rounded-lg p-3 text-xs font-mono overflow-x-auto my-2" {...props}>
        {children}
      </code>
    );
  },
  pre: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  p: ({ children }: { children?: React.ReactNode }) => <p className="my-1.5 leading-relaxed">{children}</p>,
  ul: ({ children }: { children?: React.ReactNode }) => <ul className="list-disc pl-5 my-1.5 space-y-0.5">{children}</ul>,
  ol: ({ children }: { children?: React.ReactNode }) => <ol className="list-decimal pl-5 my-1.5 space-y-0.5">{children}</ol>,
  li: ({ children }: { children?: React.ReactNode }) => <li className="text-xs">{children}</li>,
  a: ({ children, href }: { children?: React.ReactNode; href?: string }) => {
    let resolvedHref = href;
    if (href && href.startsWith("/uploads/")) {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
      resolvedHref = `${apiBase}${href}`;
    }
    return (
      <a href={resolvedHref} className="text-primary underline underline-offset-2" target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
  h1: ({ children }: { children?: React.ReactNode }) => <h1 className="text-base font-semibold mt-3 mb-1.5">{children}</h1>,
  h2: ({ children }: { children?: React.ReactNode }) => <h2 className="text-sm font-semibold mt-3 mb-1">{children}</h2>,
  h3: ({ children }: { children?: React.ReactNode }) => <h3 className="text-sm font-medium mt-2 mb-1">{children}</h3>,
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="border-l-2 border-primary/40 pl-3 my-2 text-muted-foreground italic">
      {children}
    </blockquote>
  ),
};

// ─── MemoizedBlock — only re-renders when its specific block content changes ──

const MemoizedBlock = memo(
  function MemoizedBlock({ content }: { content: string }) {
    return (
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
    );
  },
  (prev, next) => prev.content === next.content,
);

// ─── MarkdownContent — splits content into independently-memoized blocks ─────
//
// During streaming, only the last paragraph block changes per token.
// All previous blocks are memoized and skip re-render entirely.
// This reduces per-token render cost from O(N) to O(1).

interface MarkdownContentProps {
  content: string;
  className?: string;
}

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  const blocks = useMemo(() => content.split(/\n\n+/), [content]);

  return (
    <div className={cn("prose prose-sm dark:prose-invert max-w-none", className)}>
      {blocks.map((block, i) => (
        <MemoizedBlock key={i} content={block} />
      ))}
    </div>
  );
}
