import type { Layout } from "../types";

export type Vec3 = [number, number, number];

export function roomCenter(l: Layout): Vec3 {
  return [l.x, 0, l.z];
}

/** Desk slots inside a room (local coordinates), row-major, keeping a margin from the walls. */
export function deskPositions(l: Layout, n: number, margin = 1.2): Vec3[] {
  if (n <= 0) return [];
  const usableW = l.w - 2 * margin, usableD = l.d - 2 * margin;
  const cols = Math.max(1, Math.min(n, Math.floor(usableW / 1.6) + 1));
  const rows = Math.ceil(n / cols);
  const dx = cols > 1 ? usableW / (cols - 1) : 0, dz = rows > 1 ? usableD / (rows - 1) : 0;
  return Array.from({ length: n }, (_, i) => {
    const c = i % cols, r = Math.floor(i / cols);
    const x = cols > 1 ? -usableW / 2 + c * dx : 0;
    const z = rows > 1 ? -usableD / 2 + r * dz : 0;
    return [round(x), 0, round(z)] as Vec3;
  });
}

export function sceneBounds(ls: Layout[]): { center: Vec3; width: number; depth: number } {
  if (ls.length === 0) return { center: [0, 0, 0], width: 10, depth: 10 };
  const minX = Math.min(...ls.map((l) => l.x - l.w / 2)), maxX = Math.max(...ls.map((l) => l.x + l.w / 2));
  const minZ = Math.min(...ls.map((l) => l.z - l.d / 2)), maxZ = Math.max(...ls.map((l) => l.z + l.d / 2));
  return { center: [(minX + maxX) / 2, 0, (minZ + maxZ) / 2], width: maxX - minX, depth: maxZ - minZ };
}

/** Orthographic zoom (pixels per world unit) that fits an extent into the viewport. */
export function fitZoom(extent: number, viewport: { width: number; height: number }, padding = 1.3): number {
  return Math.max(2, Math.min(viewport.width, viewport.height) / (extent * padding));
}

function round(v: number) { return Math.round(v * 1000) / 1000; }
