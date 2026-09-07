import { useCallback, useEffect, useState } from "react";
import { del, get, pickFolder, post } from "../api";
import type { Cluster, ExportStatus, Group } from "../types";

interface Preview {
  count: number;
  files: { id: number; rel_path: string }[];
}

const PREVIEW_LIMIT = 60;

export default function ExportView() {
  const [clusters, setClusters] = useState<Cluster[] | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [preview, setPreview] = useState<Preview | null>(null);
  const [dest, setDest] = useState<string | null>(null);
  const [mode, setMode] = useState<"copy" | "move">("copy");
  const [status, setStatus] = useState<ExportStatus | null>(null);
  const [groupName, setGroupName] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    get<Cluster[]>("/clusters").then(setClusters);
    get<Group[]>("/groups").then(setGroups);
  }, []);

  // refetch the matching photos whenever the selection changes
  useEffect(() => {
    if (selected.size === 0) {
      setPreview(null);
      return;
    }
    const ids = [...selected].join(",");
    const t = setTimeout(() => {
      get<Preview>(`/export/preview?cluster_ids=${ids}`).then(setPreview);
    }, 300);
    return () => clearTimeout(t);
  }, [selected]);

  // poll the status while an export is running
  useEffect(() => {
    if (status?.phase !== "running") return;
    const id = setInterval(async () => {
      const s = await get<ExportStatus>("/export/status");
      setStatus(s);
      if (s.phase !== "running") clearInterval(id);
    }, 700);
    return () => clearInterval(id);
  }, [status?.phase]);

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const applyGroup = (g: Group) => setSelected(new Set(g.cluster_ids));

  const saveGroup = async () => {
    const name = groupName.trim();
    if (!name || selected.size === 0) return;
    await post("/groups", { name, cluster_ids: [...selected] });
    setGroups(await get<Group[]>("/groups"));
    setGroupName("");
    setMsg(`"${name}" grubu kaydedildi.`);
  };

  const removeGroup = async (g: Group) => {
    if (!window.confirm(`"${g.name}" grubu silinsin mi? (Fotoğraflara dokunulmaz)`)) return;
    await del(`/groups/${g.id}`);
    setGroups(await get<Group[]>("/groups"));
  };

  const chooseDest = async () => {
    const path = await pickFolder();
    if (path) setDest(path);
  };

  const start = useCallback(async () => {
    if (!dest || selected.size === 0) return;
    if (mode === "move") {
      const ok = window.confirm(
        "TAŞIMA modu: fotoğraflar hedefe kopyalandıktan sonra KAYNAKTAN SİLİNECEK. Emin misiniz?",
      );
      if (!ok) return;
    }
    setMsg(null);
    try {
      await post("/export", { cluster_ids: [...selected], dest_path: dest, mode });
      setStatus(await get<ExportStatus>("/export/status"));
    } catch (e) {
      setMsg((e as Error).message);
    }
  }, [dest, selected, mode]);

  if (clusters === null) return <p className="text-neutral-500">Yükleniyor…</p>;

  if (clusters.length === 0) {
    return (
      <div className="mt-16 text-center text-neutral-500">
        <div className="mb-3 text-4xl">📤</div>
        <p>
          Dışa aktarılacak kişi yok. Önce <b>Tarama</b> sekmesinden arşivinizi
          tarayın, sonra <b>Kişiler</b> sekmesinden kümeleri düzenleyin.
        </p>
      </div>
    );
  }

  const namedFirst = [...clusters].sort((a, b) => {
    if (Boolean(a.name) !== Boolean(b.name)) return a.name ? -1 : 1;
    return b.face_count - a.face_count;
  });

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[1fr_320px]">
      <div>
        <h2 className="mb-1 text-xl font-semibold">Kişileri seçin</h2>
        <p className="mb-4 text-sm text-neutral-500">
          Seçtiğiniz kişilerden <b>en az birinin</b> bulunduğu tüm fotoğraflar
          dışa aktarılır.
        </p>

        {groups.length > 0 && (
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <span className="text-sm text-neutral-500">Kayıtlı gruplar:</span>
            {groups.map((g) => (
              <span
                key={g.id}
                className="flex items-center gap-1 rounded-full border border-neutral-300 bg-white pl-3 text-sm"
              >
                <button className="py-1 hover:text-emerald-600" onClick={() => applyGroup(g)}>
                  {g.name}
                </button>
                <button
                  className="px-2 py-1 text-neutral-400 hover:text-red-500"
                  onClick={() => removeGroup(g)}
                  title="Grubu sil"
                >
                  ✕
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-3">
          {namedFirst.map((c) => (
            <button
              key={c.id}
              onClick={() => toggle(c.id)}
              className={`overflow-hidden rounded-xl border text-left transition-all ${
                selected.has(c.id)
                  ? "border-emerald-500 ring-2 ring-emerald-200"
                  : "border-neutral-200 bg-white hover:shadow"
              }`}
            >
              <div className="aspect-square w-full bg-neutral-100">
                {c.cover_face_id && (
                  <img
                    src={`/api/face-thumb/${c.cover_face_id}`}
                    alt=""
                    loading="lazy"
                    className="h-full w-full object-cover"
                  />
                )}
              </div>
              <div className="px-2 py-1.5">
                <div className="truncate text-xs font-medium">
                  {c.name ?? `Kişi #${c.id}`}
                </div>
                <div className="text-[10px] text-neutral-500">{c.photo_count} foto</div>
              </div>
            </button>
          ))}
        </div>

        {preview && (
          <div className="mt-8">
            <h3 className="mb-3 font-medium">
              Eşleşen fotoğraflar:{" "}
              <span className="text-emerald-600">{preview.count}</span>
              {preview.count > PREVIEW_LIMIT && (
                <span className="ml-2 text-xs font-normal text-neutral-400">
                  (ilk {PREVIEW_LIMIT} tanesi gösteriliyor)
                </span>
              )}
            </h3>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(96px,1fr))] gap-2">
              {preview.files.slice(0, PREVIEW_LIMIT).map((f) => (
                <img
                  key={f.id}
                  src={`/api/thumb/${f.id}`}
                  alt=""
                  title={f.rel_path}
                  loading="lazy"
                  className="aspect-square w-full rounded-lg border border-neutral-200 object-cover"
                />
              ))}
            </div>
          </div>
        )}
      </div>

      <aside className="lg:sticky lg:top-20 lg:self-start">
        <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
          <h3 className="mb-4 font-semibold">Dışa Aktar</h3>

          <div className="mb-3 text-sm">
            <div className="mb-1 text-neutral-500">Seçilen kişi</div>
            <div className="font-medium">{selected.size}</div>
          </div>
          <div className="mb-4 text-sm">
            <div className="mb-1 text-neutral-500">Eşleşen fotoğraf</div>
            <div className="font-medium">{preview?.count ?? 0}</div>
          </div>

          <button
            onClick={chooseDest}
            className="mb-2 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm hover:bg-neutral-50"
          >
            {dest ? "Hedefi Değiştir" : "Hedef Klasör Seç"}
          </button>
          {dest && (
            <p className="mb-3 break-all text-xs text-neutral-500">{dest}</p>
          )}

          <div className="mb-4 flex gap-4 text-sm">
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                checked={mode === "copy"}
                onChange={() => setMode("copy")}
              />
              Kopyala
            </label>
            <label className="flex items-center gap-1.5 text-red-600">
              <input
                type="radio"
                checked={mode === "move"}
                onChange={() => setMode("move")}
              />
              Taşı
            </label>
          </div>

          <button
            onClick={start}
            disabled={!dest || selected.size === 0 || status?.phase === "running"}
            className="w-full rounded-xl bg-neutral-900 py-2.5 font-medium text-white hover:bg-neutral-700 disabled:opacity-40"
          >
            {status?.phase === "running" ? "Aktarılıyor…" : "Başlat"}
          </button>
          {msg && <p className="mt-3 text-sm text-neutral-600">{msg}</p>}

          {status && status.phase !== "idle" && (
            <div className="mt-4 border-t border-neutral-100 pt-4 text-sm">
              <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-neutral-100">
                <div
                  className="h-full bg-emerald-500 transition-all"
                  style={{
                    width: `${
                      status.total
                        ? Math.round(
                            ((status.copied + status.skipped + status.errors) /
                              status.total) *
                              100,
                          )
                        : 0
                    }%`,
                  }}
                />
              </div>
              <p className="text-neutral-600">
                {status.copied} kopyalandı · {status.skipped} zaten vardı ·{" "}
                <span className={status.errors ? "text-red-600" : ""}>
                  {status.errors} hata
                </span>
              </p>
              {status.phase === "done" && (
                <p className="mt-1 font-medium text-emerald-600">Tamamlandı ✓</p>
              )}
              {status.error_files.length > 0 && (
                <div className="mt-2 max-h-40 overflow-y-auto rounded-lg border border-red-100 bg-red-50 p-2 text-xs">
                  {status.error_files.map((e) => (
                    <div key={e.path} className="mb-1">
                      <b>{e.path}</b>: {e.error}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="mt-4 rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
          <h3 className="mb-2 text-sm font-semibold">Seçimi grup olarak kaydet</h3>
          <div className="flex gap-2">
            <input
              value={groupName}
              onChange={(e) => setGroupName(e.target.value)}
              placeholder="örn. X ailesi"
              className="min-w-0 flex-1 rounded-lg border border-neutral-300 px-3 py-1.5 text-sm outline-none focus:border-neutral-500"
            />
            <button
              onClick={saveGroup}
              disabled={!groupName.trim() || selected.size === 0}
              className="rounded-lg bg-neutral-900 px-3 py-1.5 text-sm text-white disabled:opacity-40"
            >
              Kaydet
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}
