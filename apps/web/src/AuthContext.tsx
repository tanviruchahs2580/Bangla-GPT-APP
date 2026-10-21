import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  fetchMe,
  getToken,
  logout,
  setUnauthorizedHandler,
  type MeResponse,
} from "./api";

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
  // AUD-G-15: with no stored token there is no session to verify — fetchMe()
  // answers "unauthenticated" without a request — so an anonymous visitor's
  // first render is the real public page, which is the state the prerendered
  // HTML hydrated against. Starting in `loading` made the first commit a
  // skeleton that the real page then replaced (the pending-shell flash).
  const [loading, setLoading] = useState(() => getToken() !== null);
  const [apiUnreachable, setApiUnreachable] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Re-entering the pending state is only meaningful when there is a token
    // to probe (a retry after an outage); `setLoading(false)` is a no-op on
    // the anonymous path, so it cannot reintroduce the flash.
    setLoading(getToken() !== null);
    fetchMe()
      .then((result) => {
        if (cancelled) return;
        if (result.status === "ok") {
          setMe(result.me);
          setApiUnreachable(false);
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
      // reload must not race the storage wipe on a shared device.
      void logout().finally(() => {
        window.location.href = "/login";
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
    // cleanup registered in main.tsx.
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
