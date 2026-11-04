export interface Flag { code: string; severity: "blocking" | "warning" | "info"; message: string; other_id?: string }
export interface Input { value: string | null; origin: string; source_item_id: string | null; note?: string; previous_value?: string | null; cell?: number[]; raw?: string }
export interface BoqItem {
  id: string; item_no: number; category: string; description: string; spec: string; module: string | null;
  inputs: Record<string, Input>; unit_system: string | null; stated_unit: string | null; waste_factor: string; waste_override: string | null;
  quantity: string | null; unit: string | null; formula_text: string; origin: string; review_status: "pending" | "accepted" | "rejected";
  flags: Flag[]; notes: string; drawing_id: string | null; page_no: number | null; bbox: number[] | null; source_item_ids: string[];
  version: number; has_blocking: boolean;
}
export interface Total { category: string; unit: string | null; accepted: string; all_active: string; items: number }
export interface Boq {
  id: string; title: string; version_no: number; previous_boq_id: string | null; status: string; project_id: string | null;
  rules: { decimals: number; steel_density: string; waste: Record<string, string> };
  submitted_at: string | null; decided_at: string | null; decision_note: string; created_at: string | null;
  sources: { drawing_id: string; document_version_id: string }[]; item_count: number;
  review_counts: Record<string, number>; blocking_count: number; totals: Total[]; items?: BoqItem[];
}
export interface ModuleField { name: string; label_vi: string; kind: string }
export interface ModuleSpec { key: string; title_vi: string; category: string; out_unit: string; dimensional: boolean; fields: ModuleField[] }
export interface HistoryRow { version: number; action: string; reason: string; at: string | null; quantity: string | null; review_status: string; inputs: Record<string, string | null> }
export interface BoqExport { id: string; boq_version_no: number; boq_status: string; filename: string; sha256: string; size_bytes: number; item_count: number; created_at: string | null }
