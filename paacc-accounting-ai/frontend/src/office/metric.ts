import { formatVND } from "../format";
import type { Metric } from "./types";

/** Display-only: money metrics (key ends in "_value") are formatted as VND; counts are shown as-is. */
export function metricText(m: Metric): string {
  return m.key.endsWith("_value") ? formatVND(m.value) : m.value;
}
