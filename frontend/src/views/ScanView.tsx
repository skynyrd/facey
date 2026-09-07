import { useState } from "react";
import { get, pickFolder, post } from "../api";
import type { ScanError, ScanStatus } from "../types";

const PHASE_LABELS: Record<string, string> = {
  idle: "Hazır",
  enumerating: "Dosyalar listeleniyor…",
  scanning: "Yüzler aranıyor…",
  clustering: "Kişiler gruplanıyor…",
  paused: "Duraklatıldı",
  done: "Tarama tamamlandı",
  error: "Hata oluştu",
};

export default function ScanView({ scan }: { scan: ScanStatus | null }) {
  const [busy, setBusy] = useState(false);
  const [errorList, setErrorList] = useState<ScanError[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const startScan = async (path: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await post("/library", { root_path: path });
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const chooseFolder = async () => {
    const path = await pickFolder();
    if (!path) return;
    if (scan?.root_path && scan.root_path !== path) {
      const ok = window.confirm(
        "Yeni bir klasör seçtiniz. Önceki taramanın tüm verileri (kişiler, birleştirmeler) silinecek. Devam edilsin mi?",
      );
      if (!ok) return;
    }
    await startScan(path);
  };

  const showErrors = async () => {
    setErrorList(await get<ScanError[]>("/scan/errors"));
  };

  if (!scan) return <p className="text-neutral-500">Bağlanılıyor…</p>;

  if (!scan.root_path) {
    return (
      <div className="mx-auto mt-16 max-w-lg text-center">
        <div className="mb-4 text-5xl">📁</div>
        <h2 className="mb-2 text-2xl font-semibold">Fotoğraf arşivinizi seçin</h2>
        <p className="mb-6 text-neutral-500">
          Seçtiğiniz klasör ve tüm alt klasörleri taranır, fotoğraflardaki yüzler
          tespit edilir. Orijinal dosyalarınıza dokunulmaz; yalnızca küçük yüz
          önizlemeleri saklanır.
        </p>
        <button
          onClick={chooseFolder}
          disabled={busy}
          className="rounded-xl bg-neutral-900 px-6 py-3 font-medium text-white hover:bg-neutral-700 disabled:opacity-50"
        >
          Klasör Seç
        </button>
        {msg && <p className="mt-4 text-sm text-red-600">{msg}</p>}
      </div>
    );
  }

  const pct = scan.total > 0 ? Math.round((scan.done / scan.total) * 100) : 0;

  return (
    <div className="mx-auto max-w-2xl">
      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
        <div className="mb-1 flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">
            {PHASE_LABELS[scan.phase] ?? scan.phase}
          </h2>
          <span className="text-sm text-neutral-500">%{pct}</span>
        </div>
        <p className="mb-4 truncate text-xs text-neutral-400" title={scan.root_path}>
          {scan.root_path}
        </p>

        {scan.model === "loading" && (
          <p className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-700">
            Yüz tanıma modeli hazırlanıyor (ilk çalıştırmada ~330 MB indirilir)…
          </p>
        )}
        {scan.error && (
          <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {scan.error}
          </p>
        )}

        <div className="mb-4 h-2 overflow-hidden rounded-full bg-neutral-100">
          <div
            className="h-full rounded-full bg-emerald-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>

        <div className="mb-4 grid grid-cols-4 gap-3 text-center">
          <Stat label="Fotoğraf" value={`${scan.done}/${scan.total}`} />
          <Stat label="Yüz" value={String(scan.faces)} />
          <Stat label="Bekleyen" value={String(scan.pending)} />
          <Stat label="Hata" value={String(scan.errors)} />
        </div>

        {scan.current && (
          <p className="mb-4 truncate text-xs text-neutral-400" title={scan.current}>
            İşleniyor: {scan.current}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          {scan.running && !scan.paused && (
            <Btn onClick={() => post("/scan/pause")}>Duraklat</Btn>
          )}
          {scan.paused && (
            <Btn primary onClick={() => post("/scan/resume")}>
              Devam Et
            </Btn>
          )}
          {!scan.running && scan.pending > 0 && (
            <Btn primary onClick={() => post("/scan/resume")}>
              Kaldığı Yerden Sürdür
            </Btn>
          )}
          {!scan.running && (
            <>
              <Btn onClick={() => startScan(scan.root_path!)}>Yeniden Tara</Btn>
              <Btn onClick={chooseFolder}>Klasör Değiştir</Btn>
            </>
          )}
          {scan.errors > 0 && <Btn onClick={showErrors}>Hataları Göster</Btn>}
        </div>
        {msg && <p className="mt-3 text-sm text-red-600">{msg}</p>}

        {errorList && (
          <div className="mt-4 max-h-64 overflow-y-auto rounded-lg border border-neutral-200 text-xs">
            {errorList.length === 0 && (
              <p className="p-3 text-neutral-500">Hata kaydı yok.</p>
            )}
            {errorList.map((e) => (
              <div key={e.rel_path} className="border-b border-neutral-100 p-2">
                <span className="font-medium">{e.rel_path}</span>
                <span className="ml-2 text-neutral-500">{e.error}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {scan.phase === "done" && (
        <p className="mt-4 text-center text-sm text-neutral-500">
          Tarama bitti — <b>Kişiler</b> sekmesinden yüzleri inceleyebilirsiniz.
        </p>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-neutral-50 py-2">
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-xs text-neutral-500">{label}</div>
    </div>
  );
}

function Btn({
  children,
  onClick,
  primary,
}: {
  children: React.ReactNode;
  onClick: () => void;
  primary?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
        primary
          ? "bg-neutral-900 text-white hover:bg-neutral-700"
          : "border border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-50"
      }`}
    >
      {children}
    </button>
  );
}
