import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { get } from "../api";
import { t } from "../i18n";
import type { SearchResponse } from "../types";

// S1.11: global search box in the top bar. Debounced GET /search, dropdown
// results, and an "ask in Tutor" action for question-like queries.
const KIND_LABEL: Record<
  string,
  "searchKindSubject" | "searchKindChapter" | "searchKindQuestion"
> = {
  subject: "searchKindSubject",
  chapter: "searchKindChapter",
  question: "searchKindQuestion",
};

export function SearchBox() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const id = setTimeout(() => setDebounced(q.trim()), 300);
    return () => clearTimeout(id);
  }, [q]);

  useEffect(() => {
    if (debounced.length < 2) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    get<SearchResponse>(`/search?q=${encodeURIComponent(debounced)}`)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch(() => {
        if (!cancelled)
          setData({ query: debounced, ask_action: false, hits: [] });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debounced]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const showDropdown =
    open && debounced.length >= 2 && !loading && data !== null;

  return (
    <div className="searchbox" ref={boxRef}>
      <Search size={16} aria-hidden />
      <input
        className="input search-input"
        value={q}
        placeholder={t("searchPlaceholder")}
        aria-label={t("searchPlaceholder")}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {showDropdown && (
        <div
          className="search-dropdown"
          role="listbox"
          aria-label={t("searchPlaceholder")}
        >
          {data.ask_action && (
            <button
              type="button"
              role="option"
              aria-selected={false}
              className="search-item search-ask"
              onClick={() => {
                setOpen(false);
                navigate("/student/tutor", { state: { ask: debounced } });
              }}
            >
              <span className="search-kind">{t("searchAskTutor")}</span>
              <span className="search-title">{debounced}</span>
            </button>
          )}
          {data.hits.map((h, i) => (
            <button
              key={`${h.href}-${i}`}
              type="button"
              role="option"
              aria-selected={false}
              className="search-item"
              onClick={() => {
                setOpen(false);
                navigate(h.href);
              }}
            >
              <span className="search-kind">
                {t(KIND_LABEL[h.kind] ?? "searchKindChapter")}
              </span>
              <span className="search-title">{h.title}</span>
              {h.subtitle && <span className="search-sub">{h.subtitle}</span>}
            </button>
          ))}
          {data.hits.length === 0 && !data.ask_action && (
            <div className="search-empty">{t("searchNoResults")}</div>
          )}
        </div>
      )}
    </div>
  );
}
