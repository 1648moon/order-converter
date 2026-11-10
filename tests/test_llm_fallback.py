"""LLM 폴백 테스트(네트워크 없음). 실행: python -I tests/test_llm_fallback.py"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import rules, llm_fallback as L  # noqa: E402

# 템플릿 검증: {color} 만 허용
assert L.valid_template("빅마운틴/{color}(2026)")
assert not L.valid_template("{0}") and not L.valid_template("{color.__class__}") and not L.valid_template("{x}")
assert not L.valid_template(None) and not L.valid_template("") and not L.valid_template("{")

# 응답 파싱: 설명 문장이 섞여도 JSON 추출, null/잘못된 템플릿은 제외
txt = '결과입니다 {"A상품": "A/{color}", "B상품": null, "C상품": "{evil}"} 끝'
assert L.parse_response(txt, ["A상품", "B상품", "C상품"]) == {"A상품": "A/{color}"}
assert L.parse_response("not json", ["A"]) == {}

with tempfile.TemporaryDirectory() as d:
    mp = Path(d) / "map.yaml"
    terms = rules.load_terms(map_path=mp)
    opt = "색상: 블랙, 완전조립"
    assert rules.convert_product("신상 자전거 XYZ", opt, terms) == ("신상 자전거 XYZ", "변환 표에 없는 상품")
    # 제안 저장 -> 재로딩 -> 적용(미확인 경고)
    terms["_map"]["신상자전거XYZ"] = {"name": "신상 자전거 XYZ", "template": "XYZ/{color}", "status": "llm"}
    rules.save_product_map(terms["_map"], mp)
    t2 = rules.load_terms(map_path=mp)
    assert rules.convert_product("신상 자전거 XYZ", opt, t2) == ("XYZ/블랙", rules.LLM_WARN)
    # 확인(ok) 처리하면 경고 없음
    t2["_map"]["신상자전거XYZ"]["status"] = "ok"
    assert rules.convert_product("신상 자전거 XYZ", opt, t2) == ("XYZ/블랙", None)
    # 색상 없으면 원본 유지 + 경고
    assert rules.convert_product("신상 자전거 XYZ", "옵션없음", t2)[1] is not None
    # 기존 규칙이 우선
    assert rules.convert_product("빅마운틴 2026년형", opt, t2)[0] == "빅마운틴/블랙(2026)"
# 축약 자전거명 목록(내부보관용 product_list) -> 색상 템플릿, 프롬프트에 포함
t = rules.load_terms(map_path=Path("/nonexistent.yaml"))
bt = L.bike_templates(t)
assert "시애틀MT24/{color}" in bt and "빅마운틴/{color}(2026)" in bt and "엑스퍼트/380{color}" in bt and "엑스퍼트/510{color}" in bt
assert len(bt) == len(set(bt)) and all(L.valid_template(x) for x in bt)
pr = L.build_prompt(["x"], t)
assert "시애틀키즈18/{color}" in pr and "시애틀클래식20/{color}" in pr and "시애틀라인26/{color}" in pr
print("OK")
