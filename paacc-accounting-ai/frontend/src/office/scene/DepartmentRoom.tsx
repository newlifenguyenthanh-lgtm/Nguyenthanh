import { useState } from "react";
import type { ThreeEvent } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { statusMeta } from "../status";
import type { Department } from "../types";
import { AgentWorkstation } from "./AgentWorkstation";
import { deskPositions } from "./layout";

const WALL_H = 1.4, WALL_T = 0.12;

export interface RoomProps {
  dept: Department; selected: boolean; onSelect: (code: string) => void; showLabels?: boolean;
}

export function DepartmentRoom({ dept, selected, onSelect, showLabels = true }: RoomProps) {
  const [hover, setHover] = useState(false);
  const { x, z, w, d } = dept.layout;
  const desks = deskPositions(dept.layout, dept.agents.length + dept.employees.length);
  const lamp = statusMeta(dept.status).color;
  const click = (e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onSelect(dept.code); };
  return (
    <group position={[x, 0, z]} name={`room-${dept.code}`} userData={{ code: dept.code, status: dept.status }}>
      <mesh name={`floor-${dept.code}`} position={[0, 0.05, 0]} onClick={click}
        onPointerOver={(e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { setHover(false); document.body.style.cursor = ""; }}>
        <boxGeometry args={[w, 0.1, d]} />
        <meshStandardMaterial color={dept.color} emissive={dept.color} emissiveIntensity={selected ? 0.55 : hover ? 0.3 : 0.05} />
      </mesh>
      <mesh position={[0, WALL_H / 2, -d / 2]} onClick={click}><boxGeometry args={[w, WALL_H, WALL_T]} /><meshStandardMaterial color="#e8ebf0" /></mesh>
      <mesh position={[-w / 2, WALL_H / 2, 0]} onClick={click}><boxGeometry args={[WALL_T, WALL_H, d]} /><meshStandardMaterial color="#dde1e7" /></mesh>
      <mesh name={`lamp-${dept.code}`} position={[w / 2 - 0.5, 1.7, -d / 2 + 0.5]} userData={{ status: dept.status }}>
        <sphereGeometry args={[0.32, 16, 16]} />
        <meshStandardMaterial color={lamp} emissive={lamp} emissiveIntensity={0.8} />
      </mesh>
      {dept.agents.map((a, i) => (
        <AgentWorkstation key={a.key} id={a.key} position={desks[i]} kind="agent" status={a.status} name={a.name_vi} showLabel={showLabels && selected} />
      ))}
      {dept.employees.map((e, i) => (
        <AgentWorkstation key={e.user_id} id={e.user_id} position={desks[dept.agents.length + i]} kind="human" name={e.name} showLabel={showLabels && selected} />
      ))}
      {showLabels && (
        <Html position={[0, WALL_H + 0.9, -d / 2]} center zIndexRange={[20, 0]}>
          <button className="room-label" onClick={() => onSelect(dept.code)} style={{ borderColor: lamp }}>
            <span className="dot" style={{ background: lamp }} />{dept.name_vi}
          </button>
        </Html>
      )}
    </group>
  );
}
