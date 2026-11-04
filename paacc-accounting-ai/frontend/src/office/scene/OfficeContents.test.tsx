import ReactThreeTestRenderer from "@react-three/test-renderer";
import { describe, expect, it, vi } from "vitest";
import { agent, dept, tenDepartments } from "../testData";
import { AVATAR_Y } from "./AgentWorkstation";
import { OfficeContents } from "./OfficeContents";

function data() {
  const deps = tenDepartments();
  deps[2] = dept("engineering_qs", 2, { status: "working",
    agents: [agent("pdf_drawing", "working"), agent("quantity_surveyor", "idle")],
    employees: [{ user_id: "u1", name: "A", role: "viewer", job_title: "" }] });
  deps[9] = dept("internal_audit", 9, { status: "error", agents: [agent("audit", "error")] });
  return deps;
}

describe("3D office scene graph", () => {
  it("renders one clickable room per department and one workstation per agent/employee", async () => {
    const onSelect = vi.fn();
    const r = await ReactThreeTestRenderer.create(<OfficeContents departments={data()} onSelect={onSelect} showLabels={false} />);
    const rooms = r.scene.findAll((n) => typeof n.props.name === "string" && n.props.name.startsWith("room-"));
    expect(rooms).toHaveLength(10);
    const ws = r.scene.findAll((n) => typeof n.props.name === "string" && n.props.name.startsWith("ws-"));
    expect(ws).toHaveLength(9 + 2 + 1); // 9 rooms with 1 agent, engineering with 2 agents + 1 employee
    await r.fireEvent(r.scene.findByProps({ name: "floor-cad_design" }), "onClick", { stopPropagation: () => {} });
    expect(onSelect).toHaveBeenCalledWith("cad_design");
  });

  it("status lamps and avatars use the backend status colours", async () => {
    const r = await ReactThreeTestRenderer.create(<OfficeContents departments={data()} onSelect={() => {}} showLabels={false} />);
    const lamp = r.scene.findByProps({ name: "lamp-internal_audit" });
    expect(lamp.props.userData.status).toBe("error");
    const mat = lamp.allChildren.find((c) => c.type === "MeshStandardMaterial")!;
    expect(mat.props.color).toBe("#eb5757");
  });

  it("animates an avatar only while its agent is working", async () => {
    const r = await ReactThreeTestRenderer.create(<OfficeContents departments={data()} onSelect={() => {}} showLabels={false} />);
    await r.advanceFrames(5, 0.1);
    const working = r.scene.findByProps({ name: "avatar-pdf_drawing" }).instance;
    const idle = r.scene.findByProps({ name: "avatar-quantity_surveyor" }).instance;
    expect(idle.position.y).toBe(AVATAR_Y);
    expect(working.position.y).not.toBe(AVATAR_Y);
  });
});
