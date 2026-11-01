/**
 * Guardian-invite card for the student's Me page.
 *
 * Split out of MePage (F-094 page budget) when the F-IV2-3 fix added the
 * active-code list and the revoke control: the create response used to be
 * the only place a code appeared and its database id never reached the
 * client, so a leaked code could not be revoked from the product.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { KeyRound, Trash2 } from "lucide-react";
import {
  generateInviteCode,
  getLiveInviteCodes,
  revokeInviteCode,
} from "../api";
import { friendlyError } from "../errors";
import { t } from "../i18n";
import { track } from "../lib/analytics";
import { formatServerDateTime } from "../lib/datetime";
import { Button, Card } from "./ui";

export default function ParentInviteCard() {
  const [invite, setInvite] = useState<{
    id: number;
    code: string;
    expires_in_minutes: number;
  } | null>(null);
  const [inviteBusy, setInviteBusy] = useState(false);
  const [inviteNotice, setInviteNotice] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  // Codes issued before this mount are only revocable if their ids are
  // listed back; the created code alone left revocation unreachable after a
  // reload (F-IV2-3).
  const { data: liveInvites, refetch: refetchInvites } = useQuery({
    queryKey: ["my-invites"],
    queryFn: getLiveInviteCodes,
  });

  const createInvite = async () => {
    setInviteBusy(true);
    setInviteError(null);
    setInviteNotice(null);
    try {
      const inv = await generateInviteCode();
      setInvite(inv);
      await refetchInvites();
      track("parent_invite_generated");
    } catch (e) {
      setInviteError(
        friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
    } finally {
      setInviteBusy(false);
    }
  };

  const revokeInvite = async (id: number) => {
    setInviteBusy(true);
    setInviteError(null);
    setInviteNotice(null);
    try {
      await revokeInviteCode(id);
      setInvite((current) => (current?.id === id ? null : current));
      setInviteNotice(t("parentInviteRevoked"));
      await refetchInvites();
      track("parent_invite_revoked");
    } catch (e) {
      setInviteError(
        friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
    } finally {
      setInviteBusy(false);
    }
  };

  return (
    <Card>
      <div className="card-title">{t("parentInviteTitle")}</div>
      <p className="muted text-sm m-0">{t("parentInviteHint")}</p>
      {invite ? (
        <div className="stack">
          <div className="row-flex gap-2">
            <KeyRound size={18} aria-hidden />
            <strong className="invite-code">{invite.code}</strong>
            <button
              type="button"
              className="icon-btn"
              aria-label={`${t("parentInviteRevoke")}: ${invite.code}`}
              disabled={inviteBusy}
              onClick={() => void revokeInvite(invite.id)}
            >
              <Trash2 size={16} aria-hidden />
            </button>
          </div>
          <p className="muted text-sm m-0">
            {t("parentInviteExpires", {
              minutes: invite.expires_in_minutes,
            })}
          </p>
        </div>
      ) : (
        <Button variant="teal" onClick={createInvite} disabled={inviteBusy}>
          {inviteBusy ? (
            <span className="spinner" aria-hidden />
          ) : (
            <KeyRound size={16} aria-hidden />
          )}
          {t("parentInviteGenerate")}
        </Button>
      )}
      {(liveInvites ?? []).some((c) => c.id !== invite?.id) && (
        <div className="stack">
          <p className="muted text-sm m-0">{t("parentInviteActive")}</p>
          <ul className="stack notes-list">
            {(liveInvites ?? [])
              .filter((c) => c.id !== invite?.id)
              .map((c) => (
                <li key={c.id} className="row">
                  <div className="row-main">
                    <div className="row-title">
                      {t("parentInviteExpiresAt", {
                        time: formatServerDateTime(c.expires_at),
                      })}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label={`${t("parentInviteRevoke")}: ${formatServerDateTime(c.expires_at)}`}
                    disabled={inviteBusy}
                    onClick={() => void revokeInvite(c.id)}
                  >
                    <Trash2 size={16} aria-hidden />
                  </button>
                </li>
              ))}
          </ul>
        </div>
      )}
      {inviteNotice && <p className="muted text-sm m-0">{inviteNotice}</p>}
      {inviteError && <p className="error m-0">{inviteError}</p>}
    </Card>
  );
}
