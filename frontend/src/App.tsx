import { useEffect, useState } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";

import { getDrugs } from "./api/client";
import { Sidebar } from "./components/Sidebar";
import { SurfaceNav } from "./components/SurfaceNav";
import { Dashboard } from "./pages/Dashboard";
import { Discover } from "./pages/Discover";
import { useVigilensStore } from "./store/useVigilensStore";

function CasefileGate() {
  const drugs = useVigilensStore((state) => state.drugs);
  const selectedDrugId = useVigilensStore((state) => state.selectedDrugId);
  const setDrugs = useVigilensStore((state) => state.setDrugs);
  const setSelectedDrugId = useVigilensStore((state) => state.setSelectedDrugId);

  const { drugId } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function resolveCasefile() {
      setLoading(true);
      setError(null);

      try {
        let availableDrugs = drugs;
        const requestedDrugMissing =
          Boolean(drugId) && availableDrugs.length > 0 && !availableDrugs.some((drug) => drug.id === drugId);
        if (availableDrugs.length === 0 || requestedDrugMissing) {
          availableDrugs = await getDrugs();
          if (cancelled) {
            return;
          }
          setDrugs(availableDrugs);
        }

        if (availableDrugs.length === 0) {
          navigate("/discover", { replace: true });
          return;
        }

        const fallbackDrugId =
          availableDrugs.find((drug) => drug.id === selectedDrugId)?.id ?? availableDrugs[0].id;
        const targetDrugId =
          drugId && availableDrugs.some((drug) => drug.id === drugId) ? drugId : fallbackDrugId;

        if (selectedDrugId !== targetDrugId) {
          setSelectedDrugId(targetDrugId);
        }

        if (drugId !== targetDrugId) {
          navigate(`/casefile/${targetDrugId}`, { replace: true });
          return;
        }

        if (!cancelled) {
          setLoading(false);
        }
      } catch (nextError) {
        if (!cancelled) {
          setError(nextError instanceof Error ? nextError.message : "Casefile unavailable");
          setLoading(false);
        }
      }
    }

    void resolveCasefile();
    return () => {
      cancelled = true;
    };
  }, [drugId, drugs, navigate, selectedDrugId, setDrugs, setSelectedDrugId]);

  if (error) {
    return (
      <main className="mx-auto flex min-h-[calc(100vh-4rem)] w-full max-w-[900px] items-center justify-center px-4 py-10 sm:px-6 lg:px-8">
        <section className="w-full rounded-[1.6rem] border border-red-500/20 bg-red-500/10 p-6">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-red-200">Casefile Error</p>
          <h1 className="mt-2 font-display text-3xl text-[var(--text-primary)]">
            The casefile could not be opened.
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-red-100/90">{error}</p>
        </section>
      </main>
    );
  }

  if (loading) {
    return (
      <main className="mx-auto flex min-h-[calc(100vh-4rem)] w-full max-w-[900px] items-center justify-center px-4 py-10 sm:px-6 lg:px-8">
        <section className="w-full rounded-[1.6rem] border border-[var(--border)] bg-[linear-gradient(135deg,rgba(19,18,16,0.98),rgba(33,24,18,0.92))] p-6 shadow-[0_20px_60px_rgba(0,0,0,0.26)]">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-tertiary)]">
            Casefile
          </p>
          <h1 className="mt-2 font-display text-3xl text-[var(--text-primary)]">
            Preparing the selected drug workspace.
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">
            VigiLens is locating the tracked portfolio and opening the correct casefile.
          </p>
        </section>
      </main>
    );
  }

  return <Dashboard />;
}

function AppShell() {
  const location = useLocation();
  const showCasefileChrome = location.pathname.startsWith("/casefile");

  return (
    <>
      <SurfaceNav />
      {showCasefileChrome ? <Sidebar /> : null}
      <div className={showCasefileChrome ? "pt-16 lg:pl-14" : "pt-16"}>
        <Routes>
          <Route path="/" element={<Navigate to="/discover" replace />} />
          <Route path="/discover" element={<Discover />} />
          <Route path="/casefile" element={<CasefileGate />} />
          <Route path="/casefile/:drugId" element={<CasefileGate />} />
        </Routes>
      </div>
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
