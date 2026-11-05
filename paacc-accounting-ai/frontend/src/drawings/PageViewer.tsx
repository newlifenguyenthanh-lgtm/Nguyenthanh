import { useEffect, useState } from "react";
import { apiBlob } from "../api";
import { GEO_COLOR } from "./GeometryPanel";
import type { GeometryPrim, Item, Page, TextBlock } from "./types";

export interface Link { key: string; from: [number, number]; to: [number, number]; color: string }
export interface Tag { key: string; at: [number, number]; text: string; color: string }

export const KIND_COLOR: Record<string, string> = {
  dimension: "#d9480f", count: "#e67700", spec: "#2b8a3e", symbol: "#5f3dc4", reference: "#1971c2",
  region: "#868e96", table: "#0c8599", text: "#adb5bd",
};

/** Rendered page with bounding boxes. bbox is in PDF points (displayed space) -> positioned in % of page size. */
export default function PageViewer({ drawingId, page, items, selectedId, onSelect, geometry = [], selectedGeo, onSelectGeo,
  texts = [], textColor, selectedText, onSelectText, links = [], tags = [] }:
  { drawingId: string; page: Page; items: Item[]; selectedId?: string; onSelect: (id: string) => void;
    geometry?: GeometryPrim[]; selectedGeo?: string; onSelectGeo?: (id: string) => void;
    /** Phase 5C overlay: text blocks, association lines (selection only) and measurement / conflict tags. */
    texts?: TextBlock[]; textColor?: (t: TextBlock) => string; selectedText?: string; onSelectText?: (id: string) => void;
    links?: Link[]; tags?: Tag[] }) {
  const [url, setUrl] = useState<string>("");
  const [err, setErr] = useState("");
  useEffect(() => {
    let revoke = "";
    setUrl(""); setErr("");
    apiBlob(`/drawings/${drawingId}/pages/${page.page_no}/image?dpi=110`)
      .then((b) => { revoke = URL.createObjectURL(b); setUrl(revoke); })
      .catch(() => setErr("Không tải được ảnh trang"));
    return () => { if (revoke) URL.revokeObjectURL(revoke); };
  }, [drawingId, page.page_no]);
  const { width_pt: W, height_pt: H } = page;
  return (
    <div className="page-view" style={{ aspectRatio: `${W} / ${H}` }} aria-label={`Trang ${page.page_no}`}>
      {url ? <img src={url} alt={`Trang ${page.page_no}`} /> : <p className="muted">{err || "Đang tải ảnh…"}</p>}
      {geometry.length > 0 && (
        <svg className="geo-layer" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-label="Lớp hình học vector">
          {geometry.map((g) => {
            const pts = g.points.map(([x, y]) => `${x},${y}`).join(" ");
            const sel = g.id === selectedGeo;
            const props = { "data-geo": g.id, onClick: () => onSelectGeo?.(g.id), stroke: sel ? "#e8590c" : GEO_COLOR[g.status] ?? "#1f6feb",
              strokeWidth: sel ? 3 : 1.5, vectorEffect: "non-scaling-stroke" as const, fill: g.kind === "fill_region" ? "#1f6feb22" : "none",
              strokeDasharray: g.status === "rejected" ? "4 3" : undefined };
            return g.closed ? <polygon key={g.id} {...props} points={pts} /> : <polyline key={g.id} {...props} points={pts} />;
          })}
        </svg>
      )}
      {(texts.length > 0 || links.length > 0 || tags.length > 0) && (
        <svg className="assoc-layer" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-label="Lớp chữ và liên kết">
          {texts.map((t) => {
            const [x0, y0, x1, y1] = t.bbox;
            const sel = t.id === selectedText;
            return <rect key={t.id} data-text={t.id} x={x0} y={y0} width={Math.max(1, x1 - x0)} height={Math.max(1, y1 - y0)}
              fill={sel ? "#ffd43b55" : "transparent"} stroke={textColor?.(t) ?? "#adb5bd"} strokeWidth={sel ? 2.5 : 1}
              vectorEffect="non-scaling-stroke" onClick={() => onSelectText?.(t.id)}><title>{t.original_text}</title></rect>;
          })}
          {links.map((l) => <line key={l.key} data-link={l.key} x1={l.from[0]} y1={l.from[1]} x2={l.to[0]} y2={l.to[1]}
            stroke={l.color} strokeWidth={2} strokeDasharray="5 3" vectorEffect="non-scaling-stroke" />)}
          {tags.map((t) => <text key={t.key} data-tag={t.key} x={t.at[0]} y={t.at[1]} fill={t.color} fontSize={9}>{t.text}</text>)}
        </svg>
      )}
      {items.map((it) => {
        const [x0, y0, x1, y1] = it.bbox;
        const sel = it.id === selectedId;
        return (
          <button key={it.id} className={`bbox${sel ? " sel" : ""}`} title={`${it.kind}: ${it.text}`} aria-label={`Vị trí ${it.text}`}
            onClick={() => onSelect(it.id)}
            style={{ left: `${(x0 / W) * 100}%`, top: `${(y0 / H) * 100}%`, width: `${Math.max(0.3, ((x1 - x0) / W) * 100)}%`,
              height: `${Math.max(0.3, ((y1 - y0) / H) * 100)}%`, borderColor: KIND_COLOR[it.kind] ?? "#333" }} />
        );
      })}
    </div>
  );
}
