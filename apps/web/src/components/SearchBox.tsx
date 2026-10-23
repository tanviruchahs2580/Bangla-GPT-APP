import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { get } from "../api";
import { t } from "../i18n";
import type { SearchResponse } from "../types";

// global search box in the top bar. Debounced GET /search, dropdown
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
  const [active, setActive] = useState(-1);
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

  // Flatten the rendered options once so the keyboard handler, the
  // aria-activedescendant wiring and the click handlers all agree on the
  // same ordering.
  const options: Array<{ id: string; run: () => void }> = [];
  if (showDropdown && data) {
    if (data.ask_action) {
      options.push({
        id: "search-option-ask",
        run: () => {
          setOpen(false);
          void navigate("/student/tutor", { state: { ask: debounced } });
        },
      });
    }
    data.hits.forEach((h, i) => {
      options.push({
        id: `search-option-${i}`,
        run: () => {
          setOpen(false);
          void navigate(h.href);
        },
      });
    });
  }
  const activeId =
    active >= 0 && active < options.length ? options[active].id : undefined;

  return (
    <div className="searchbox" ref={boxRef}>
      <Search size={16} aria-hidden />
      <input
        className="input search-input"
        value={q}
        placeholder={t("searchPlaceholder")}
        aria-label={t("searchPlaceholder")}
        // APG combobox contract. The markup previously announced a listbox
        // with options and then implemented none of the keyboard model:
        // ArrowDown did nothing, every option was aria-selected=false
        // (including the one being activated), and the input never said it
        // had a popup. Focus stays in the input; activedescendant names the
        // highlighted option.
        role="combobox"
        aria-expanded={showDropdown}
        aria-controls="search-listbox"
        aria-autocomplete="list"
        aria-activedescendant={activeId}
        onChange={(e) => {
          setQ(e.target.value);
          setActive(-1);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setOpen(false);
            setActive(-1);
            return;
          }
          if (!showDropdown || options.length === 0) return;
          let next: number | null = null;
          if (e.key === "ArrowDown")
            next = active < 0 ? 0 : (active + 1) % options.length;
          else if (e.key === "ArrowUp")
            next = active < 0 ? options.length - 1 : (active - 1 + options.length) % options.length;
          else if (e.key === "Home") next = 0;
          else if (e.key === "End") next = options.length - 1;
          else if (e.key === "Enter" && active >= 0) {
            e.preventDefault();
            options[active].run();
            return;
          } else return;
          e.preventDefault();
          setActive(next);
        }}
      />
      {showDropdown && (
        <div
          id="search-listbox"
          className="search-dropdown"
          role="listbox"
          aria-label={t("searchPlaceholder")}
        >
          {data.ask_action && (
            <button
              id="search-option-ask"
              type="button"
              role="option"
              aria-selected={active === options.findIndex((o) => o.id === "search-option-ask")}
              className="search-item search-ask"
              onClick={() => {
                setOpen(false);
                void navigate("/student/tutor", { state: { ask: debounced } });
              }}
            >
              <span className="search-kind">{t("searchAskTutor")}</span>
              <span className="search-title">{debounced}</span>
            </button>
          )}
          {data.hits.map((h, i) => (
            <button
              key={`${h.href}-${i}`}
              id={`search-option-${i}`}
              type="button"
              role="option"
              aria-selected={options[active]?.id === `search-option-${i}`}
              className="search-item"
              onClick={() => {
                setOpen(false);
                void navigate(h.href);
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
