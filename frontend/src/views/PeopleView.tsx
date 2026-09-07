import { useCallback, useEffect, useState } from "react";
import { get, post } from "../api";
import type { Cluster } from "../types";
import ClusterDetail from "./ClusterDetail";

export default function PeopleView() {
  const [clusters, setClusters] = useState<Cluster[] | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [detail, setDetail] = useState<Cluster | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const rows = await get<Cluster[]>(`/clusters?include_hidden=${showHidden}`);
    setClusters(rows);
  }, [showHidden]);

  useEffect(() => {
    reload();
  }, [reload]);

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const mergeSelected = async () => {
    if (!clusters || selected.size < 2) return;
    // target: the selected cluster with the most faces, so its name and cover survive
    const chosen = clusters.filter((c) => selected.has(c.id));
    const target = chosen.reduce((a, b) => (b.face_count > a.face_count ? b : a));
    const sources = chosen.map((c) => c.id).filter((id) => id !== target.id);
    setBusy(true);
    try {
      await post("/clusters/merge", { target_id: target.id, source_ids: sources });
      setSelected(new Set());
      await reload();
    } finally {
      setBusy(false);
    }
  };

  if (clusters === null) return <p className="text-neutral-500">Yükleniyor…</p>;

  if (clusters.length === 0) {
    return (
      <div className="mt-16 text-center text-neutral-500">
        <div className="mb-3 text-4xl">👤</div>
        <p>
          Henüz kişi yok. Önce <b>Tarama</b> sekmesinden bir klasör tarayın.
        </p>
      </div>
    );
  }

  const visible = clusters.filter((c) => showHidden || !c.hidden);

  return (
    <div>
      <div className="mb-5 flex items-center gap-3">
        <h2 className="text-xl font-semibold">Kişiler</h2>
        <span className="text-sm text-neutral-400">{visible.length} küme</span>
        <label className="ml-auto flex items-center gap-2 text-sm text-neutral-600">
          <input
            type="checkbox"
            checked={showHidden}
            onChange={(e) => setShowHidden(e.target.checked)}
          />
          Yoksayılanları göster
        </label>
      </div>

      <p className="mb-4 text-sm text-neutral-500">
        Aynı kişiye ait kümeleri seçip birleştirin; detay için karta tıklayın.
      </p>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-4 pb-24">
        {visible.map((c) => (
          <ClusterCard
            key={c.id}
            cluster={c}
            selected={selected.has(c.id)}
            onSelect={() => toggleSelect(c.id)}
            onOpen={() => setDetail(c)}
          />
        ))}
      </div>

      {selected.size > 0 && (
        <div className="fixed inset-x-0 bottom-6 z-30 mx-auto flex w-fit items-center gap-4 rounded-2xl border border-neutral-200 bg-white px-6 py-3 shadow-lg">
          <span className="text-sm font-medium">{selected.size} küme seçildi</span>
          <button
            onClick={mergeSelected}
            disabled={selected.size < 2 || busy}
            className="rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-40"
          >
            Aynı Kişi — Birleştir
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="text-sm text-neutral-500 hover:text-neutral-800"
          >
            Vazgeç
          </button>
        </div>
      )}

      {detail && (
        <ClusterDetail
          cluster={detail}
          onClose={() => setDetail(null)}
          onChanged={async () => {
            await reload();
          }}
        />
      )}
    </div>
  );
}

function ClusterCard({
  cluster,
  selected,
  onSelect,
  onOpen,
}: {
  cluster: Cluster;
  selected: boolean;
  onSelect: () => void;
  onOpen: () => void;
}) {
  return (
    <div
      className={`group relative cursor-pointer overflow-hidden rounded-2xl border bg-white shadow-sm transition-all hover:shadow-md ${
        selected ? "border-emerald-500 ring-2 ring-emerald-200" : "border-neutral-200"
      }`}
      onClick={onOpen}
    >
      <button
        onClick={(e) => {
          e.stopPropagation();
          onSelect();
        }}
        title="Birleştirmek için seç"
        className={`absolute left-2 top-2 z-10 flex h-6 w-6 items-center justify-center rounded-full border text-xs transition-opacity ${
          selected
            ? "border-emerald-500 bg-emerald-500 text-white opacity-100"
            : "border-neutral-300 bg-white/90 text-transparent opacity-0 group-hover:opacity-100"
        }`}
      >
        ✓
      </button>
      {cluster.hidden ? (
        <span className="absolute right-2 top-2 z-10 rounded bg-neutral-800/70 px-1.5 py-0.5 text-[10px] text-white">
          yoksayıldı
        </span>
      ) : null}
      <div className="aspect-square w-full bg-neutral-100">
        {cluster.cover_face_id && (
          <img
            src={`/api/face-thumb/${cluster.cover_face_id}`}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover"
          />
        )}
      </div>
      <div className="px-3 py-2">
        <div className="truncate text-sm font-medium">
          {cluster.name ?? `Kişi #${cluster.id}`}
        </div>
        <div className="text-xs text-neutral-500">
          {cluster.face_count} yüz · {cluster.photo_count} foto
        </div>
      </div>
    </div>
  );
}
