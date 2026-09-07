export interface ScanStatus {
  phase: string;
  running: boolean;
  paused: boolean;
  root_path: string | null;
  total: number;
  done: number;
  pending: number;
  errors: number;
  faces: number;
  current: string | null;
  model: string;
  error: string | null;
}

export interface Cluster {
  id: number;
  name: string | null;
  hidden: number;
  cover_face_id: number | null;
  face_count: number;
  photo_count: number;
}

export interface FaceRow {
  id: number;
  file_id: number;
  det_score: number;
  rel_path: string;
}

export interface Group {
  id: number;
  name: string;
  cluster_ids: number[];
}

export interface ExportStatus {
  phase: string;
  mode: string;
  dest: string | null;
  total: number;
  copied: number;
  skipped: number;
  errors: number;
  current: string | null;
  error_files: { path: string; error: string }[];
}

export interface ScanError {
  rel_path: string;
  error: string;
}
