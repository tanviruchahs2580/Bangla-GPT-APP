import React, { lazy, Suspense, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, Link } from "react-router-dom";
import "./styles.css";
import "@fontsource/noto-sans-bengali/400.css";
import "@fontsource/noto-sans-bengali/700.css";
import "@fontsource/hind-siliguri/400.css";
import "@fontsource/hind-siliguri/600.css";
import { getToken, setLogoutCleanup } from "./api";
import { AuthProvider, ROLE_HOME, useAuth } from "./AuthContext";
import { AppShell } from "./AppShell";
import { Skeleton } from "./components/ui";
import { SkipLink } from "./components/SkipLink";
import {
  AppErrorBoundary,
  RouteErrorBoundary,
} from "./components/AppErrorBoundary";
import { PublicLanguageToggle } from "./components/PublicLanguageToggle";
import { onLangChange, t } from "./i18n";
import { initInstallPrompt } from "./lib/installPrompt";
import { initLowData } from "./lib/lowData";
// AUD-HI-07 / I-12: Sentry + web-vitals are consent-gated; nothing leaves the
// device until the user opts in (see lib/telemetry.ts and the MePage toggle).
import { initTelemetry } from "./lib/telemetry";

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
      <main
        id="main-content"
        tabIndex={-1}
        className="container"
        aria-live="polite"
      >
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
  return (
    <main
      id="main-content"
      tabIndex={-1}
      className="container"
      aria-live="assertive"
    >
      <div className="card stack">
        <h1>{t("apiUnreachableTitle")}</h1>
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
    <main
      id="main-content"
      tabIndex={-1}
      className="container"
      aria-live="polite"
    >
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
  return (
    <BrowserRouter>
      <LangRoot>
        {/* AUD-G-02: first focusable element on every screen, above both the
            public routes and the authenticated shell. */}
        <SkipLink />
        <Suspense fallback={<Loading />}>
          <RoutesSwitch />
          <Footer />
        </Suspense>
      </LangRoot>
    </BrowserRouter>
  );
}

// language switch remounts the tree in place instead of a full
// page reload (navigate(0)) — instant, no network round-trip, PWA-safe.
function LangRoot({ children }: { children: React.ReactNode }) {
  const [tick, setTick] = useState(0);
  useEffect(() => onLangChange(() => setTick((n) => n + 1)), []);
  return <React.Fragment key={tick}>{children}</React.Fragment>;
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

// apply the persisted low-data mode before first paint.
initLowData();
initInstallPrompt();
// Consent-gated: a no-op unless the user opted in (AUD-HI-07).
initTelemetry();
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* Last-resort boundary for errors above the routes (providers, shell);
        per-route recovery lives in RouteErrorBoundary (F-001). */}
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </QueryClientProvider>
    </AppErrorBoundary>
  </React.StrictMode>,
);

// PWA: register the service worker in production builds only — in dev the
// cache-first strategy would serve stale Vite modules and break HMR.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* offline support is best-effort; never block the app on SW errors */
    });
  });
}
