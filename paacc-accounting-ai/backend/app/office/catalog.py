"""Default departments of a construction company and their link to software modules.
Layout is only the initial seed; it is stored per company in `departments.layout` and can be changed."""

ROOM_W, ROOM_D, GAP = 8.0, 6.0, 1.5

# code, Vietnamese name, colour, module route, module status, roadmap phase, related document kinds
DEFAULT_DEPARTMENTS: list[tuple[str, str, str, str | None, str, int, tuple[str, ...]]] = [
    ("board", "Ban Giám đốc", "#8a6d3b", "/dashboard", "available", 2, ()),
    ("bidding", "Phòng Đấu thầu", "#3b6e8a", "/documents?kind=quote", "partial", 6, ("quote", "email")),
    ("engineering_qs", "Phòng Kỹ thuật & Bóc tách khối lượng", "#3b8a5a", "/drawings", "partial", 4, ("drawing", "boq")),
    ("cad_design", "Phòng AutoCAD & Thiết kế", "#5a3b8a", None, "planned", 5, ("drawing",)),
    ("estimation", "Phòng Dự toán", "#8a3b6e", None, "planned", 6, ("boq", "quote")),
    ("contract_payment", "Phòng Hợp đồng & Thanh toán", "#8a5a3b", "/contracts", "partial", 7, ("contract",)),
    ("accounting_finance", "Phòng Kế toán & Tài chính", "#3b8a85", None, "planned", 10, ()),
    ("procurement_inventory", "Phòng Vật tư & Kho", "#6e8a3b", None, "planned", 8, ()),
    ("construction", "Phòng Quản lý Thi công", "#8a3b3b", "/projects", "partial", 9, ()),
    ("internal_audit", "Phòng Kiểm toán Nội bộ", "#4a4a6a", "/audit", "partial", 11, ()),
]

CATALOG = {d[0]: {"route": d[3], "module_status": d[4], "phase": d[5], "doc_kinds": d[6]} for d in DEFAULT_DEPARTMENTS}


def default_layout(index: int, cols: int = 5) -> dict:
    col, row = index % cols, index // cols
    width = cols * ROOM_W + (cols - 1) * GAP
    return {"x": round(col * (ROOM_W + GAP) - width / 2 + ROOM_W / 2, 3),
            "z": round(row * (ROOM_D + GAP) - (ROOM_D + GAP) / 2, 3), "w": ROOM_W, "d": ROOM_D}
