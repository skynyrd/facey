import { useEffect, useState } from "react";
import { get, post } from "../api";
import type { Cluster, FaceRow } from "../types";

export default function ClusterDetail({
  cluster,
  onClose,
  onChanged,
}: {
  cluster: Cluster;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const [faces, setFaces] = useState<FaceRow[] | null>(null);
  const [name, setName] = useState(cluster.name ?? "");
  const [hidden, setHidden] = useState(Boolean(cluster.hidden));
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [preview, setPreview] = useState<FaceRow | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = async () => {
    setFaces(await get<FaceRow[]>(`/clusters/${cluster.id}/faces`));
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cluster.id]);

  const saveName = async () => {
    await post(`/clusters/${cluster.id}`, { name });
    await onChanged();
  };

  const toggleHidden = async () => {
    await post(`/clusters/${cluster.id}`, { hidden: !hidden });
    setHidden(!hidden);
    await onChanged();
  };

  const removeSelected = async () => {
    if (selected.size === 0) return;
    setBusy(true);
    try {
      await post("/faces/unassign", { face_ids: [...selected] });
      setSelected(new Set());
      await reload();
      await onChanged();
    } finally {
      setBusy(false);
    }
  };

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-6"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-neutral-200 px-5 py-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={saveName}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
            placeholder={`Kişi #${cluster.id} — isim verin`}
            className="w-64 rounded-lg border border-transparent px-2 py-1 text-lg font-semibold outline-none focus:border-neutral-300"
          />
          <span className="text-sm text-neutral-400">
            {faces?.length ?? "…"} yüz
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={toggleHidden}
              className="rounded-lg border border-neutral-300 px-3 py-1.5 text-sm text-neutral-600 hover:bg-neutral-50"
            >
              {hidden ? "Yoksaymayı Kaldır" : "Yoksay"}
            </button>
            <button
              onClick={onClose}
              className="rounded-lg px-3 py-1.5 text-sm text-neutral-500 hover:bg-neutral-100"
            >
              Kapat ✕
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1">
          <div className="flex-1 overflow-y-auto p-4">
            {faces === null && <p className="text-neutral-500">Yükleniyor…</p>}
            <div className="grid grid-cols-[repeat(auto-fill,minmax(90px,1fr))] gap-2">
              {faces?.map((f) => (
                <div
                  key={f.id}
                  className={`relative cursor-pointer overflow-hidden rounded-lg border-2 ${
                    selected.has(f.id)
                      ? "border-red-400"
                      : preview?.id === f.id
                        ? "border-neutral-800"
                        : "border-transparent"
                  }`}
                  onClick={() => setPreview(f)}
                >
                  <img
                    src={`/api/face-thumb/${f.id}`}
                    alt=""
                    loading="lazy"
                    className="aspect-square w-full object-cover"
                  />
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(f.id);
                    }}
                    title="Bu kişiden çıkarmak için seç"
                    className={`absolute left-1 top-1 flex h-5 w-5 items-center justify-center rounded-full border text-[10px] ${
                      selected.has(f.id)
                        ? "border-red-400 bg-red-400 text-white"
                        : "border-neutral-300 bg-white/80 text-neutral-400"
                    }`}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>

          {preview && (
            <div className="w-80 shrink-0 overflow-y-auto border-l border-neutral-200 bg-neutral-50 p-4">
              <img
                src={`/api/thumb/${preview.file_id}`}
                alt=""
                className="w-full rounded-lg border border-neutral-200"
              />
              <p className="mt-2 break-all text-xs text-neutral-500">
                {preview.rel_path}
              </p>
            </div>
          )}
        </div>

        {selected.size > 0 && (
          <div className="flex items-center gap-3 border-t border-neutral-200 bg-red-50 px-5 py-3">
            <span className="text-sm">{selected.size} yüz seçildi</span>
            <button
              onClick={removeSelected}
              disabled={busy}
              className="rounded-lg bg-red-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-600 disabled:opacity-50"
            >
              Bu Kişiden Çıkar
            </button>
            <button
              onClick={() => setSelected(new Set())}
              className="text-sm text-neutral-500"
            >
              Vazgeç
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
