import { useCallback, useEffect, useRef, useState } from "react";

interface NavItem {
  id: string;
  label: string;
  icon: React.ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  {
    id: "section-overview",
    label: "Overview",
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="6" height="6" rx="1" />
        <rect x="11" y="3" width="6" height="6" rx="1" />
        <rect x="3" y="11" width="6" height="6" rx="1" />
        <rect x="11" y="11" width="6" height="6" rx="1" />
      </svg>
    ),
  },
  {
    id: "section-time-travel",
    label: "Time Travel",
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="10" cy="10" r="7" />
        <polyline points="10,6 10,10 13,12" />
      </svg>
    ),
  },
  {
    id: "section-belief-revision",
    label: "Belief Revision",
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 10h12" />
        <path d="M4 6h8" />
        <path d="M4 14h10" />
        <circle cx="16" cy="14" r="2" fill="currentColor" opacity="0.4" />
      </svg>
    ),
  },
  {
    id: "section-evidence",
    label: "Evidence",
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 3h8l3 3v11a1 1 0 01-1 1H6a1 1 0 01-1-1V4a1 1 0 011-1z" />
        <path d="M14 3v3h3" />
        <path d="M8 10h4" />
        <path d="M8 13h4" />
      </svg>
    ),
  },
  {
    id: "section-signals",
    label: "Signal Trajectory",
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="3,15 7,9 11,12 17,5" />
        <polyline points="14,5 17,5 17,8" />
      </svg>
    ),
  },
  {
    id: "section-analyst",
    label: "Analyst",
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="10" cy="7" r="3" />
        <path d="M4 17v-1a4 4 0 014-4h4a4 4 0 014 4v1" />
      </svg>
    ),
  },
];

export function Sidebar() {
  const [activeId, setActiveId] = useState<string>(NAV_ITEMS[0].id);
  const [hovered, setHovered] = useState(false);
  const observerRef = useRef<IntersectionObserver | null>(null);

  const handleClick = useCallback((sectionId: string) => {
    const el = document.getElementById(sectionId);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, []);

  useEffect(() => {
    observerRef.current?.disconnect();

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length > 0) {
          setActiveId(visible[0].target.id);
        }
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: 0 },
    );

    observerRef.current = observer;

    for (const item of NAV_ITEMS) {
      const el = document.getElementById(item.id);
      if (el) observer.observe(el);
    }

    return () => observer.disconnect();
  }, []);

  return (
    <nav
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="sidebar-nav group fixed left-0 top-16 z-40 hidden h-[calc(100vh-4rem)] flex-col border-r border-white/[0.06] bg-[var(--bg-panel)]/80 backdrop-blur-xl transition-all duration-300 lg:flex"
      style={{ width: hovered ? 180 : 56 }}
    >
      <div className="flex h-14 items-center justify-center border-b border-white/[0.06] px-3">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" className="shrink-0 text-[var(--accent)]">
          <path
            d="M12 2L4 7v10l8 5 8-5V7l-8-5z"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
          <circle cx="12" cy="12" r="3" fill="currentColor" opacity="0.3" />
        </svg>
        <span
          className="ml-2.5 overflow-hidden whitespace-nowrap font-display text-sm font-semibold text-[var(--text-primary)] transition-all duration-300"
          style={{ width: hovered ? 100 : 0, opacity: hovered ? 1 : 0 }}
        >
          VigiLens
        </span>
      </div>

      <div className="mt-3 flex flex-1 flex-col gap-0.5 px-2">
        {NAV_ITEMS.map((item) => {
          const isActive = activeId === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => handleClick(item.id)}
              className={`relative flex items-center gap-3 rounded-lg px-2.5 py-2.5 text-left transition-all duration-200 ${
                isActive
                  ? "bg-[var(--accent-dim)] text-[var(--accent)]"
                  : "text-[var(--text-tertiary)] hover:bg-white/[0.04] hover:text-[var(--text-secondary)]"
              }`}
            >
              {isActive && (
                <span className="absolute -left-2 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-[var(--accent)]" />
              )}
              <span className="shrink-0">{item.icon}</span>
              <span
                className="overflow-hidden whitespace-nowrap text-xs font-medium transition-all duration-300"
                style={{ width: hovered ? 100 : 0, opacity: hovered ? 1 : 0 }}
              >
                {item.label}
              </span>
            </button>
          );
        })}
      </div>

      <div className="border-t border-white/[0.06] p-3">
        <div
          className="overflow-hidden whitespace-nowrap text-center text-[10px] text-[var(--text-tertiary)] transition-all duration-300"
          style={{ opacity: hovered ? 0.7 : 0, height: hovered ? 16 : 0 }}
        >
          Memory Genesis 2026
        </div>
      </div>
    </nav>
  );
}
