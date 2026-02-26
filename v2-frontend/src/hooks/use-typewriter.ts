import { useRef, useCallback } from "react";
import type { ChatMessage } from "@/lib/chat-api";

interface TypewriterState {
  msgId: number;
  target: string;
  revealed: number;
  done: boolean;
  finalContent: string;
  finalCreatedAt: string;
}

export function useTypewriter(
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
) {
  const typewriterRef = useRef<TypewriterState | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopTypewriter = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    typewriterRef.current = null;
  }, []);

  const startTypewriter = useCallback(
    (msgId: number) => {
      if (timerRef.current) return;

      timerRef.current = setInterval(() => {
        const tw = typewriterRef.current;
        if (!tw || tw.msgId !== msgId) {
          clearInterval(timerRef.current!);
          timerRef.current = null;
          return;
        }

        const nextReveal = Math.min(tw.revealed + 3, tw.target.length);
        tw.revealed = nextReveal;
        const isComplete = tw.done && nextReveal >= tw.target.length;

        setMessages((prev) =>
          prev.map((m) =>
            m.id === msgId
              ? {
                  ...m,
                  content: isComplete
                    ? tw.finalContent
                    : tw.target.slice(0, nextReveal),
                  streaming: !isComplete,
                  created_at: isComplete ? tw.finalCreatedAt : m.created_at,
                }
              : m,
          ),
        );

        if (isComplete) {
          clearInterval(timerRef.current!);
          timerRef.current = null;
          typewriterRef.current = null;
        }
      }, 20);
    },
    [setMessages],
  );

  return { typewriterRef, stopTypewriter, startTypewriter };
}
