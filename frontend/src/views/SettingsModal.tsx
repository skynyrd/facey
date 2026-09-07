import { useEffect, useState } from "react";
import { get, post } from "../api";

const FIELDS: { key: string; label: string; hint: string }[] = [
  {
    key: "assign_threshold",
    label: "Atama eşiği",
    hint: "Yeni yüzün mevcut kişiye sayılması için min. benzerlik (0-1, ↑ = daha katı)",
  },
  {
    key: "cluster_distance",
    label: "Kümeleme mesafesi",
    hint: "Yeni kümeler oluşurken izin verilen uzaklık (↑ = daha az, daha geniş küme)",
  },
  {
    key: "min_det_score",
    label: "Min. tespit skoru",
    hint: "Altındaki yüzler kümelenmez (düşük kalite havuzu)",
  },
  {
    key: "min_face_px",
    label: "Min. yüz boyutu (px)",
    hint: "Bundan küçük yüzler kümelenmez",
  },
];

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const [values, setValues] = useState<Record<string, string> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    get<Record<string, string>>("/settings").then(setValues);
  }, []);

  const save = async () => {
    if (!values) return;
    setMsg(null);
    try {
      await post("/settings", { values });
      setMsg("Kaydedildi. Eşikler bundan sonraki kümelemelerde geçerli olur.");
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const recluster = async () => {
    const r = await post<{ assigned: number; new_clusters: number }>("/recluster");
    setMsg(`Yeniden kümelendi: ${r.assigned} yüz atandı, ${r.new_clusters} yeni küme.`);
  };

  const clearCache = async () => {
    const r = await post<{ removed: number }>("/cache/clear");
    setMsg(`${r.removed} önizleme dosyası temizlendi.`);
  };

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-6"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Ayarlar</h2>
          <button
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-sm text-neutral-500 hover:bg-neutral-100"
          >
            Kapat ✕
          </button>
        </div>

        {values === null ? (
          <p className="text-neutral-500">Yükleniyor…</p>
        ) : (
          <div className="space-y-4">
            {FIELDS.map((f) => (
              <div key={f.key}>
                <label className="mb-1 block text-sm font-medium">{f.label}</label>
                <input
                  value={values[f.key] ?? ""}
                  onChange={(e) =>
                    setValues({ ...values, [f.key]: e.target.value })
                  }
                  className="w-full rounded-lg border border-neutral-300 px-3 py-1.5 text-sm outline-none focus:border-neutral-500"
                />
                <p className="mt-1 text-xs text-neutral-400">{f.hint}</p>
              </div>
            ))}
            <div className="flex flex-wrap gap-2 pt-2">
              <button
                onClick={save}
                className="rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700"
              >
                Kaydet
              </button>
              <button
                onClick={recluster}
                className="rounded-lg border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-50"
              >
                Yeniden Kümele
              </button>
              <button
                onClick={clearCache}
                className="rounded-lg border border-neutral-300 px-4 py-2 text-sm text-neutral-500 hover:bg-neutral-50"
              >
                Önizleme Cache'ini Temizle
              </button>
            </div>
            {msg && <p className="text-sm text-emerald-700">{msg}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
