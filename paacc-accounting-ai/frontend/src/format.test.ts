import { describe, expect, it } from "vitest";
import { formatDateVN, formatVND } from "./format";

describe("format", () => {
  it("formats VND with Vietnamese grouping", () => {
    expect(formatVND("1150000000")).toMatch(/^1\.150\.000\.000\s*₫$/);
  });
  it("handles invalid numbers", () => expect(formatVND("abc")).toBe("—"));
  it("formats dates dd/mm/yyyy", () => {
    expect(formatDateVN("2026-11-04")).toBe("04/11/2026");
    expect(formatDateVN(null)).toBe("—");
  });
});
