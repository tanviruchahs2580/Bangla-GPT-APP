/** Class levels 1–10, the range the teacher surfaces offer. */
const CLASS_LEVELS = Array.from({ length: 10 }, (_, i) => i + 1);

/**
 * Class-level `<select>` used by the teacher pages.
 *
 * One implementation of the option list: three pages had copy-pasted the
 * same 1–10 markup, which the duplication ratchet flagged
 * (apps/api/quality-baselines/duplication-baseline.json).
 */
export function ClassLevelSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: number;
  onChange: (level: number) => void;
}) {
  return (
    <select
      id={id}
      className="select"
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
    >
      {CLASS_LEVELS.map((n) => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
    </select>
  );
}
