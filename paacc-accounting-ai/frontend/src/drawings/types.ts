export interface DrawingSummary {
  id: string; document_id: string; version_no: number; filename: string; status: string; page_count: number;
  findings: Finding[]; error_code: string; error_message: string; duplicate_of_drawing_id: string | null;
  processed_at: string | null; project_id: string | null;
}
export interface Finding { type: string; severity: string; [k: string]: unknown }
export interface Candidate { ratio?: number; unit?: string; labeled?: boolean; item_id: string; raw: string; confidence: number }
export interface Classified { value: string; basis: string; confidence: number }
export interface Page {
  page_no: number; width_pt: number; height_pt: number; rotation: number; kind: string; text_chars: number;
  ocr_used: boolean; ocr_engine: string | null; ocr_mean_confidence: number | null; warnings: string[];
  drawing_number: string | null; title: string | null; revision: string | null;
  disciplines: Classified[] | null; view_types: Classified[] | null;
  scale_candidates: Candidate[] | null; scale_status: string; scale_ratio: number | null;
  units_candidates: Candidate[] | null; units_status: string; units: string | null; calibrated_at: string | null;
  geometry_status?: string; geometry_stats?: { by_kind?: Record<string, number> } | null;
}
export interface DrawingDetail extends DrawingSummary { document_title: string; pages: Page[]; item_counts: Record<string, number> }
export interface Item {
  id: string; page_no: number; kind: string; text: string; bbox: [number, number, number, number];
  source: string; confidence: number | null; data: Record<string, unknown> & { flags?: string[] };
}
export interface GeometryPrim {
  id: string; page_no: number; kind: string; points: [string, string][]; closed: boolean; bbox: number[];
  length_pt: string | null; area_pt2: string | null; stroke_width: number | null; derived_from: string | null;
  approximate: boolean; flags: string[]; duplicate_of: string | null; status: string; review_note: string;
  layer: string | null; source: { path_index: number; item_index: number };
  length_paper_mm?: string; length_real_m?: string | null; real_basis?: string;
}
export interface TextBlock {
  id: string; page_no: number; extracted_item_id: string; original_text: string; normalized_text: string;
  bbox: [number, number, number, number]; center: [number, number]; rotation: number; font_size: number | null; font_name: string | null;
  source: string; confidence: number | null; text_type: string; values: Record<string, unknown>; flags: string[];
  encoding: { encoding?: string; confidence?: number } | null; repeat_count: number;
}
export interface Association {
  id: string; drawing_id: string; page_no: number; text_block_id: string; geometry_id: string; association_type: string; rank: number;
  distance: number | null; angle_difference: number | null; overlap_ratio: number | null; orientation_match: boolean;
  semantic_match: number | null; relation: string | null; components: Record<string, number>; confidence: number; status: string;
  reason: string; origin: string; duplicate_of: string | null; measurement_id: string | null; text_value: string | null;
  measured_value: string | null; difference: string | null; unit: string | null;
  history: { old_geometry_id: string; new_geometry_id: string; reason: string; user: string; timestamp: string }[];
  decided_by: string | null; decided_at: string | null;
}
