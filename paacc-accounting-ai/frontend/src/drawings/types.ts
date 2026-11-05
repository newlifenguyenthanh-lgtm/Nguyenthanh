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
export interface Component {
  id: string; drawing_id: string; page_no: number; component_type: string; component_subtype: string | null; name: string;
  description: string; specification: string; material: string; bbox: [number, number, number, number]; centroid: [number, number];
  view_context: string; recognition_method: string; recognition_rule: string; recognition_confidence: number; confidence_band: string;
  scores: Record<string, number | null>; status: string; ambiguity_reason: string; rejection_reason: string; parent_id: string | null;
  representation_of_id: string | null; repeat_group_id: string | null; dimensions: Record<string, unknown>;
  source_text_ids: string[]; source_geometry_ids: string[]; source_measurement_ids: string[]; source_association_ids: string[];
  downstream_allowed: boolean;
}
export interface ComponentEvidence {
  scores: Record<string, number | null>; overall: number; band: string; rule: string;
  measurements: { id: string; kind: string; value_real: string | null; real_unit: string | null; value_paper: string; paper_unit: string }[];
  detail: { reasons?: string[]; comparisons?: { stated: string; measured: string; difference: string; unit: string }[]; conflicts?: string[];
    ambiguous?: string[]; alternatives?: { type: string; overall?: number }[] };
  repeat_group: { pattern_status: string; gaps_pt: number[]; start: number[]; end: number[] } | null;
  relations: { from: string; to: string; type: string }[];
}
export interface ComponentTypeDef { code: string; group: string; name_vi: string; active: boolean }
export interface QuantityResult {
  id: string; component_id: string; drawing_id: string; page_no?: number; component_type?: string; component_description?: string;
  quantity_type: string; raw_value: string | null; quantity_value: string | null; unit: string; precision: number; rounding_rule: string;
  calculation_method: string; rule_code: string | null; formula: string; formula_trace: string; parameters: Record<string, Record<string, string>>;
  input_measurement_ids: string[]; status: string; reason: string; version: number;
  provenance?: {
    component: { id: string; type: string; status: string; description: string; specification: string };
    measurements: { id: string; kind: string; value_real: string | null; real_unit: string | null; status: string; geometry_ids: string[] }[];
    geometry_ids: string[]; texts: { id: string; original_text: string }[]; association_ids: string[];
    drawing: { page_no: number }; audit: { action: string; user: string | null; at: string | null }[];
  };
}
export interface QuantityRunSummary {
  components_scanned: number; not_confirmed: number; representations_skipped: number; rules_matched: number; calculated: number;
  requires_review: number; blocked: number; skipped_missing_parameter: number; skipped_missing_measurement: number;
}
