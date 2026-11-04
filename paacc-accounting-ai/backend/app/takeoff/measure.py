"""Scale-based measurement helper. Refuses to run on an unconfirmed scale."""
from decimal import Decimal

from app.takeoff.engine import CalcError


def real_length_from_paper(paper_length: Decimal, scale_ratio: int, scale_confirmed: bool) -> Decimal:
    """paper_length in any unit -> real length in the SAME unit (ratio 100 means 1:100)."""
    if not scale_confirmed:
        raise CalcError("scale_unconfirmed", "Tỷ lệ bản vẽ chưa được người dùng xác nhận")
    if scale_ratio <= 0:
        raise CalcError("invalid_scale", "Tỷ lệ không hợp lệ")
    return paper_length * scale_ratio
