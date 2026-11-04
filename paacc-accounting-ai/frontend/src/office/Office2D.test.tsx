import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Office2D from "./Office2D";
import { agent, dept, tenDepartments } from "./testData";

describe("2D dashboard", () => {
  it("renders every department with its real status and counts", () => {
    const deps = tenDepartments();
    deps[5] = dept("contract_payment", 5, { status: "waiting_approval", pending_business_approvals: 2,
      metrics: [{ key: "contracts", label_vi: "Số hợp đồng", value: "3" },
        { key: "outbound_original_value", label_vi: "Giá trị", value: "2500000000.00" }] });
    deps[1] = dept("bidding", 1, { status: "working", agents: [agent("quotation", "working")], task_counts: { running: 1 } });
    render(<Office2D departments={deps} onSelect={() => {}} />);
    expect(screen.getAllByRole("button")).toHaveLength(10);
    const card = screen.getByLabelText("Phòng ban Phòng contract_payment");
    expect(card.textContent).toContain("Chờ phê duyệt");
    expect(card.textContent).toContain("Chờ duyệt: 2");
    expect(card.textContent).toContain("Số hợp đồng3");
    expect(card.textContent).toMatch(/2\.500\.000\.000\s*₫/);
    expect(screen.getByLabelText("Phòng ban Phòng bidding").textContent).toContain("Đang xử lý: 1");
  });
  it("selects a department on click", () => {
    const onSelect = vi.fn();
    render(<Office2D departments={tenDepartments()} onSelect={onSelect} />);
    fireEvent.click(screen.getByLabelText("Phòng ban Phòng estimation"));
    expect(onSelect).toHaveBeenCalledWith("estimation");
  });
});
