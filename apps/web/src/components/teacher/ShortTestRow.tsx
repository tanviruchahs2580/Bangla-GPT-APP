import { formatNumber, t } from "../../i18n";

/** One short-test list row (teacher CreatePage + Assessments). The count is a
 *  quantity, so it takes the app language's digits (F-113), and both pages
 *  render the same markup from one place. */
export function ShortTestRow({
  test,
}: {
  test: {
    chapter: string;
    subject: string;
    questions: unknown[];
    attempts: unknown[];
  };
}) {
  return (
    <li>
      {test.chapter} · {test.subject} · {formatNumber(test.questions.length)}Q ·{" "}
      {t("stAssigned", { n: test.attempts.length })}
    </li>
  );
}
