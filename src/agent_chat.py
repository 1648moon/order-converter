"""디스코드 메시지 한 줄을 받아 보낼 답 목록을 만든다 (디스코드·네트워크와 무관한 순수 흐름 -> 테스트 가능).

승인 게이트는 여기 코드에 있다 (프롬프트가 아니라):
  1) '승인 3' / '거절 3' / (대기 중 제안이 하나일 때) '네' '아니요' 는 LLM 을 거치지 않고 이 코드가 처리한다.
  2) LLM 은 제안(propose_*)만 만들 수 있고, 만들어진 제안은 코드가 만든 문장으로 다시 보여 준다.
  3) 적용은 agent_rules.apply 로만, 사용자가 허용된 사람(Notifier.is_allowed)일 때만 일어난다.
ANTHROPIC_API_KEY 가 없으면 LLM 없이도 '시애틀F28 미조립 운임 16000' 같은 정해진 문장은 처리한다.
"""
from __future__ import annotations

import re

import agent_rules
import agent_tools
import chat
from agent_state import Store

_APPROVE = re.compile(r"^(승인|적용|확정)\s*#?\s*(\d+)?\s*(번)?$")
_REJECT = re.compile(r"^(거절|반려|취소)\s*#?\s*(\d+)?\s*(번)?$")
REUPLOAD = "서버는 개인정보 때문에 업로드한 파일을 보관하지 않아요. 웹에서 같은 주문 파일을 다시 올려 주세요."


def proposal_text(p: dict) -> str:
    return (f"📝 변경 제안 #{p['id']}\n• {p['summary']}\n"
            f"맞으면 '승인 {p['id']}', 아니면 '거절 {p['id']}'라고 답해 주세요.")


def issues_message(record: dict) -> str | None:
    """웹 변환이 끝난 뒤 디스코드에 올릴 '확인할 것' 안내. 확인할 게 없으면 None."""
    unmatched = record.get("unmatched_products") or []
    fees = record.get("fee_missing_products") or []
    if not unmatched and not fees:
        return None
    lines = [f"🔎 {record.get('run', '이번 변환')}에서 확인할 게 있어요."]
    if fees:
        lines.append("• 운임을 모르는 상품: " + ", ".join(fees[:10]))
    if unmatched:
        lines.append("• 공장 표기를 모르는 상품: " + ", ".join(unmatched[:10]))
    lines.append("운임이나 표기를 알려 주시면 제안을 올릴게요. (예: '시애틀F28 미조립 운임 16000')")
    return "\n".join(lines)


class AgentChat:
    def __init__(self, store: Store | None = None, brain=None):
        self.store = store or Store()
        self.brain = brain
        self._awaiting: dict[str, bool] = {}     # 채널별: 봇의 직전 메시지가 '제안 안내'였나 (짧은 네/아니요를 승인으로 볼 조건)

    # ---- 진입점 ----
    def handle(self, text: str, channel: str = "main") -> list[str]:
        text = text.strip()
        if not text:
            return []
        awaiting = self._awaiting.pop(channel, False)       # 어떤 경우에도 이번 턴이 끝나면 꺼진다
        done = self._approval(text, awaiting)
        if done is not None:
            return done
        before = {p["id"] for p in self.store.pending()}
        if self.brain is not None:
            reply = self.brain.respond(channel, text)
        else:
            reply = self._fallback(text)
        out = [reply] if reply else []
        announced = [p for p in self.store.pending() if p["id"] not in before]
        out += [proposal_text(p) for p in announced]
        self._awaiting[channel] = bool(announced)           # 마지막 메시지가 제안 안내일 때만 '네'를 승인으로 본다
        return out

    # ---- 승인 / 거절 (LLM 을 거치지 않음) ----
    def _approval(self, text: str, awaiting: bool = False) -> list[str] | None:
        pending = self.store.pending()
        action, pid = None, None
        m = _APPROVE.match(text)
        r = _REJECT.match(text)
        if m:
            action, pid = "approve", m.group(2)
        elif r:
            action, pid = "reject", r.group(2)
        elif pending and awaiting:                     # 짧은 네/아니요: 봇이 방금 제안을 안내했을 때만. 하나면 그것, 여럿이면 번호를 되묻는다
            kind = chat.answer_kind(text)
            if kind in ("yes", "no"):
                action = "approve" if kind == "yes" else "reject"
                pid = str(pending[0]["id"]) if len(pending) == 1 else None
        if action is None:
            return None
        if pid is None:
            if len(pending) == 1:
                pid = str(pending[0]["id"])
            elif not pending:
                return ["대기 중인 제안이 없어요."]
            else:
                ids = ", ".join(f"#{p['id']}" for p in pending)
                return [f"대기 중인 제안이 여러 개예요 ({ids}). 번호를 붙여 '승인 3'처럼 말해 주세요."]
        p = self.store.get_proposal(int(pid))
        if p is None:
            return [f"#{pid} 제안을 찾지 못했어요."]
        if p["status"] != "pending":
            label = {"applied": "이미 적용됐어요", "rejected": "이미 거절했어요", "expired": "시간이 지나 만료됐어요",
                     "failed": "적용하지 못한 제안이에요"}.get(p["status"], "처리할 수 없어요")
            return [f"#{p['id']} 제안은 {label}."]
        if action == "reject":
            self.store.set_status(p["id"], "rejected")
            return [f"#{p['id']} 제안을 거절했어요. 바꾸지 않았어요."]
        try:
            result = agent_rules.apply(p)
        except Exception as e:
            self.store.set_status(p["id"], "failed", type(e).__name__)
            return [f"#{p['id']} 제안을 적용하지 못했어요 ({type(e).__name__}). 아무것도 바뀌지 않았어요."]
        self.store.set_status(p["id"], "applied")
        return [f"✅ {result}\n{REUPLOAD}"]

    # ---- LLM 없이 처리 가능한 정해진 문장 ----
    def _fallback(self, text: str) -> str:
        rule = chat.parse_fee_rule(text)
        if rule:
            out = agent_tools.run_tool("propose_fee_rule", {"product": rule[0], "fee": rule[1]}, self.store)
            return out.get("error") or ""      # 성공이면 proposal_text 가 따로 붙는다
        if self.store.pending() and chat.answer_kind(text) in ("yes", "no"):
            return "승인하려면 '승인 번호', 거절하려면 '거절 번호'라고 답해 주세요. (예: 승인 1)"
        return ("지금은 AI 연결이 꺼져 있어요. '시애틀F28 미조립 운임 16000' 처럼 말해 주시면 제안을 만들 수 있어요. "
                "'승인 번호', '거절 번호'로 답해 주세요.")


def default_handler(store: Store | None = None):
    """Notifier 에 넘길 핸들러: 텍스트 -> 보낼 문장 목록. ANTHROPIC_API_KEY 가 있으면 Claude 를 쓴다."""
    from agent_llm import Brain

    store = store or Store()
    brain = None
    try:
        brain = Brain.from_env(store)
    except Exception as e:                      # 패키지 문제 등으로 LLM 을 못 켜도 규칙 기반으로는 동작
        print(f"[에이전트] AI 연결을 켜지 못했습니다 ({type(e).__name__}) - 규칙 기반으로만 응답합니다.")
    print("[에이전트] " + ("Claude 연결됨" if brain else "ANTHROPIC_API_KEY 없음 - 규칙 기반으로만 응답"))
    return AgentChat(store, brain).handle
