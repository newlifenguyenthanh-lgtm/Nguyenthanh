import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { BoxGeometry, CapsuleGeometry, Mesh, SphereGeometry } from "three";
import { statusMeta } from "../status";
import type { Vec3 } from "./layout";

// Shared geometries (created once for all workstations).
const DESK = new BoxGeometry(1.2, 0.08, 0.7);
const LEG = new BoxGeometry(1.1, 0.7, 0.6);
const MONITOR = new BoxGeometry(0.6, 0.38, 0.05);
const BODY = new CapsuleGeometry(0.18, 0.35, 4, 8);
const HEAD = new SphereGeometry(0.16, 12, 12);
export const AVATAR_Y = 0.75;

export interface WorkstationProps {
  id: string; position: Vec3; kind: "agent" | "human"; status?: string; name: string; showLabel?: boolean;
}

/** Desk + avatar. Agent colour = real backend status; the avatar moves ONLY while the backend reports "working". */
export function AgentWorkstation({ id, position, kind, status = "idle", name, showLabel }: WorkstationProps) {
  const avatar = useRef<Mesh>(null);
  const phase = useRef(0);
  const working = kind === "agent" && status === "working";
  useFrame((_, delta) => {
    if (!avatar.current) return;
    if (working) {
      phase.current += delta;
      avatar.current.position.y = AVATAR_Y + Math.sin(phase.current * 4) * 0.08;
    } else if (avatar.current.position.y !== AVATAR_Y) {
      avatar.current.position.y = AVATAR_Y; // stop exactly when the backend says the work ended
    }
  });
  const color = kind === "agent" ? statusMeta(status).color : "#d9b48f";
  return (
    <group position={position} name={`ws-${id}`} userData={{ kind, status }}>
      <mesh geometry={LEG} position={[0, 0.35, -0.2]}><meshStandardMaterial color="#c9ced6" /></mesh>
      <mesh geometry={DESK} position={[0, 0.72, -0.2]}><meshStandardMaterial color="#8d6e52" /></mesh>
      <mesh geometry={MONITOR} position={[0, 1.0, -0.45]}>
        <meshStandardMaterial color="#222" emissive={kind === "agent" ? color : "#334"} emissiveIntensity={kind === "agent" ? 0.6 : 0.2} />
      </mesh>
      <mesh ref={avatar} name={`avatar-${id}`} geometry={BODY} position={[0, AVATAR_Y, 0.35]}>
        <meshStandardMaterial color={color} />
      </mesh>
      {kind === "human" && <mesh geometry={HEAD} position={[0, AVATAR_Y + 0.45, 0.35]}><meshStandardMaterial color="#e8c9a6" /></mesh>}
      {kind === "agent" && <mesh geometry={HEAD} position={[0, AVATAR_Y + 0.45, 0.35]} scale={[1, 0.8, 1]}><meshStandardMaterial color="#dfe6ee" metalness={0.4} /></mesh>}
      {showLabel && (
        <Html position={[0, 1.7, 0.35]} center distanceFactor={undefined} zIndexRange={[10, 0]}>
          <div className="ws-label">{kind === "agent" ? "🤖 " : ""}{name}{kind === "agent" ? ` · ${statusMeta(status).label}` : ""}</div>
        </Html>
      )}
    </group>
  );
}
