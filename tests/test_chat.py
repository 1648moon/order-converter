"""말로 하는 입력(chat.py) 테스트 - 디스코드·네트워크 불필요.
실행: <venv>/bin/python -I tests/test_chat.py
"""
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import chat as C  # noqa: E402
import rules  # noqa: E402

# 오전/오후
assert C.parse_ampm("오늘 오후 주문 처리할게요") == "오후" and C.parse_ampm("오전 건") == "오전"
assert C.parse_ampm("처리할게요") is None
assert C.default_ampm(datetime(2026, 11, 10, 9)) == "오전" and C.default_ampm(datetime(2026, 11, 10, 12)) == "오후"

# 시작 인사 vs 요청/질문
for t in ("오늘 오전 주문 처리할게요", "주문 변환 시작할게요", "안녕", "시작", "오후 건 작업하려고요"):
    assert C.is_start(t), t
for t in ("택배용 파일 다시 보내줘", "경고 알려줘", "왜 실패했어?", "시애틀F28 미조립 운임 16000", "네"):
    assert not C.is_start(t), t

# 네/아니요/건너뛰기
assert [C.answer_kind(x) for x in ("네", "네!", "ㅇㅇ", "OK", "아니요", "아니 틀렸어", "건너뛰기", "나중에", "글쎄")] == \
    ["yes", "yes", "yes", "yes", "no", "no", "skip", "skip", None]

# 운임 말 -> 규칙
assert C.parse_fee_rule("시애틀F28 미조립 운임 16000") == ("시애틀F28", 16000)
assert C.parse_fee_rule("시애틀F28 미조립 택배운임은 16,000원이야") == ("시애틀F28", 16000)
assert C.parse_fee_rule("시애틀F28 운임 16000으로 추가해줘") == ("시애틀F28", 16000)
assert C.parse_fee_rule("시애틀F28 조립 운임 16000") is None          # 조립 규칙은 막는다
assert C.parse_fee_rule('위험"; x 미조립 운임 100') is None             # 따옴표 등은 거부
assert C.parse_fee_rule("오늘 날씨 어때") is None
with tempfile.TemporaryDirectory() as d:
    y = Path(d) / "factory.yaml"
    shutil.copy(ROOT / "config" / "factory.yaml", y)
    msg = C.add_fee_rule("시애틀F28", 16000, y)
    assert "16,000" in msg
    assert "이미 등록" in C.add_fee_rule("시애틀F28", 17000, y)
    import yaml
    rules_list = yaml.safe_load(y.read_text(encoding="utf-8"))["shipping_rules"]
    assert rules_list[0].get("assembled") is True                      # 조립 전체 규칙이 맨 위
    assert {"assembled": False, "product_contains": "시애틀F28", "fee": 16000} in rules_list
    import factory as F
    cfg = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert F.shipping_fee_info("시애틀F28 자전거", "미조립", cfg) == (16000, True)
    assert yaml.safe_load(y.read_text(encoding="utf-8")).keys() == yaml.safe_load((ROOT / "config" / "factory.yaml").read_text(encoding="utf-8")).keys()

# LLM 제안 확인 -> 확정/수정/건너뛰기
with tempfile.TemporaryDirectory() as d:
    mp = Path(d) / "map.yaml"
    rules.save_product_map({
        "A상품": {"name": "A 상품", "template": "A/{color}", "status": "llm"},
        "B상품": {"name": "B 상품", "template": "B/{color}", "status": "llm"},
        "C상품": {"name": "C 상품", "template": "C/{color}", "status": "ok"}}, mp)
    items = C.pending_items(mp)
    assert [i[0] for i in items] == ["A상품", "B상품"]
    assert "A/블랙" in C.question("A 상품", "A/{color}", 1, 2) and "(1/2)" in C.question("A 상품", "A/{color}", 1, 2)
    assert C.resolve("A상품", "yes", map_path=mp) is False
    assert C.resolve("B상품", "edit", "B2/{color}", map_path=mp) is True      # 수정은 재변환 필요
    assert C.resolve("B상품", "edit", "{evil}", map_path=mp) is False         # 잘못된 템플릿은 무시
    m = rules.load_product_map(mp)
    assert m["A상품"]["status"] == "ok" and m["B상품"]["template"] == "B2/{color}" and m["B상품"]["status"] == "ok"
    assert C.pending_items(mp) == []

# 쉬운 말 보고: 개발 용어 없음, 건수·상품명만
lines = ["[경고] 변환", "    경고: 2행 [상품명] 변환 표에 없는 상품 - 원본 값 유지",
         "    경고: 3행 [상품명] LLM 제안값 적용(미확인) - 확인 후 product_map.yaml 에서 status 를 ok 로",
         "    경고: 운임표에 없는 상품 '시애틀F28' - 기본운임 적용됨. config/factory.yaml shipping_rules 에 추가 필요",
         "    경고: 수량이 1이 아닌 주문 1건"]
s = C.friendly_summary(2, lines, 52)
assert "52건" in s and "1건은 자동으로" in s and "AI가 제안" in s and "시애틀F28" in s and "그 밖에" in s
assert "종료코드" not in s and ".py" not in s and "yaml" not in s
assert "52건 변환을 마쳤어요" in C.friendly_summary(0, ["[정상] 변환"], 52)
assert C.friendly_summary(1, ["[실패] 변환", "필수 컬럼 없음: 주문번호"], 5).startswith("❌")
print("OK")
