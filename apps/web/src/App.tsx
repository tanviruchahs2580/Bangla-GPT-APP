/**
 * Application shell: routing table, auth gates, and the language re-render.
 *
 * Split out of ``main.tsx`` so it is testable — a module that calls
 * ``createRoot`` at import cannot be imported by a test. ``main.tsx`` keeps
 * only the bootstrap: providers, the last-resort error boundary, and
 * service-worker registration.
 */

import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { QueryClient } from "@tanstack/react-query";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { getToken, setLogoutCleanup } from "./api";
import { ROLE_HOME, useAuth } from "./AuthContext";
import { AppShell } from "./AppShell";
import { Skeleton } from "./components/ui";
import { RouteErrorBoundary } from "./components/AppErrorBoundary";
import { PublicLanguageToggle } from "./components/PublicLanguageToggle";
import { onLangChange, t } from "./i18n";

const LoginPage = lazy(() => import("./pages/LoginPage"));
const WelcomePage = lazy(() => import("./pages/WelcomePage"));
const RegisterPage = lazy(() => import("./pages/RegisterPage"));
const ForgotResetPage = lazy(() => import("./pages/ForgotResetPage"));
const LegalPage = lazy(() => import("./pages/LegalPage"));
const HomePage = lazy(() => import("./pages/student/HomePage"));
const AITutorPage = lazy(() => import("./pages/student/AITutorPage"));
const QuizPage = lazy(() => import("./pages/student/QuizPage"));
const MePage = lazy(() => import("./pages/student/MePage"));
const LearnPage = lazy(() =>
  import("./pages/student/LearnPage").then((m) => ({ default: m.LearnPage })),
);
const LearnChapterPage = lazy(() =>
  import("./pages/student/LearnPage").then((m) => ({
    default: m.LearnChapterPage,
  })),
);
const TeacherHomePage = lazy(() =>
  import("./pages/teacher/TeacherHomePage").then((m) => ({
    default: m.default,
  })),
);
const CreatePage = lazy(() => import("./pages/teacher/CreatePage"));
const ClassesPage = lazy(() => import("./pages/teacher/ClassesPage"));
const AssessmentsPage = lazy(() => import("./pages/teacher/AssessmentsPage"));
const AnalyticsPage = lazy(() =>
  import("./pages/teacher/AnalyticsPage").then((m) => ({
    default: m.default,
  })),
);
const TeacherProfilePage = lazy(
  () => import("./pages/teacher/TeacherProfilePage"),
);
const ParentDashboard = lazy(() => import("./pages/ParentDashboard"));
const AdminDashboard = lazy(() => import("./pages/AdminDashboard"));
const SchoolDashboard = lazy(() => import("./pages/SchoolDashboard"));
const StatusPage = lazy(() => import("./pages/StatusPage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

// F-036: cached query data is user data. logout() awaits this so sign-out
// cannot hand the next user on a shared device the previous one's dashboards.
setLogoutCleanup(() => queryClient.clear());

function RequireAuth({
  role,
  children,
}: {
  role?: string;
  children: React.ReactNode;
}) {
  const { me, loading, apiUnreachable, retrySession } = useAuth();
  if (!getToken()) return <Navigate to="/login" replace />;
  if (loading)
    return (
      <main className="container" aria-live="polite">
        <p className="muted">{t("loading")}</p>
        <div className="stack">
          <Skeleton w="60%" />
          <Skeleton w="40%" />
        </div>
      </main>
    );
  // F-107: the server is down, not the session. Say so, keep the token, and
  // offer a retry. Redirecting to /login here is what made a total outage
  // look to a child like their account had been closed.
  if (apiUnreachable) return <ApiUnreachable onRetry={retrySession} />;
  // Token present but the profile was genuinely refused (401/403): the
  // session really is over, so send them to log in.
  if (me === null) return <Navigate to="/login" replace />;
  if (role && me.role !== role)
    return <Navigate to={ROLE_HOME[me.role] ?? "/login"} replace />;
  // F-001: the page renders inside its own boundary, so a page-level render
  // error keeps the nav/sidebar alive and clears when the route changes.
  return (
    <AppShell>
      <RouteErrorBoundary>{children}</RouteErrorBoundary>
    </AppShell>
  );
}

/**
 * F-107 / F-099: the one screen that says what is actually wrong. Before
 * this, a hung or dead backend produced either a silent redirect to /login
 * or, worse, a dashboard full of confident zeros.
 */
function ApiUnreachable({ onRetry }: { onRetry: () => void }) {
  // role="alert" (not aria-live on a container that mounts WITH its content)
  // and focus moved onto the heading: live regions announce CHANGES, so the
  // one screen that says what is wrong could be completely silent for a
  // screen-reader user.
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);
  return (
    <main className="container">
      <div className="card stack" role="alert">
        <h1 ref={headingRef} tabIndex={-1}>
          {t("apiUnreachableTitle")}
        </h1>
        <p className="muted">{t("apiUnreachableBody")}</p>
        <div className="stack">
          <button type="button" className="btn" onClick={onRetry}>
            {t("retry")}
          </button>
        </div>
      </div>
    </main>
  );
}

function Loading() {
  return (
    <main className="container" aria-live="polite">
      <p className="muted">{t("loading")}</p>
      <div className="stack">
        <Skeleton w="70%" />
        <Skeleton w="55%" />
        <Skeleton w="80%" />
      </div>
    </main>
  );
}

function RoutesSwitch() {
  const { me, loading } = useAuth();
  const home = me ? (ROLE_HOME[me.role] ?? "/login") : "/welcome";
  if (loading) return <Loading />;

  return (
    <>
      {/* I18N-12: an anonymous visitor sees these pages without AppShell, so
          the language switch has to be rendered here or not at all. */}
      {!me && <PublicLanguageToggle />}
      <Routes>
        <Route path="/" element={<Navigate to={home} replace />} />
        <Route
          path="/welcome"
          element={
            me ? (
              <Navigate to={ROLE_HOME[me.role] ?? "/login"} replace />
            ) : (
              <RouteErrorBoundary>
                <WelcomePage />
              </RouteErrorBoundary>
            )
          }
        />
        <Route
          path="/login"
          element={
            me ? (
              <Navigate to={home} replace />
            ) : (
              <RouteErrorBoundary>
                <LoginPage />
              </RouteErrorBoundary>
            )
          }
        />
        <Route
          path="/register"
          element={
            me ? (
              <Navigate to={home} replace />
            ) : (
              <RouteErrorBoundary>
                <RegisterPage />
              </RouteErrorBoundary>
            )
          }
        />
        <Route
          path="/forgot"
          element={
            <RouteErrorBoundary>
              <ForgotResetPage />
            </RouteErrorBoundary>
          }
        />
        <Route
          path="/privacy"
          element={
            <RouteErrorBoundary>
              <LegalPage kind="privacy" />
            </RouteErrorBoundary>
          }
        />
        <Route
          path="/terms"
          element={
            <RouteErrorBoundary>
              <LegalPage kind="terms" />
            </RouteErrorBoundary>
          }
        />
        <Route
          path="/status"
          element={
            <RouteErrorBoundary>
              <StatusPage />
            </RouteErrorBoundary>
          }
        />

        <Route
          path="/student"
          element={
            <RequireAuth role="student">
              <HomePage />
            </RequireAuth>
          }
        />
        <Route
          path="/student/learn"
          element={
            <RequireAuth role="student">
              <LearnPage />
            </RequireAuth>
          }
        />
        <Route
          path="/student/learn/:subject/:chapter"
          element={
            <RequireAuth role="student">
              <LearnChapterPage />
            </RequireAuth>
          }
        />
        <Route
          path="/student/tutor"
          element={
            <RequireAuth role="student">
              <AITutorPage />
            </RequireAuth>
          }
        />
        <Route
          path="/student/quiz"
          element={
            <RequireAuth role="student">
              <QuizPage />
            </RequireAuth>
          }
        />
        <Route
          path="/student/me"
          element={
            <RequireAuth role="student">
              <MePage />
            </RequireAuth>
          }
        />

        <Route
          path="/teacher"
          element={
            <RequireAuth role="teacher">
              <TeacherHomePage />
            </RequireAuth>
          }
        />
        <Route
          path="/teacher/create"
          element={
            <RequireAuth role="teacher">
              <CreatePage />
            </RequireAuth>
          }
        />
        <Route
          path="/teacher/classes"
          element={
            <RequireAuth role="teacher">
              <ClassesPage />
            </RequireAuth>
          }
        />
        <Route
          path="/teacher/assessments"
          element={
            <RequireAuth role="teacher">
              <AssessmentsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/teacher/analytics"
          element={
            <RequireAuth role="teacher">
              <AnalyticsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/teacher/profile"
          element={
            <RequireAuth role="teacher">
              <TeacherProfilePage />
            </RequireAuth>
          }
        />
        <Route
          path="/parent"
          element={
            <RequireAuth role="parent">
              <ParentDashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/admin"
          element={
            <RequireAuth role="admin">
              <AdminDashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/school"
          element={
            <RequireAuth role="school_admin">
              <SchoolDashboard />
            </RequireAuth>
          }
        />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}

function App() {
  // I18N: a language switch re-renders this component IN PLACE. The elements
  // below are recreated on every render, so every t() call re-evaluates in
  // the new language while every mounted component keeps its state. The
  // previous shape keyed a wrapper by a counter, which REMOUNTED the whole
  // tree: switching language mid-quiz discarded the in-progress attempt, a
  // streaming tutor answer was aborted, and half-filled forms reset — all
  // from a control the UI invites users to press at any time. Re-render,
  // never remount.
  const [langTick, setLangTick] = useState(0);
  useEffect(() => onLangChange(() => setLangTick((n) => n + 1)), []);
  return (
    <BrowserRouter>
      <DocumentTitle tick={langTick} />
      <Suspense fallback={<Loading />}>
        <RoutesSwitch />
        <Footer />
      </Suspense>
    </BrowserRouter>
  );
}

/** Per-route document titles, longest prefix first. */
const ROUTE_TITLES: Array<[string, Parameters<typeof t>[0]]> = [
  ["/student/tutor", "aiTutor"],
  ["/student/quiz", "practice"],
  ["/student/learn", "learn"],
  ["/student/me", "me"],
  ["/student", "home"],
  ["/teacher", "dashboard"],
  ["/parent", "dashboard"],
  ["/admin", "dashboard"],
  ["/school", "dashboard"],
  ["/login", "login"],
  ["/register", "register"],
  ["/forgot", "resetTitle"],
  ["/status", "statusPage"],
  ["/privacy", "privacy"],
  ["/terms", "terms"],
];

function DocumentTitle({ tick }: { tick: number }) {
  const location = useLocation();
  useEffect(() => {
    // Every route kept the landing <title> before this, so browser history
    // entries and screen-reader tab announcements were indistinguishable
    // between the tutor, a quiz and the admin dashboard. `tick` re-runs the
    // effect on a language switch.
    const match = ROUTE_TITLES.find(
      ([prefix]) =>
        location.pathname === prefix ||
        location.pathname.startsWith(prefix + "/"),
    );
    document.title = match ? `${t(match[1])} · ${t("appName")}` : t("appName");
  }, [location.pathname, tick]);
  return null;
}

function Footer() {
  return (
    <footer className="footer">
      <div>
        <Link to="/privacy">{t("privacy")}</Link> ·{" "}
        <Link to="/terms">{t("terms")}</Link> ·{" "}
        <Link to="/status">{t("statusPage")}</Link>
      </div>
      <div>
        © {new Date().getFullYear()} {t("appName")}
      </div>
    </footer>
  );
}

export { App, queryClient };
