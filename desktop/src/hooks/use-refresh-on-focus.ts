import { useEffect, useRef } from "react";

const DEFAULT_DELAY = 1000;

export function useRefreshOnFocus(
  refetch: () => void | Promise<void>,
  delayMs = DEFAULT_DELAY,
) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refetchRef = useRef(refetch);

  refetchRef.current = refetch;

  useEffect(() => {
    if (typeof window === "undefined") return;

    const clearTimer = () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const schedule = () => {
      clearTimer();
      timerRef.current = setTimeout(async () => {
        timerRef.current = null;
        try {
          await refetchRef.current();
        } catch {
          // swallow errors from background refetches
        }
      }, delayMs);
    };

    const onFocus = () => schedule();
    const onVisibilityChange = () => {
      if (!document.hidden) schedule();
    };

    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      clearTimer();
    };
  }, [delayMs]);
}
