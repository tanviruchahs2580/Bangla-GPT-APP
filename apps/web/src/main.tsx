import React, { lazy, Suspense, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, Link } from "react-router-dom";
import * as Sentry from "@sentry/react";

// S0.6: Sentry — no-op when DSN absent
if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN as string,
    environment: import.meta.env.MODE,
    tracesSampleRate: 0.1,
  });
}
import "./styles.css";
import "@fontsource/noto-sans-bengali/400.css";
import "@fontsource/noto-sans-bengali/700.css";
import "@fontsource/hind-siliguri/400.css";
import "@fontsource/hind-siliguri/600.css";
import { getToken } from "./api";
import { AuthProvider, ROLE_HOME, useAuth } from "./AuthContext";
import { AppShell } from "./AppShell";
import { Skeleton } from "./components/ui";
import { onLangChange, t } from "./i18n";
import { initInstallPrompt } from "./lib/installPrompt";
import { initLowData } from "./lib/lowData";

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

function RequireAuth({
  role,
  children,
}: {
  role?: string;
  children: React.ReactNode;
}) {
  const { me, loading } = useAuth();
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
  // Token present but profile unloadable (e.g. expired token, offline):
  // never trap the user on a skeleton — send them to re-login.
  if (me === null) return <Navigate to="/login" replace />;
  if (role && me.role !== role)
    return <Navigate to={ROLE_HOME[me.role] ?? "/login"} replace />;
  return <AppShell>{children}</AppShell>;
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
    <Routes>
      <Route path="/" element={<Navigate to={home} replace />} />
      <Route
        path="/welcome"
        element={
          me ? (
            <Navigate to={ROLE_HOME[me.role] ?? "/login"} replace />
          ) : (
            <WelcomePage />
          )
        }
      />
      <Route
        path="/login"
        element={me ? <Navigate to={home} replace /> : <LoginPage />}
      />
      <Route
        path="/register"
        element={me ? <Navigate to={home} replace /> : <RegisterPage />}
      />
      <Route path="/forgot" element={<ForgotResetPage />} />
      <Route path="/privacy" element={<LegalPage kind="privacy" />} />
      <Route path="/terms" element={<LegalPage kind="terms" />} />
      <Route path="/status" element={<StatusPage />} />

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
  );
}

function App() {
  return (
    <BrowserRouter>
      <LangRoot>
        <Suspense fallback={<Loading />}>
          <RoutesSwitch />
          <Footer />
        </Suspense>
      </LangRoot>
    </BrowserRouter>
  );
}

// RENO: language switch remounts the tree in place instead of a full
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

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div className="container" role="alert">
          <div className="card">
            <h2>{t("errorGeneric")}</h2>
            <p className="muted">{this.state.error.message}</p>
            <button
              className="btn btn-primary"
              onClick={() => window.location.reload()}
            >
              {t("retry")}
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// S1.13: apply the persisted low-data mode before first paint.
initLowData();
initInstallPrompt();
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
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
