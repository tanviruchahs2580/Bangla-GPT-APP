import { ClipboardList } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  LoadError,
  Skeleton,
  Spinner,
} from "../../../components/ui";
import { t, tSubject } from "../../../i18n";
import { formatServerDateTime } from "../../../lib/datetime";
import type { AssignmentMine, ShortTestMine } from "../../../types";

/** F-094 split: the "assigned by teacher" tab body, extracted from QuizPage. */

export type AssignedEntry =
  | { kind: "shorttest"; item: ShortTestMine }
  | { kind: "bulk"; item: AssignmentMine };

export function AssignedPanel({
  assigned,
  isStudent,
  shortTestPending,
  assignmentsPending,
  shortTestFailed,
  assignmentsFailed,
  onRetry,
  onOpenShortTest,
  onOpenAssigned,
}: {
  assigned: AssignedEntry[];
  isStudent: boolean;
  shortTestPending: boolean;
  assignmentsPending: boolean;
  shortTestFailed: boolean;
  assignmentsFailed: boolean;
  onRetry: () => void;
  onOpenShortTest: (st: ShortTestMine) => void;
  onOpenAssigned: (a: AssignmentMine) => void;
}) {
  return (
    <div className="stack">
      {/* A failed fetch used to render "no work assigned yet", which reads
          as a fact about the student's homework rather than a failed
          request -- so they would skip work that actually exists. */}
      {shortTestFailed || assignmentsFailed ? (
        <Card>
          <LoadError onRetry={onRetry} />
        </Card>
      ) : isStudent &&
        (shortTestPending || assignmentsPending) &&
        assigned.length === 0 ? (
        // isStudent guards this: react-query reports isPending while a query
        // is disabled too, so without it a teacher opening this tab would
        // wait on a "loading" that never resolves.
        // E2: the list's own shape while it loads — card rows — with the
        // loading state still announced (Spinner carries role="status").
        <Card>
          <div className="stack">
            <Spinner />
            <Skeleton variant="row" />
            <Skeleton variant="row" />
          </div>
        </Card>
      ) : (
        assigned.length === 0 && (
          // E2: the shared empty state instead of a lone muted line.
          <Card>
            <EmptyState
              size="sm"
              icon={ClipboardList}
              title={t("assignedEmpty")}
            />
          </Card>
        )
      )}
      {assigned.map(({ kind, item }) => {
        if (kind === "shorttest") {
          const st = item;
          return (
            <Card key={`st-${st.id}`} className="row quiz-review-row">
              <div className="row-main">
                <div className="row-title">
                  <Badge tone="teal">{t("assignedShortTest")}</Badge>{" "}
                  {st.chapter}
                </div>
                <div className="row-sub">
                  {tSubject(st.subject)} ·{" "}
                  {t("stMinutes", { n: st.duration_min })}
                  {st.expired && <Badge tone="warn"> {t("stExpired")}</Badge>}
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  className="section-gap-top"
                  disabled={st.attempt_id === null || st.expired}
                  onClick={() => onOpenShortTest(st)}
                >
                  {t("startQuiz")}
                </Button>
              </div>
            </Card>
          );
        }
        const a = item;
        return (
          <Card key={`ba-${a.id}`} className="row quiz-review-row">
            <div className="row-main">
              <div className="row-title">
                <Badge>{t("assignedBulk")}</Badge> {a.chapter}
              </div>
              <div className="row-sub">
                {tSubject(a.subject)} · {t("baDue")}:{" "}
                {formatServerDateTime(a.due_at)}
                {a.done ? (
                  <Badge tone="ok"> {t("baDone")}</Badge>
                ) : a.overdue ? (
                  <Badge tone="warn"> {t("baOverdue")}</Badge>
                ) : null}
              </div>
              <Button
                variant="primary"
                size="sm"
                className="section-gap-top"
                disabled={a.done}
                onClick={() => onOpenAssigned(a)}
              >
                {t("startQuiz")}
              </Button>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
