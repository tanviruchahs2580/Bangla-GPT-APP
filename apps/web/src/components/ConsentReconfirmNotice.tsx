import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../api";
import { friendlyError } from "../errors";
import { t } from "../i18n";
import { cn } from "../lib/cn";
import { invalidateStudyCaches } from "../lib/invalidate";
import { toast } from "../lib/toast";
import type { ConsentStatusOut } from "../types";
import { Button } from "./ui";

/**
 * FE-FIX-019: the surface for the consent re-confirmation gate.
 *
 * BE-FIX-004 made `students.consent_version != CONSENT_VERSION` refuse tutor
 * generation and the student's durable writes with a coded 403 whose message
 * names POST /students/{id}/consent/reconfirm as the way out. Before this
 * component no first-party client called either consent read, so the coded
 * refusal rendered as the generic sentence and the way out did not exist in
 * the product at all — a CSV-imported class could never submit a quiz again.
 *
 * The notice is visible in two states, and both are honest:
 *  - the server's own flag (`needs_reconfirm` from GET /students/{id}/consent)
 *    so a student sees the requirement before the blocked action; and
 *  - `blocked`, set by the surface when it caught the gate's 403 — the refusal
 *    is authoritative even while the read is in flight or failed.
 * `onReconfirmed` lets the caller drop its own block and retry the action
 * immediately; no reload is involved.
 */
export function ConsentReconfirmNotice({
  studentId,
  blocked = false,
  onReconfirmed,
  className,
}: {
  studentId: number | null | undefined;
  /** The surface caught the gate's 403 (consent_reconfirmation_required). */
  blocked?: boolean;
  /** The gate is cleared: the caller forgets its block and the retry works. */
  onReconfirmed?: () => void;
  className?: string;
}) {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["consent-status", studentId],
    queryFn: () => {
      if (studentId == null)
        throw new Error("consent notice rendered without a student id");
      return get<ConsentStatusOut>(`/students/${studentId}/consent`);
    },
    enabled: studentId != null,
  });
  const mutation = useMutation({
    mutationFn: () => {
      if (studentId == null)
        throw new Error("consent notice rendered without a student id");
      // The body is the API's contract (ConsentReconfirmIn): an explicit
      // acceptance, never a bare "clear the flag".
      return post<ConsentStatusOut>(
        `/students/${studentId}/consent/reconfirm`,
        { accepted: true },
      );
    },
    onSuccess: () => {
      // The student's next tap is the gated action itself, so the consent read
      // must stop saying `needs_reconfirm`, and the study caches (progress,
      // dashboard, revision queue) must stop serving data fetched while the
      // gate was up — all without a reload.
      void queryClient.invalidateQueries({
        queryKey: ["consent-status", studentId],
      });
      invalidateStudyCaches(queryClient);
      toast(t("consentReconfirmed"));
      onReconfirmed?.();
    },
  });
  // FE-FIX-012 pattern: state lands after a render, so two confirm taps in one
  // tick (a double-tap, or Enter plus a click) would both POST and refresh the
  // evidence trail twice. A ref is synchronous.
  const confirmRef = useRef(false);

  // `blocked` deliberately wins over a read that says consent is current: the
  // 403 is fresher than a read issued at page load, and a version bump between
  // the two is exactly the case this notice exists for. The student still sees
  // the refusal explained instead of a notice that flaps away under them.
  const needsReconfirm = status.data?.needs_reconfirm === true;
  if (!needsReconfirm && !blocked) return null;

  const confirm = () => {
    if (confirmRef.current || studentId == null) return;
    confirmRef.current = true;
    mutation.mutate(undefined, {
      onSettled: () => {
        confirmRef.current = false;
      },
    });
  };

  return (
    <div
      className={cn("warn-strip", className)}
      role="alert"
      data-testid="consent-reconfirm-notice"
    >
      <p>{t("consentReconfirmTitle")}</p>
      {/* A plain block, not another <p>: .warn-strip p is the bold heading, and
          the body must read as an explanation, not as a second shout. */}
      <div>{t("consentReconfirmBody")}</div>
      <div className="row-flex">
        <Button
          variant="primary"
          size="sm"
          loading={mutation.isPending}
          disabled={mutation.isPending}
          onClick={confirm}
        >
          {t("consentReconfirmAction")}
        </Button>
      </div>
      {mutation.isError && (
        // No role="alert" of its own: this text changes inside the strip's own
        // alert region, and a nested alert double-announces on some readers.
        <div className="error">
          {friendlyError((mutation.error as { rawDetail?: unknown }).rawDetail)
            ?.text ?? t("errorGeneric")}
        </div>
      )}
    </div>
  );
}
