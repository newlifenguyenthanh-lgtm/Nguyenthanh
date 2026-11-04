import { describe, expect, it } from "vitest";
import { deskPositions, fitZoom, roomCenter, sceneBounds } from "./layout";

const room = { x: 10, z: -3, w: 8, d: 6 };

describe("layout helpers", () => {
  it("room centre", () => expect(roomCenter(room)).toEqual([10, 0, -3]));
  it.each([0, 1, 2, 5, 9])("places %i desks inside the room without overlap", (n) => {
    const ps = deskPositions(room, n);
    expect(ps).toHaveLength(n);
    for (const [x, , z] of ps) {
      expect(Math.abs(x)).toBeLessThanOrEqual(room.w / 2);
      expect(Math.abs(z)).toBeLessThanOrEqual(room.d / 2);
    }
    expect(new Set(ps.map((p) => p.join(","))).size).toBe(n);
  });
  it("scene bounds", () => {
    const b = sceneBounds([room, { x: -10, z: 3, w: 8, d: 6 }]);
    expect(b).toEqual({ center: [0, 0, 0], width: 28, depth: 12 });
    expect(sceneBounds([]).width).toBe(10);
  });
  it("fit zoom shrinks for larger extents and has a floor", () => {
    expect(fitZoom(10, { width: 800, height: 600 })).toBeGreaterThan(fitZoom(40, { width: 800, height: 600 }));
    expect(fitZoom(1e6, { width: 800, height: 600 })).toBe(2);
  });
});
