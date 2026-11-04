from dataclasses import dataclass

from app.ai.base import LLMProvider, Message


@dataclass(frozen=True)
class AgentSpec:
    key: str
    title: str
    tax_domain: bool  # tax agents stay disabled until rules are verified
    department: str  # owning department code (see app/office/catalog.py)
    title_vi: str = ""


# 14 design agents (docs/PHASE1_DESIGN.md) + accounting/tax sub-agents. Each belongs to exactly one department.
AGENTS: dict[str, AgentSpec] = {a.key: a for a in [
    AgentSpec("supervisor", "Supervisor", False, "board", "Điều phối tổng"),
    AgentSpec("reporting", "Reporting", False, "board", "Lập báo cáo"),
    AgentSpec("document", "Document", False, "bidding", "Xử lý hồ sơ"),
    AgentSpec("quotation", "Quotation intake", False, "bidding", "Tiếp nhận báo giá"),
    AgentSpec("pdf_drawing", "PDF drawing", False, "engineering_qs", "Phân tích bản vẽ PDF"),
    AgentSpec("quantity_surveyor", "Quantity surveyor", False, "engineering_qs", "Bóc tách khối lượng"),
    AgentSpec("cad", "AutoCAD", False, "cad_design", "AutoCAD"),
    AgentSpec("estimation", "Estimation", False, "estimation", "Lập dự toán"),
    AgentSpec("contracts", "Contracts", False, "contract_payment", "Hợp đồng"),
    AgentSpec("payments", "Payments", False, "contract_payment", "Thanh toán"),
    AgentSpec("general_accounting", "General accounting", False, "accounting_finance", "Kế toán tổng hợp"),
    AgentSpec("finance", "Finance", False, "accounting_finance", "Tài chính"),
    AgentSpec("vat", "Value-added tax", True, "accounting_finance", "Thuế GTGT"),
    AgentSpec("cit", "Corporate income tax", True, "accounting_finance", "Thuế TNDN"),
    AgentSpec("pit", "Personal income tax", True, "accounting_finance", "Thuế TNCN"),
    AgentSpec("inventory", "Inventory", False, "procurement_inventory", "Kho vật tư"),
    AgentSpec("construction", "Construction accounting", False, "construction", "Thi công"),
    AgentSpec("audit", "Audit", False, "internal_audit", "Kiểm tra dữ liệu"),
]}


def run_agent(key: str, prompt: str, provider: LLMProvider) -> dict:
    spec = AGENTS[key]
    if spec.tax_domain:
        return {"agent": key, "status": "not_implemented",
                "detail": "Tax rules are not yet verified against official sources."}
    resp = provider.complete([
        Message("system", f"You are the PAACC {spec.title} assistant. Do not state tax rules you cannot cite."),
        Message("user", prompt),
    ])
    return {"agent": key, "status": "ok", "provider": resp.provider, "model": resp.model, "output": resp.text}
