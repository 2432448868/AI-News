export type Category = 'news' | 'projects' | 'skills' | 'models' | 'tips' | 'apps' | 'dev';
export interface Item {
  id: string;
  title: string;
  summary: string;
  url: string;
  sourceId: string;
  sourceName: string;
  categories: Category[];
  tags: string[];
  publishedAt: string | null;
  updatedAt: string | null;
  collectedAt: string;
  metricLabel: string | null;
  metricValue: number | null;
  /** Absent in static snapshots; the cloud API always emits it (possibly null). */
  metricPrev?: number | null;
  rankScore: number;
}
export interface Source {
  id: string;
  name: string;
  homepage: string;
  status: 'ok' | 'error';
  lastSuccessAt: string | null;
  itemCount: number;
  error: string | null;
}
export interface EditorNote {
  date: string;
  text: string;
}
export interface Feed {
  schemaVersion: 1;
  generatedAt: string;
  sources: Source[];
  items: Item[];
  /** Cloud-only; static snapshots predate it and simply render nothing. */
  editorNote?: EditorNote | null;
}
