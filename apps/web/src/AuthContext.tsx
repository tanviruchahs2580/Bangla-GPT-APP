import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  fetchMe,
  logout,
  setUnauthorizedHandler,
  type MeResponse,
} from "./api";
import { syncOfflineOwner } from "./lib/offlineStore";

interface AuthState {
  me: MeResponse | null;
  loading: boolean;
  /**
   * A token is held but the API could not be reached (F-107). Distinct from
   * "signed out": the session is intact, the server is not, and saying so is
   * the difference between a retry button and a dead end at the login page.
   */
  apiUnreachable: boolean;
  retrySession: () => void;
  setMe: (me: MeResponse | null) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [apiUnreachable, setApiUnreachable] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchMe()
      .then((result) => {
        if (cancelled) return;
        if (result.status === "ok") {
          setMe(result.me);
          setApiUnreachable(false);
          if (result.me.role === "student") {
            // PWA-03: a crash or an undetected logout can leave offline
            // chapter copies owned by a different user on a shared device;
            // the owner marker catches that before the reader opens.
            void syncOfflineOwner(result.me.user_id);
          }
        } else if (result.status === "unreachable") {
          // Keep whatever profile we already have and keep the token: the
          // outage is not the user's fault and must not end their session.
          setApiUnreachable(true);
        } else {
          setMe(null);
          setApiUnreachable(false);
        }
        setLoading(false);
      })
      .catch(() => {
        // A failed session probe leaves the user signed out rather than
        // stuck on the loading screen forever.
        if (!cancelled) setLoading(false);
      });
    setUnauthorizedHandler(() => {
      // Clear this user's stored data (F-036) before bouncing to login — the
      // reload must not race the storage wipe on a shared device. FE-02
      // (B-02 client half): the bounce carries ?next= so the re-login returns
      // to where the session died instead of dumping the user at their role
      // home — a quiz finish or a saved note must survive the hour, not be
      // abandoned by the clock.
      void logout().finally(() => {
        const here = `${window.location.pathname}${window.location.search}`;
        const target = here.startsWith("/login")
          ? "/login"
          : `/login?next=${encodeURIComponent(here)}`;
        window.location.href = target;
      });
    });
    return () => {
      cancelled = true;
      setUnauthorizedHandler(() => {});
    };
  }, [attempt]);

  const retrySession = () => setAttempt((n) => n + 1);

  const signOut = () => {
    // F-036: logout() is awaitable precisely so sign-out cannot navigate away
    // before the storage wipe finishes; the query cache is cleared by the
    // cleanup registered in App.tsx (`setLogoutCleanup`).
    void logout().finally(() => {
      setMe(null);
      setApiUnreachable(false);
      window.location.href = "/login";
    });
  };

  return (
    <AuthContext.Provider
      value={{ me, loading, apiUnreachable, retrySession, setMe, signOut }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export const ROLE_HOME: Record<string, string> = {
  student: "/student",
  teacher: "/teacher",
  parent: "/parent",
  admin: "/admin",
  school_admin: "/school",
};
