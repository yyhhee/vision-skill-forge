import { useEffect } from "react";
export const HISTORY_INDEX = "vsfHistoryIndex";
export const ROUTE_EVENT = "vsf:route";
export const HISTORY_LEAVE_EVENT = "vsf:history-leave";
export function navigateLocal(path: string) {
  const index = Number(history.state?.[HISTORY_INDEX] ?? 0);
  history.pushState({ [HISTORY_INDEX]: index + 1 }, "", path);
  window.dispatchEvent(new Event(ROUTE_EVENT));
}
export function useHistoryLeaveGuard(block: (proceed: () => void) => boolean) {
  useEffect(() => {
    const listener = (event: Event) => {
      const proceed = (event as CustomEvent<{ proceed: () => void }>).detail
        .proceed;
      if (block(proceed)) event.preventDefault();
    };
    window.addEventListener(HISTORY_LEAVE_EVENT, listener);
    return () => window.removeEventListener(HISTORY_LEAVE_EVENT, listener);
  }, [block]);
}
