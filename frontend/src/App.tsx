import { useEffect, useState } from "react";
import { get } from "./api";
import type { ScanStatus } from "./types";
import ScanView from "./views/ScanView";
import PeopleView from "./views/PeopleView";
import ExportView from "./views/ExportView";
import SettingsModal from "./views/SettingsModal";

type Tab = "scan" | "people" | "export";

const TABS: { id: Tab; label: string }[] = [
  { id: "scan", label: "Tarama" },
  { id: "people", label: "Kişiler" },
  { id: "export", label: "Dışa Aktar" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("scan");
  const [scan, setScan] = useState<ScanStatus | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const s = await get<ScanStatus>("/scan/status");
        if (alive) setScan(s);
      } catch {
        /* server not up yet */
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="min-h-screen bg-neutral-50 text-neutral-900">
      <header className="sticky top-0 z-20 border-b border-neutral-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-8 px-6 py-3">
          <h1 className="text-lg font-semibold tracking-tight">
            <span className="mr-1.5">🙂</span>Facey
          </h1>
          <nav className="flex gap-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`rounded-lg px-4 py-1.5 text-sm font-medium transition-colors ${
                  tab === t.id
                    ? "bg-neutral-900 text-white"
                    : "text-neutral-600 hover:bg-neutral-100"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
          {scan?.running && (
            <span className="ml-auto flex items-center gap-2 text-xs text-neutral-500">
              <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
              Tarama sürüyor · {scan.done}/{scan.total}
            </span>
          )}
          <button
            onClick={() => setShowSettings(true)}
            title="Ayarlar"
            className={`rounded-lg px-2 py-1.5 text-neutral-500 hover:bg-neutral-100 ${scan?.running ? "" : "ml-auto"}`}
          >
            ⚙︎
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        {tab === "scan" && <ScanView scan={scan} />}
        {tab === "people" && <PeopleView />}
        {tab === "export" && <ExportView />}
      </main>
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
    </div>
  );
}
