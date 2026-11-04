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
}
export interface DrawingDetail extends DrawingSummary { document_title: string; pages: Page[]; item_counts: Record<string, number> }
export interface Item {
  id: string; page_no: number; kind: string; text: string; bbox: [number, number, number, number];
  source: string; confidence: number | null; data: Record<string, unknown> & { flags?: string[] };
}
