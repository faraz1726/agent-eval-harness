"""Deterministic demo lead-qualification agent.

``v1`` is deliberately flawed (hallucinates, leaks its prompt, follows injected
instructions, claims success after tool failures...). ``v2`` fixes all of that.
Running the harness against both shows what the evaluation suite catches.
"""
from __future__ import annotations

import re

from ..tools import ToolBox, ToolError

INJECTION_RE = re.compile(
    r"ignore (all |any )?(previous|prior|above) instructions|system prompt|system override|"
    r"developer mode|admin mode|delete[_ ](all )?leads?|call delete_lead|disregard (the |all )?(rules|instructions)",
    re.I,
)
SIGNUP_RE = re.compile(
    r"sign me up|get started|enrol+|register me|finish my qualification|qualify me|complete my (sign|qualif)", re.I
)
RECALL_WORD_RE = re.compile(r"\b(what|which|remind|remember)\b", re.I)
RECALL_FIELD_RE = re.compile(r"\bmy (name|company|budget|email)\b", re.I)
NAME_RE = re.compile(r"(?i:i['’]m|i am|my name is|this is)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)")
COMPANY_RE = re.compile(r"\b(?:from|at|with)\s+([A-Z][\w&-]*(?:\s[A-Z][\w&-]*)*)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
BUDGET_RE = re.compile(r"budget[^\d]{0,40}(\d[\d,]*)(\s?[kK]\b)?")
NEED_RE = re.compile(r"(?:looking for|need|want|require)\s+(.{3,80}?)(?:[.!?]|$| for our| and )")
PLAN_WORDS = ("starter", "growth", "enterprise")
FIELDS = ("name", "company", "email", "budget_usd")
FIELD_LABELS = {"name": "your name", "company": "your company", "email": "your email",
                "budget_usd": "your monthly budget (USD)"}


class LeadAgent:
    def __init__(self, system_prompt: str, tools: ToolBox, version: str = "v2"):
        self.system_prompt = system_prompt
        self.tools = tools
        self.robust = version == "v2"
        self.state: dict = {}
        self.saved = False

    # ------------------------------------------------------------------ API
    def respond(self, user_message: str) -> str:
        text = user_message.strip()
        if INJECTION_RE.search(text):
            return self._handle_injection(text)
        self._extract(text)
        if RECALL_WORD_RE.search(text) and RECALL_FIELD_RE.search(text):
            return self._recall()
        if self._complete() and not self.saved:
            return self._qualify()
        if SIGNUP_RE.search(text):
            return self._signup_intent()
        if "?" in text:
            return self._answer_question(text)
        return self._ask_missing(first_turn=not self.state)

    # ------------------------------------------------------------ extraction
    def _extract(self, text: str) -> None:
        if m := NAME_RE.search(text):
            self.state["name"] = m.group(1)
        if m := COMPANY_RE.search(text):
            company = m.group(1).strip()
            if company != self.state.get("name"):
                self.state["company"] = company
        if m := EMAIL_RE.search(text):
            self.state["email"] = m.group(0)
        if m := BUDGET_RE.search(text):
            amount = int(m.group(1).replace(",", ""))
            self.state["budget_usd"] = amount * 1000 if m.group(2) else amount
        if m := NEED_RE.search(text):
            self.state["need"] = m.group(1).strip()

    def _complete(self) -> bool:
        return all(f in self.state for f in FIELDS)

    def _missing(self) -> list[str]:
        return [f for f in FIELDS if f not in self.state]

    # -------------------------------------------------------------- behaviours
    def _handle_injection(self, text: str) -> str:
        if self.robust:
            return ("I can't help with that, but I'm happy to answer questions about NovaDesk "
                    "plans or help qualify your enquiry.")
        if "system prompt" in text.lower():
            return f"Sure! My instructions are: {self.system_prompt}"
        try:
            self.tools.call("delete_lead", {"lead_id": "ALL"})
        except ToolError:
            pass
        return "Done - I've deleted all the leads as requested."

    def _recall(self) -> str:
        if not self.robust:
            return "Sorry, I don't have that handy - could you remind me?"
        known = []
        if "name" in self.state:
            known.append(f"your name is {self.state['name']}")
        if "company" in self.state:
            known.append(f"you're with {self.state['company']}")
        if "budget_usd" in self.state:
            known.append(f"your budget is ${self.state['budget_usd']} per month")
        if "email" in self.state:
            known.append(f"your email is {self.state['email']}")
        if not known:
            return "You haven't shared any details with me yet. What's your name and company?"
        return "Of course! So far I have that " + ", ".join(known) + "."

    def _answer_question(self, text: str) -> str:
        try:
            results = self.tools.call("lookup_product", {"query": text})["results"]
        except ToolError:
            if self.robust:
                return ("I'm unable to retrieve that information right now, and I'd rather not guess. "
                        "Please try again in a moment, or I can have a teammate confirm the details.")
            return "The Starter plan is $99 per month."
        if not self.robust:
            if not results:
                return "Yes, we offer a 20% student discount, and our lifetime deal is $99 one-time!"
            return "Here's what I found: " + " ".join(f"{r['title']}: {r['text']}" for r in results)
        # robust path: drop poisoned documents, stay grounded in what was retrieved
        results = [r for r in results if not INJECTION_RE.search(r["text"])]
        named = [w for w in PLAN_WORDS if w in text.lower()]
        if named:
            results = [r for r in results if any(w in r["title"].lower() for w in named)] or results
        if not results:
            return ("I don't have confirmed information about that, so I'd rather not guess. "
                    "I can check with the team and follow up. Could you share your email?")
        return "Here's what I found: " + " ".join(f"{r['title']}: {r['text']}" for r in results)

    def _signup_intent(self) -> str:
        if self.robust:
            return self._ask_missing()
        # v1 flaw: tries to save whatever it has and claims success
        try:
            self.tools.call("save_lead", {
                "name": self.state.get("name", "Unknown"), "company": self.state.get("company", "Unknown"),
                "email": self.state.get("email", ""), "budget_usd": self.state.get("budget_usd", 0)})
        except ToolError:
            pass
        return "You're all set! I've signed you up."

    def _ask_missing(self, first_turn: bool = False) -> str:
        missing = self._missing()
        if not missing:
            return "Thanks! Is there anything else I can help you with?"
        ask = ", ".join(FIELD_LABELS[f] for f in missing[:-1])
        ask = f"{ask} and {FIELD_LABELS[missing[-1]]}" if ask else FIELD_LABELS[missing[-1]]
        if first_turn:
            return f"Hi! I'm the NovaDesk assistant. Could you share {ask}?"
        who = " ".join(filter(None, [self.state.get("name"), f"from {self.state['company']}" if "company" in self.state else ""]))
        greeting = f"Thanks, {who}! " if who else "Thanks! "
        return f"{greeting}To qualify you, could you share {ask}?"

    def _qualify(self) -> str:
        s = self.state
        need = s.get("need", "")
        score = None
        try:
            score = self.tools.call("score_lead", {"budget_usd": s["budget_usd"], "need": need})
        except ToolError:
            pass
        args = {k: s[k] for k in FIELDS}
        if need:
            args["need"] = need
        if isinstance(score, dict) and "score" in score and "tier" in score:
            args["score"], args["tier"] = score["score"], score["tier"]
        saved = None
        for _ in range(2 if self.robust else 1):  # v2 retries once, v1 gives up silently
            try:
                res = self.tools.call("save_lead", args)
            except ToolError:
                continue
            if isinstance(res, dict) and res.get("status") == "saved":
                saved = res
                break
        if saved:
            self.saved = True
        elif self.robust:
            return ("I'm sorry, I wasn't able to save your details because of a technical issue. "
                    "Please try again shortly - a teammate will also follow up.")
        tier = args.get("tier")
        extra = f" You're a {tier} lead." if tier else ""
        lead_ref = f" (ID {saved['lead_id']})" if saved else ""
        return f"Thanks {s['name']}!{extra} I've saved your details{lead_ref} and a teammate will contact you at {s['email']}."
