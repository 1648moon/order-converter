"""디스코드 에이전트 테스트 - 네트워크·디스코드·API 키 없이 돈다 (Claude 는 가짜 클라이언트로 대신한다).
실행: PYTHONPATH=src python -I tests/test_agent.py   (또는 python -m unittest discover -s tests)
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="agent_test_"))
os.environ["ORDER_RULES_DIR"] = str(TMP / "rules")        # 실제 config/ 를 건드리지 않도록 먼저 지정
os.environ["AGENT_STATE_DIR"] = str(TMP / "agent")
_saved_ignore = os.environ.pop("FACTORY_IGNORE_LOCAL", None)   # 다른 테스트가 켠 값이 이 테스트에 영향 주지 않게

import agent_chat as AC  # noqa: E402
import agent_llm  # noqa: E402
import agent_rules as AR  # noqa: E402
import agent_tools as AT  # noqa: E402
import discord_notify as DN  # noqa: E402
import factory as F  # noqa: E402
import rules  # noqa: E402
import run_report as RR  # noqa: E402
from agent_state import Store  # noqa: E402


def fresh_store(clock=None):
    d = Path(tempfile.mkdtemp(dir=TMP))
    return Store(d, **({"clock": clock} if clock else {}))


RUN = {"run": "2026-11-15_v1", "overall": "경고", "files": 4, "orders": 12, "warn_stages": ["공장용"],
       "fail_stages": [], "unmatched_products": ["신상 어린이헬멧 SH900"], "fee_missing_products": ["시애틀F99/블랙"],
       "partial": False}

# ---- 1. 저장소: 제안 생성/중복/상태/만료 ----
t = [1000.0]
s = fresh_store(lambda: t[0])
p1 = s.add_proposal("fee_rule", {"product": "시애틀F99", "fee": 16000}, "x")
assert p1["id"] == 1 and p1["status"] == "pending"
assert s.add_proposal("fee_rule", {"product": "시애틀F99", "fee": 16000}, "x")["id"] == 1      # 같은 내용은 새로 안 만든다
p2 = s.add_proposal("fee_rule", {"product": "시애틀F99", "fee": 17000}, "y")
assert p2["id"] == 2 and [p["id"] for p in s.pending()] == [1, 2]
s.set_status(1, "applied")
assert [p["id"] for p in s.pending()] == [2]
t[0] += 25 * 3600                                                                               # 하루 지나면 만료
assert s.pending() == [] and s.get_proposal(2)["status"] == "expired"
s.save_run(RUN)
assert s.latest_run()["run"] == "2026-11-15_v1"

# ---- 2. 검증: 모델이 준 값은 코드가 다시 거른다 ----
assert AR.validate_fee_rule("시애틀 F28", "16,000") == ("시애틀F28", 16000)
assert AR.validate_fee_rule("시애틀F28", 16000.0) == ("시애틀F28", 16000)
assert AR.validate_fee_rule("시애틀\nF28", 1000)[0] == "시애틀F28"          # 공백·개행은 지워서 정규화
for bad_name in ('시애틀"; rm', "시애틀F28/블랙", "a{b}", "", "가" * 31, "x\x00y", "시애틀F28: 1", "a#b", "a\\b"):
    try:
        AR.validate_fee_rule(bad_name, 1000)
        raise AssertionError(bad_name)
    except ValueError:
        pass
for bad_fee in (0, -5, 1_000_000, "abc", True, None, 1.5):
    try:
        AR.validate_fee_rule("시애틀F28", bad_fee)
        raise AssertionError(bad_fee)
    except ValueError:
        pass
for bad_t in ("{x}", "{0}", "a/{color.__class__}", "", None, "{color"):
    try:
        AR.validate_mapping("상품", bad_t)
        raise AssertionError(bad_t)
    except ValueError:
        pass
assert AR.validate_mapping("상품 A", "시애틀F28/{color}") == ("상품 A", "시애틀F28/{color}")

# ---- 3. 적용: 운임은 운임표 위쪽에 끼워지고 기존 규칙보다 우선 ----
cfg0 = F.load_cfg()
n0 = len(cfg0["shipping_rules"])
assert F.shipping_fee_info("시애틀F99/블랙", None, cfg0)[1] is False            # 아직 규칙 없음
msg = AR.apply_fee_rule("시애틀F99", 16000)
assert "16,000원" in msg and "추가" in msg
cfg1 = F.load_cfg()
assert len(cfg1["shipping_rules"]) == n0 + 1
assert F.shipping_fee_info("시애틀F99/블랙", None, cfg1) == (16000, True)
assert F.shipping_fee("시애틀F99/블랙", "100%조립요청", cfg1) == 20000            # 조립 규칙(모델 무관)이 계속 먼저
assert F.shipping_fee("시애틀MT24/블랙", None, cfg1) == F.shipping_fee("시애틀MT24/블랙", None, cfg0)   # 다른 모델은 그대로
assert "바꿨어요" in AR.apply_fee_rule("시애틀F99", 17000)                         # 같은 모델 재적용은 교체
assert F.shipping_fee("시애틀F99/블랙", None, F.load_cfg()) == 17000 and len(F.load_cfg()["shipping_rules"]) == n0 + 1
assert not (ROOT / "config" / "factory.agent.yaml").exists()                    # 저장소 config 는 건드리지 않았다
os.environ["FACTORY_IGNORE_LOCAL"] = "1"                                         # 샘플값 기준 테스트용 스위치는 에이전트 규칙도 끈다
assert F.shipping_fee_info("시애틀F99/블랙", None, F.load_cfg())[1] is False
os.environ.pop("FACTORY_IGNORE_LOCAL")

# ---- 4. 적용: 상품 표기 매핑 ----
terms0 = rules.load_terms(map_path=rules.rules_dir() / "product_map.yaml")
assert rules.convert_product("신상 어린이헬멧 SH900", "색상:블랙", terms0)[1] == "변환 표에 없는 상품"
AR.apply_mapping("신상 어린이헬멧 SH900", "삼천리SH900어린이헬멧/{color}")
terms1 = rules.load_terms(map_path=rules.rules_dir() / "product_map.yaml")
assert rules.convert_product("신상 어린이헬멧 SH900", "색상:블랙", terms1) == ("삼천리SH900어린이헬멧/블랙", None)

# ---- 5. 요약 기록: 개인정보 없음 ----
assert RR.safe_name("010-1234-5678 헬멧") is None and RR.safe_name("시애틀F28") == "시애틀F28"
assert RR.safe_name("가" * 61) is None and RR.safe_name("  ") is None

from openpyxl import Workbook  # noqa: E402

src = TMP / "src.xlsx"
wb = Workbook()
ws = wb.active
heads = ["주문번호", "수령자", "주소", "상품명", "선택사항", "수량"]
ws.append(heads)
ws.append(["A1", "홍길동", "서울시 동대문구 어딘가 1-2", "미등록테스트상품Q", "색상:블랙", 1])
ws.append(["A2", "김철수", "경기도 수원시 어딘가 3-4", "010-9999-8888", "색상:블랙", 1])      # 이름이 전화번호 꼴이면 버린다
ws.append(["A3", "이영희", "부산시 어딘가 5-6", "빅마운틴 2026", "색상:블랙", 1])
wb.save(src)
orders, unmatched = RR.unmatched_products(src)
assert orders == 3 and unmatched == ["미등록테스트상품Q"], (orders, unmatched)

inter = TMP / "inter_변환.xlsx"
wb = Workbook()
ws = wb.active
ws.append(["주문번호", "수령자", "", "우편번호", "주소", "수령자전화번호", "수령자휴대전화", "수량", "상품명", "선택사항",
           "추가구성", "배송메모", "택배사"])
ws.append(["A1", "홍길동", "홍길동(서울시)", 12345, "서울", "02-111-2222", "010-1111-2222", 1, "시애틀F77/블랙", None, None, None, "경동택배"])
ws.append(["A2", "김철수", "김철수(경기도)", 12345, "경기", "02-111-2222", "010-1111-2222", 1, "시애틀MT24/블랙", None, None, None, "경동택배"])
wb.save(inter)
assert RR.fee_missing_products(inter) == ["시애틀F77/블랙"]

rec = RR.build_record(src, None, NS(name="2026-11-15_v1", overall="경고", files=["a.xlsx"], warn_stages=["공장용"], fail_stages=[]))
blob = json.dumps(rec, ensure_ascii=False)
for secret in ("홍길동", "김철수", "이영희", "동대문", "수원", "010-9999-8888"):
    assert secret not in blob, secret

# ---- 6. 도구: 개인정보 모양은 출력에서 지워지고, 매핑은 최근 변환에 나온 이름만 ----
s = fresh_store()
s.save_run({**RUN, "unmatched_products": ["신상 어린이헬멧 SH900", "수상한 010-1234-5678 상품"]})
out = AT.run_tool("get_latest_run", {}, s)
assert out["available"] and "010-1234-5678" not in json.dumps(out, ensure_ascii=False)
assert AT.run_tool("get_latest_run", {}, fresh_store())["available"] is False
ex = json.dumps(AT.run_tool("get_naming_examples", {}, s), ensure_ascii=False)
assert "빅마운틴" in ex
assert AT.run_tool("propose_fee_rule", {"product": "시애틀F99", "fee": 99999999}, s).get("error")
assert AT.run_tool("propose_product_mapping", {"original_name": "아무거나 상품", "template": "x/{color}"}, s).get("error")
assert AT.run_tool("propose_product_mapping", {"original_name": "신상 어린이헬멧 SH900", "template": "{evil}"}, s).get("error")
ok = AT.run_tool("propose_product_mapping", {"original_name": "신상어린이헬멧SH900", "template": "삼천리SH900/{color}"}, s)
assert ok["status"] == "awaiting_human_approval" and s.get_proposal(ok["proposal_id"])["params"]["name"] == "신상 어린이헬멧 SH900"
assert AT.run_tool("없는도구", {}, s)["error"]
chk = AT.run_tool("check_fee_rule", {"product": "시애틀MT24"}, s)
assert chk["has_rule"] is True and "fee" not in json.dumps(chk)                  # 기존 금액은 노출하지 않는다
assert not any(t["name"].startswith(("apply", "approve", "write", "set_")) for t in AT.TOOLS)   # 적용 도구는 없다
assert [t["name"] for t in AT.TOOLS if t["name"].startswith("propose")] == ["propose_fee_rule", "propose_product_mapping"]


# ---- 7. 가짜 Claude: 도구 호출 루프 ----
class FakeClient:
    def __init__(self, script):
        self.script, self.calls, self.messages = list(script), [], self
    def create(self, **kw):
        self.calls.append(json.loads(json.dumps({k: v for k, v in kw.items() if k != "tools"}, default=lambda o: str(o))))
        return self.script.pop(0)


def tool_use(i, name, **inp):
    return NS(type="tool_use", id=i, name=name, input=inp)


def text(t):
    return NS(type="text", text=t)


s = fresh_store()
s.save_run(RUN)
fc = FakeClient([
    NS(stop_reason="tool_use", content=[tool_use("t1", "get_latest_run")]),
    NS(stop_reason="tool_use", content=[tool_use("t2", "propose_fee_rule", product="시애틀F99", fee=16000)]),
    NS(stop_reason="end_turn", content=[text("제안을 올렸어요. 맞으면 승인 1 이라고 답해 주세요.")]),
])
chat = AC.AgentChat(s, agent_llm.Brain(fc, s))
msgs = chat.handle("시애틀F99 운임 16000원이야")
assert "승인 1" in msgs[0] and msgs[1].startswith("📝 변경 제안 #1") and "16,000원" in msgs[1]     # 코드가 만든 안내가 따로 붙는다
assert fc.calls[0]["model"] == "claude-opus-5-5" and "tool_choice" not in fc.calls[0]
assert fc.calls[0]["output_config"] == {"effort": "medium"}
assert s.get_proposal(1)["status"] == "pending"                                                    # 아직 적용 전
assert F.shipping_fee("시애틀F99/블랙", None, F.load_cfg()) == 17000                                # (앞 테스트 값 그대로)
# 도구 결과가 다음 요청에 tool_result 로 돌아갔는지
assert any(m["role"] == "user" and isinstance(m["content"], list) and m["content"][0]["type"] == "tool_result"
           for m in fc.calls[2]["messages"])

# 모델이 도구 입력으로 값을 속여도(주입) 코드 검증이 막는다
s2 = fresh_store()
s2.save_run(RUN)
fc2 = FakeClient([
    NS(stop_reason="tool_use", content=[tool_use("t1", "propose_fee_rule", product="x\"; evil", fee=1)]),
    NS(stop_reason="end_turn", content=[text("모델명을 다시 알려 주세요.")]),
])
AC.AgentChat(s2, agent_llm.Brain(fc2, s2)).handle("아무 말")
assert s2.pending() == []
assert fc2.calls[1]["messages"][-1]["content"][0]["is_error"] is True      # 검증 실패는 오류 결과로 모델에게 돌아간다

# 거절(refusal)·길이 초과·루프 한도·API 오류
assert agent_llm.Brain(FakeClient([NS(stop_reason="refusal", content=[])]), s).respond("c", "hi").startswith("이 요청은")
assert "줄였어요" in agent_llm.Brain(FakeClient([NS(stop_reason="max_tokens", content=[text("긴 답")])]), s).respond("c", "hi")
loop = FakeClient([NS(stop_reason="tool_use", content=[tool_use(f"t{i}", "list_pending_proposals")]) for i in range(10)])
assert "나눠서" in agent_llm.Brain(loop, s).respond("c", "hi") and len(loop.calls) == agent_llm.MAX_ROUNDS
import anthropic  # noqa: E402


class Boom:
    messages = None
    def __init__(self):
        self.messages = self
    def create(self, **kw):
        raise anthropic.APIConnectionError(request=NS(url="x", method="POST"))


assert "AI 연결" in agent_llm.Brain(Boom(), s).respond("c", "hi")
# 대화 기록은 채널별 최근 것만, 텍스트만 남긴다
b = agent_llm.Brain(FakeClient([NS(stop_reason="end_turn", content=[text(str(i))]) for i in range(20)]), s)
for i in range(20):
    b.respond("ch", f"q{i}")
assert len(b._history["ch"]) == 2 * agent_llm.HISTORY_TURNS and all(isinstance(m["content"], str) for m in b._history["ch"])

# ---- 8. 승인 게이트 (LLM 을 거치지 않음) ----
s = fresh_store()
s.save_run(RUN)
chat = AC.AgentChat(s, brain=None)                                                  # 키 없는 상태: 규칙 기반
r = chat.handle("시애틀F55 미조립 운임 16000")
assert len(r) == 1 and r[0].startswith("📝 변경 제안 #1"), r
assert F.shipping_fee_info("시애틀F55/블랙", None, F.load_cfg())[1] is False         # 승인 전에는 적용되지 않았다
r = chat.handle("네")                                                               # 봇이 제안을 안내한 직후의 '네' = 승인
assert r[0].startswith("✅") and "다시 올려" in r[0]
assert F.shipping_fee_info("시애틀F55/블랙", None, F.load_cfg()) == (16000, True)
assert chat.handle("승인 1")[0] == "#1 제안은 이미 적용됐어요."                          # 두 번 적용되지 않는다
assert chat.handle("승인 7") == ["#7 제안을 찾지 못했어요."]
chat.handle("시애틀F56 미조립 운임 11000")
chat.handle("시애틀F57 미조립 운임 12000")
assert "여러 개" in chat.handle("네")[0] and "#2" in chat.handle("승인")[0]                  # 둘 이상이면 번호를 요구
assert chat.handle("거절 2")[0].startswith("#2 제안을 거절")
assert F.shipping_fee_info("시애틀F56/블랙", None, F.load_cfg())[1] is False
assert chat.handle("승인 3")[0].startswith("✅")
assert chat.handle("승인") == ["대기 중인 제안이 없어요."]
assert chat.handle("안녕하세요")[0].startswith("지금은 AI 연결이 꺼져")
assert chat.handle("   ") == []
# 만료된 제안은 승인되지 않는다
t = [5000.0]
s = fresh_store(lambda: t[0])
chat = AC.AgentChat(s, None)
chat.handle("시애틀F60 미조립 운임 9000")
t[0] += 25 * 3600
assert chat.handle("승인 1") == ["#1 제안은 시간이 지나 만료됐어요."]
assert F.shipping_fee_info("시애틀F60/블랙", None, F.load_cfg())[1] is False

# 적용 중 오류가 나면 '실패'로 두고 아무것도 바꾸지 않는다
s = fresh_store()
s.add_proposal("fee_rule", {"product": "bad name!", "fee": 5000}, "x")
r = AC.AgentChat(s, None).handle("승인 1")
assert "적용하지 못했어요" in r[0] and s.get_proposal(1)["status"] == "failed"

# ---- 9. 변환 후 안내 문구 ----
assert AC.issues_message({**RUN, "unmatched_products": [], "fee_missing_products": []}) is None
im = AC.issues_message(RUN)
assert "시애틀F99/블랙" in im and "신상 어린이헬멧 SH900" in im and "운임" in im

# ---- 10. 디스코드 글자 수 나누기, 허용 사용자 ----
long = "\n".join("가" * 100 for _ in range(60))
parts = DN.split_message(long)
assert all(len(p) <= DN.DISCORD_LIMIT for p in parts) and "".join(parts).replace("\n", "") == long.replace("\n", "")
assert DN.split_message("x" * 5000) and all(len(p) <= DN.DISCORD_LIMIT for p in DN.split_message("x" * 5000))
n = DN.Notifier(None, None, None, 1, allowed_ids=[2], agent_handler=lambda t: [t])
assert n.is_allowed(1) and n.is_allowed(2) and not n.is_allowed(3)
assert n.reply_for("상태") is not None and n.reply_for("시애틀F28 운임 1000") is None           # 일반 문장은 에이전트로 넘어간다

# ---- 11. 회귀: 제안이 대기 중일 때 Claude 의 다른 질문에 한 '네'가 그 제안을 승인하면 안 된다 ----
s = fresh_store()
s.save_run(RUN)
fc = FakeClient([
    NS(stop_reason="tool_use", content=[tool_use("t1", "propose_fee_rule", product="시애틀F71", fee=12000)]),
    NS(stop_reason="end_turn", content=[text("제안을 올렸어요.")]),
    NS(stop_reason="end_turn", content=[text("이 표기로 제안할까요?")]),          # 다음 턴: 운임과 상관없는 질문
    NS(stop_reason="end_turn", content=[text("알겠어요, 제안할게요.")]),
])
chat = AC.AgentChat(s, agent_llm.Brain(fc, s))
chat.handle("시애틀F71 운임 12000")                                              # 제안 #1 안내
assert chat.handle("헬멧 표기도 봐줘") == ["이 표기로 제안할까요?"]
assert chat.handle("네") == ["알겠어요, 제안할게요."]                              # 답은 Claude 가 한다
assert s.get_proposal(1)["status"] == "pending"                                 # 운임 제안은 그대로 대기
assert F.shipping_fee_info("시애틀F71/블랙", None, F.load_cfg())[1] is False
assert chat.handle("승인 1")[0].startswith("✅")                                  # 번호를 붙이면 언제든 승인된다
assert F.shipping_fee_info("시애틀F71/블랙", None, F.load_cfg()) == (12000, True)
# 제안 안내 직후의 '네'는 승인, 그다음 턴부터는 다시 일반 대화
s = fresh_store()
chat = AC.AgentChat(s, None)
chat.handle("시애틀F72 미조립 운임 9000")
assert chat.handle("네")[0].startswith("✅")
chat.handle("시애틀F73 미조립 운임 9500")
chat.handle("아무 말")                                                            # 안내 뒤 다른 말 -> 플래그 해제
assert "승인 번호" in chat.handle("네")[0] and s.get_proposal(2)["status"] == "pending"
# 채널이 다르면 서로의 '직전 안내'를 공유하지 않는다
s = fresh_store()
chat = AC.AgentChat(s, None)
chat.handle("시애틀F74 미조립 운임 9000", channel="A")
assert chat.handle("네", channel="B")[0].startswith("승인하려면")
assert s.get_proposal(1)["status"] == "pending"

# ---- 12. 서버 봇 연결 스모크: DISCORD_* 없이도 에이전트 핸들러가 붙고, 제안 -> 승인 -> 파일 기록까지 간다 ----
for k in ("DISCORD_TOKEN", "DISCORD_CHANNEL_ID", "DISCORD_OWNER_ID", "DISCORD_ALLOWED_IDS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)
DN._server_notifier = None
bot = DN.server_notifier()
assert bot.agent_handler is not None and not bot.enabled
msgs = bot.agent_handler("시애틀F88 미조립 운임 16000")
assert msgs and msgs[-1].startswith("📝 변경 제안 #")
num = msgs[-1].split("#")[1].split("\n")[0]
assert "시애틀F88" not in (rules.agent_fee_path().read_text(encoding="utf-8") if rules.agent_fee_path().exists() else "")
done = bot.agent_handler(f"승인 {num}")
assert done[0].startswith("✅") and "시애틀F88" in rules.agent_fee_path().read_text(encoding="utf-8")
DN._server_notifier = None
boom = DN.Notifier(None, None, None, 1, agent_handler=lambda t: 1 / 0)             # 핸들러가 터져도 봇은 계속
assert DN.Notifier._safe_agent(boom, "x") == ["처리 중 문제가 생겼어요. 잠시 뒤 다시 말씀해 주세요."]

if _saved_ignore is not None:
    os.environ["FACTORY_IGNORE_LOCAL"] = _saved_ignore
for _k in ("ORDER_RULES_DIR", "AGENT_STATE_DIR"):      # 같은 프로세스에서 도는 다른 테스트에 새지 않게
    os.environ.pop(_k, None)
print("OK (agent)")
