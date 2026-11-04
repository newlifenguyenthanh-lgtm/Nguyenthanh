import { describe, expect, it } from "vitest";
import { STATUS_META, statusMeta } from "./status";

describe("status mapping", () => {
  it("has Vietnamese labels and distinct colours for all five statuses", () => {
    expect(Object.keys(STATUS_META)).toEqual(["idle", "working", "waiting_approval", "completed", "error"]);
    expect(new Set(Object.values(STATUS_META).map((m) => m.color)).size).toBe(5);
    expect(statusMeta("waiting_approval").label).toBe("Chờ phê duyệt");
    expect(statusMeta("error").label).toBe("Lỗi");
  });
  it("falls back for unknown statuses", () => expect(statusMeta("zzz").label).toBe("zzz"));
});
