"""factory.local.yaml 덮어쓰기 테스트. 실행: .venv/bin/python -I tests/test_local_config.py"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.pop("FACTORY_IGNORE_LOCAL", None)
import chat as C  # noqa: E402
import factory as F  # noqa: E402

A = "100%조립요청"
with tempfile.TemporaryDirectory() as d:
    y = Path(d) / "factory.yaml"
    shutil.copy(ROOT / "config" / "factory.yaml", y)
    sample = F.load_cfg(y)
    assert F.local_path(y).name == "factory.local.yaml"

    # 로컬 파일이 없으면 샘플 그대로
    assert F.load_cfg(y) == sample

    # 로컬이 있으면: 운임 규칙은 통째로 교체, default_fee 교체, carriers 는 cj_fee 만 교체(나머지 유지)
    F.local_path(y).write_text(
        'default_fee: 99000\n'
        'carriers:\n  cj_fee: 7777\n'
        'shipping_rules:\n'
        '  - {assembled: true,  fee: 55555}\n'
        '  - {assembled: false, product_contains: "빅마운틴", fee: 44444}\n', encoding="utf-8")
    cfg = F.load_cfg(y)
    assert cfg["default_fee"] == 99000
    assert cfg["carriers"]["cj_fee"] == 7777
    assert cfg["carriers"]["cj"] == sample["carriers"]["cj"]             # 덮어쓰지 않은 항목 유지
    assert cfg["payment_term"] == sample["payment_term"]
    assert len(cfg["shipping_rules"]) == 2                                # 리스트는 합치지 않고 교체
    assert F.shipping_fee_info("빅마운틴/블랙(2026)", A, cfg) == (55555, True)
    assert F.shipping_fee_info("빅마운틴/블랙(2026)", None, cfg) == (44444, True)

    # 환경변수로 무시 가능
    os.environ["FACTORY_IGNORE_LOCAL"] = "1"
    assert F.load_cfg(y) == sample
    del os.environ["FACTORY_IGNORE_LOCAL"]

    # 채팅으로 운임 규칙을 추가하면 로컬 파일에 들어가고, 샘플 파일은 그대로
    before = y.read_text(encoding="utf-8")
    msg = C.add_fee_rule("시애틀F28", 16000, y)
    assert "16,000" in msg
    assert y.read_text(encoding="utf-8") == before
    assert F.shipping_fee_info("시애틀F28/블랙", None, F.load_cfg(y)) == (16000, True)
    assert "factory.local.yaml" in C.add_fee_rule("시애틀F28", 17000, y)   # 이미 등록 안내에 실제 파일명

    # 로컬에 shipping_rules 가 없으면 기존처럼 factory.yaml 에 넣는다
    F.local_path(y).write_text("default_fee: 1\n", encoding="utf-8")
    C.add_fee_rule("시애틀F30", 18000, y)
    assert "시애틀F30" in y.read_text(encoding="utf-8")

print("OK")
