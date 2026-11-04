import { useMemo } from "react";
import type { Department } from "../types";
import { DepartmentRoom } from "./DepartmentRoom";
import { sceneBounds } from "./layout";

export interface ContentsProps {
  departments: Department[]; selected?: string; onSelect: (code: string) => void; showLabels?: boolean;
}

/** Pure scene graph (no camera/controls) so it can be unit-tested without WebGL. */
export function OfficeContents({ departments, selected, onSelect, showLabels = true }: ContentsProps) {
  const b = useMemo(() => sceneBounds(departments.map((d) => d.layout)), [departments]);
  return (
    <group name="office">
      <ambientLight intensity={0.7} />
      <directionalLight position={[20, 30, 15]} intensity={1.1} />
      <mesh name="ground" position={[b.center[0], -0.01, b.center[2]]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[b.width + 6, b.depth + 6]} />
        <meshStandardMaterial color="#f1f3f6" />
      </mesh>
      {departments.map((d) => (
        <DepartmentRoom key={d.code} dept={d} selected={d.code === selected} onSelect={onSelect} showLabels={showLabels} />
      ))}
    </group>
  );
}
