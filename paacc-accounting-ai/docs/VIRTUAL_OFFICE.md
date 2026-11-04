# PAACC 3D Virtual Office – Architecture & Integration Plan

The 3D office is a navigation and monitoring layer over real data. It does not hold business logic; every
status, count and name it shows comes from the backend. If a module is not built yet, the office says so
("Module chưa phát triển") instead of showing invented activity.

## 1. Backend

### Data model (migration `0002_virtual_office`)
| Table | Purpose |
|---|---|
| `departments` | Per-company department (code, Vietnamese name, sort order, isometric layout `{x,z,w,d}`, colour). Seeded with the 10 standard departments on first access. Layout is stored data, so it can be changed without code. |
| `department_members` | user ↔ department with job title. Users are not duplicated. |
| `ai_tasks` | One row per AI agent task: agent, department, title, status (`queued`, `running`, `waiting_approval`, `completed`, `error`, `cancelled`), project/entity link, error, approver, timestamps. |

### Agents
A single registry in `app/agents/registry.py` covers the 14 Phase 1 design agents plus the 4 accounting/tax sub-agents. Each agent belongs to exactly one department. Tax agents stay disabled. Running an agent (`POST /agents/{key}/run`) now records an `ai_tasks` row (`running` → `completed`/`error`), so the office shows real activity.

### Status derivation (pure functions, `app/office/status.py`)
- Agent status, from its tasks: `error` if the most recent finished task failed (cleared by a later success), else `waiting_approval` if any task awaits approval, else `working` if any task is queued or running, else `completed` if a task finished in the last 24 h, else `idle`.
- Department status is the most urgent of its agents' statuses and its real business approvals, in the order error > waiting_approval > working > completed > idle.
- Real business approvals counted today: draft contract appendices (Contract & Payment). BOQ approvals appear as `waiting_approval` tasks of the Quantity Surveyor agent (Phase 4D), approved via the BOQ workflow (four-eyes rule).
- Engineering & QS metrics come from the drawings and BOQ tables: drawings processing, processed or failed; draft BOQs; BOQs awaiting approval; approved BOQs.

### Endpoints (`office:read` for all roles)
- `GET /office/overview`: departments with layout, status, agents (with status and current task), employees, task counts, pending approvals, real metrics and module availability.
- `GET /office/departments/{code}`: the same plus recent tasks, recent documents of related kinds, and metrics.
- `POST /office/departments/{code}/members`: assign a user (`office:manage`).
- `POST /ai-tasks`, `POST /ai-tasks/{id}/status`: create a task or move it through the state machine (`ai_task:write`). `POST /ai-tasks/{id}/approve|reject` needs `ai_task:approve`.

Metrics are counted only from existing tables: projects, documents by kind, contracts, pending appendices, tasks. Departments without a module return `module_status: "planned"` and the phase number.

## 2. Frontend

```
src/
  router (react-router)      /dashboard (2D) · /office (3D) · /office/:code · /projects · /documents · /contracts · /modules/:code
  office/
    useOfficeData.ts         fetch + 10 s polling of /office/overview (real status)
    status.ts                status → colour/label (Vietnamese), shared by 2D and 3D
    OfficePage.tsx           toolbar (overview, 2D/3D toggle, department picker) + lazy 3D scene + side panel
    DepartmentPanel.tsx      employees, agents, tasks, metrics, "Mở module", reports/documents links
    Office2D.tsx             conventional dashboard grid (same data; WebGL fallback)
    scene/  (lazy chunk)
      OfficeScene.tsx        <Canvas> orthographic isometric camera, OrbitControls (zoom/rotate/pan limits), camera focus
      DepartmentRoom.tsx     floor, walls, sign, status lamp; click → select/enter
      AgentWorkstation.tsx   desk and avatar coloured by the agent's real status; pulses only while the backend says `working`
      layout.ts              pure layout helpers (room centre, desk positions), unit-tested
```

Performance:
- three.js, R3F and drei sit in a separate chunk loaded only on `/office` (`React.lazy`).
- `frameloop="demand"` renders only on interaction or camera moves; continuous rendering runs only while some agent is `working`.
- Geometries and materials are shared, `dpr` is capped at 2, and there are no textures or external models.

On phones the panel stacks below the canvas. Without WebGL the page falls back to the 2D view.

## 3. Navigation
- Overview: resets the camera.
- Department picker: a dropdown, or click a room. Clicking a room flies the camera into it and opens the panel.
- Zoom and rotate: mouse, touch, or the toolbar buttons.
- "Bảng điều khiển": returns to the main dashboard.
- The 2D/3D toggle remembers your choice for this browser session.

## 4. Tests
- Backend: status derivation units, seeding, overview metrics against real rows, task state machine, approval permissions, agent run → task, tenant isolation.
- Frontend (vitest + Testing Library + R3F test renderer): status mapping, layout helpers, 2D dashboard rendering and navigation, and 3D scene room/workstation counts with a click on a room calling the select handler.
- Manual: headless Chromium screenshot of `/office`. This needs WebGL via SwiftShader, so it is a smoke check, not part of CI.

## 5. Not in this prototype
- Avatars are simple primitives, not character models.
- No live push: the office polls every 10 s. WebSockets later.
- Metrics for planned modules (CAD, estimation, inventory, site, accounting) are unavailable until those modules exist. Engineering & QS links to `/drawings`.
- No per-department reports beyond links to documents and the audit log.
