import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// E2 (unified loading + empty states), checked statically for the same
// reason as e1InteractionGuard and mobileSurfaceGuard: the defects this
// wave fixes are structural, not behavioural — a bare `{t("loading")}`
// paragraph where the surface's own shape belongs (cards, tables, stats),
// and hand-rolled empty states that drift apart page by page. Each rule
// below guards one of those fixes.
const ROOT = resolve(process.cwd());
const uiTsx = readFileSync(resolve(ROOT, "src/components/ui.tsx"), "utf8");

/**
 * The seven surfaces from the E2 audit, plus SchoolSections — the school
 * dashboard's section loader lives there (SchoolDashboard renders it
 directly below its own), so that surface is not clean until both are.
 */
const SURFACES = [
  "src/pages/ParentDashboard.tsx",
  "src/pages/SchoolDashboard.tsx",
  "src/pages/student/MePage.tsx",
  "src/pages/student/quiz/AssignedPanel.tsx",
  "src/pages/student/quiz/RevisionPanel.tsx",
  "src/pages/teacher/AnalyticsPage.tsx",
  "src/pages/StatusPage.tsx",
  "src/components/school/SchoolSections.tsx",
];

function read(path: string): string {
  return readFileSync(resolve(ROOT, path), "utf8");
}

/** Every .ts/.tsx file under a directory, recursively. */
function tsFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...tsFiles(full));
    else if (/\.(ts|tsx)$/.test(name)) out.push(full);
  }
  return out;
}

describe("E2: no bare loading text in the audited surfaces", () => {
  it('none of the surfaces renders {t("loading")} anymore', () => {
    const offenders = SURFACES.filter((p) =>
      read(p).includes('{t("loading")}'),
    );
    expect(
      offenders,
      `bare loading text still present in:\n${offenders.join("\n")}`,
    ).toEqual([]);
  });

  it("every surface loads through the shared Skeleton primitive", () => {
    for (const path of SURFACES) {
      const src = read(path);
      expect(src, `${path} renders <Skeleton`).toContain("<Skeleton");
      // Imported from the shared primitives module — the relative depth
      // differs per directory (SchoolSections sits beside ui.tsx), the
      // module does not.
      expect(
        src,
        `${path} imports Skeleton from the shared primitives`,
      ).toMatch(
        /import\s*\{[^}]*\bSkeleton\b[^}]*\}\s*from\s*"[./]*(?:components\/)?ui"/,
      );
    }
  });

  it("the Skeleton aria-hidden contract is intact in ui.tsx", () => {
    expect(uiTsx).toMatch(/aria-hidden\s+className=\{cn\("skeleton"/);
  });
});

describe("E2: the EmptyState primitive is shared, not re-rolled", () => {
  it("EmptyState is exported from ui.tsx", () => {
    expect(uiTsx).toMatch(/export function EmptyState\(/);
    // The icon is decorative — the title carries the meaning (the same
    // contract the .empty-mark pattern carries).
    expect(uiTsx).toMatch(/className="empty-icon" aria-hidden/);
  });

  it("at least four page files adopt EmptyState", () => {
    const adopters = tsFiles(resolve(ROOT, "src", "pages")).filter((file) =>
      readFileSync(file, "utf8").includes("EmptyState"),
    );
    expect(
      adopters.length,
      `EmptyState adopters:\n${adopters.join("\n")}`,
    ).toBeGreaterThanOrEqual(4);
  });
});
