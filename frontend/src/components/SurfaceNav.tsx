import { NavLink } from "react-router-dom";

import { useVigilensStore } from "../store/useVigilensStore";

function navClass(isActive: boolean): string {
  return isActive
    ? "border-[var(--accent-border)] bg-[var(--accent-dim)] text-[var(--accent)]"
    : "border-white/10 bg-white/[0.03] text-[var(--text-secondary)] hover:bg-white/[0.06] hover:text-[var(--text-primary)]";
}

export function SurfaceNav() {
  const drugs = useVigilensStore((state) => state.drugs);
  const selectedDrugId = useVigilensStore((state) => state.selectedDrugId);
  const preferredDrugId = drugs.find((drug) => drug.id === selectedDrugId)?.id ?? drugs[0]?.id ?? null;
  const casefileHref = preferredDrugId ? `/casefile/${preferredDrugId}` : "/casefile";

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-white/10 bg-[rgba(11,10,9,0.86)] backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-[1680px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <NavLink to="/discover" className="block">
          <p className="font-display text-lg tracking-[0.08em] text-[var(--text-primary)]">VigiLens</p>
          <p className="text-[11px] uppercase tracking-[0.24em] text-[var(--text-tertiary)]">
            Discover and casefile surfaces
          </p>
        </NavLink>

        <nav className="flex items-center gap-2">
          <NavLink
            to="/discover"
            className={({ isActive }) =>
              `rounded-full border px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] transition ${navClass(isActive)}`
            }
          >
            Discover
          </NavLink>
          <NavLink
            to={casefileHref}
            className={({ isActive }) =>
              `rounded-full border px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] transition ${navClass(isActive)}`
            }
          >
            Casefile
          </NavLink>
        </nav>
      </div>
    </header>
  );
}
