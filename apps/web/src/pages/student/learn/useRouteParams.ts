/** Route params for the reader route: /student/learn/{subject}/{chapter}. */
export function useRouteParams(): {
  subject: string | null;
  chapter: string | null;
  searchParams: URLSearchParams;
} {
  const parts = window.location.pathname.split("/").filter(Boolean);
  // /student/learn/{subject}/{chapter}
  const idx = parts.indexOf("learn");
  const subject = idx >= 0 ? (parts[idx + 1] ?? null) : null;
  const chapter = idx >= 0 ? (parts[idx + 2] ?? null) : null;
  return {
    subject,
    chapter: chapter ? decodeURIComponent(chapter) : null,
    searchParams: new URLSearchParams(window.location.search),
  };
}
