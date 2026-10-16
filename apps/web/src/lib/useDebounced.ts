import { useEffect, useState } from "react";

/**
 * F-023: returns `value` once it has been stable for `delayMs`, so a query
 * keyed on it fires one request after typing stops instead of one per
 * keystroke — and a superseded query string can no longer settle late and
 * overwrite the table with older results.
 */
export function useDebounced<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}
