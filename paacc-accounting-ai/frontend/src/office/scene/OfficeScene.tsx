import { useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { OrthographicCamera, Vector3 } from "three";
import type { Department } from "../types";
import { OfficeContents } from "./OfficeContents";
import { fitZoom, roomCenter, sceneBounds } from "./layout";

export type ViewRequest =
  | { id: number; kind: "overview" }
  | { id: number; kind: "focus"; code: string }
  | { id: number; kind: "zoom"; factor: number }
  | { id: number; kind: "rotate"; angle: number };

/** The subset of OrbitControls the rig needs (avoids importing a transitive package's types). */
interface OrbitControlsImpl { target: Vector3; update(): void }

const DIST = 60, UP = new Vector3(0, 1, 0);

interface Anim { fromT: Vector3; toT: Vector3; fromP: Vector3; toP: Vector3; fromZ: number; toZ: number; t: number }

function CameraRig({ view, departments }: { view: ViewRequest; departments: Department[] }) {
  const { camera, size, invalidate } = useThree();
  const controls = useThree((s) => s.controls) as unknown as OrbitControlsImpl | null;
  const anim = useRef<Anim | null>(null);
  useEffect(() => {
    if (!controls) return;
    const cam = camera as OrthographicCamera;
    const fromT = controls.target.clone(), fromP = cam.position.clone();
    let toT = fromT.clone(), toZ = cam.zoom;
    const offset = fromP.clone().sub(fromT);
    if (view.kind === "overview") {
      const b = sceneBounds(departments.map((d) => d.layout));
      toT = new Vector3(...b.center); toZ = fitZoom(Math.max(b.width, b.depth), size, 1.15);
      offset.set(1, 1.1, 1);
    } else if (view.kind === "focus") {
      const d = departments.find((x) => x.code === view.code);
      if (!d) return;
      toT = new Vector3(...roomCenter(d.layout)); toZ = fitZoom(d.layout.w + d.layout.d, size, 1.15); // isometric footprint ≈ w + d
    } else if (view.kind === "zoom") {
      toZ = Math.min(150, Math.max(5, cam.zoom * view.factor));
    } else {
      offset.applyAxisAngle(UP, view.angle);
    }
    anim.current = { fromT, toT, fromP, toP: toT.clone().add(offset.setLength(DIST)), fromZ: cam.zoom, toZ, t: 0 };
    invalidate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.id, controls]);
  useFrame((_, delta) => {
    const a = anim.current;
    if (!a || !controls) return;
    a.t = Math.min(1, a.t + Math.min(delta, 1 / 30) / 0.6);
    const e = 1 - (1 - a.t) ** 3;
    const cam = camera as OrthographicCamera;
    cam.position.lerpVectors(a.fromP, a.toP, e);
    controls.target.lerpVectors(a.fromT, a.toT, e);
    cam.zoom = a.fromZ + (a.toZ - a.fromZ) * e;
    cam.updateProjectionMatrix();
    controls.update();
    if (a.t < 1) invalidate(); else anim.current = null;
  });
  return null;
}

export interface SceneProps {
  departments: Department[]; selected?: string; onSelect: (code: string) => void; view: ViewRequest;
}

export default function OfficeScene({ departments, selected, onSelect, view }: SceneProps) {
  // Continuous rendering only while the backend reports a working agent; otherwise render on demand.
  const anyWorking = useMemo(() => departments.some((d) => d.agents.some((a) => a.status === "working")), [departments]);
  return (
    <Canvas orthographic frameloop={anyWorking ? "always" : "demand"} dpr={[1, 2]}
      camera={{ position: [DIST * 0.55, DIST * 0.6, DIST * 0.55], zoom: 12, near: 0.1, far: 500 }}
      aria-label="Văn phòng 3D">
      <color attach="background" args={["#e9edf2"]} />
      <OfficeContents departments={departments} selected={selected} onSelect={onSelect} />
      <OrbitControls makeDefault enableDamping={false} minZoom={5} maxZoom={150} maxPolarAngle={Math.PI / 2.3} />
      <CameraRig view={view} departments={departments} />
    </Canvas>
  );
}
