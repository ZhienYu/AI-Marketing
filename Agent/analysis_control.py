"""Server-side policy, explicit paid consent, and conservative budget reservations."""
import json
import hashlib
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Lock

CONFIG_PATH = Path(__file__).parent / "config/research_access.json"
LEDGER_PATH = Path(__file__).parent / ".runtime/research_budget.sqlite3"
SCOPES = {"youtube_aggregation", "feedback_nlp", "consumer_needs", "third_party_qwen", "report_view"}
QWEN_MODEL = "qwen-plus-2025-12-01"
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
PRICE_REFERENCE = "https://help.aliyun.com/zh/model-studio/model-pricing"
ANALYSIS_ENABLED = True  # Technical availability only; never grants platform rights.


KEYWORD_BUDGET_MODE = "keyword_single_request_estimate"
BATCH_BUDGET_MODE = "keyword_batch_estimate"
BATCH_MAX_COMMENTS = 10
BATCH_SIZE = 4
BATCH_MAX_CALLS = 3
BATCH_INPUT = 11000
BATCH_OUTPUT = 3000
BATCH_RESERVATION_CNY = Decimal("0.0444")
PHASE_K = "phase_k"
PHASE_K_COLLECTION = (20, 50)
PHASE_K_RUN_SECONDS = 720
SESSION_SECONDS = 900


@dataclass(frozen=True)
class BatchProfile:
    comments: int
    calls: int
    reservation_cny: Decimal
    videos: int = 5
    comments_per_video: int = 10

    @property
    def tokens(self):
        return self.calls * (BATCH_INPUT + BATCH_OUTPUT)


BATCH_PROFILES = {
    "standard": BatchProfile(BATCH_MAX_COMMENTS, BATCH_MAX_CALLS, BATCH_RESERVATION_CNY),
    "pilot15": BatchProfile(15, 4, Decimal("0.0592")),
    PHASE_K: BatchProfile(80, 20, Decimal("0.2960"), *PHASE_K_COLLECTION),
}


def batch_profile(policy):
    try:
        return BATCH_PROFILES[policy.get("batch_profile", "standard")]
    except (KeyError, TypeError):
        raise ControlError("Unknown batch profile.") from None


def with_batch_profile(base, name):
    """Choose only a server-defined profile over the current standard policy."""
    if (name not in BATCH_PROFILES or not isinstance(base, dict)
        or base.get("budget_mode") != BATCH_BUDGET_MODE or base.get("batch_profile", "standard") != "standard"):
        raise ControlError("A valid standard batch policy is required for the pilot.")
    Policy(base).check_technical("improvement")
    if name == "standard":
        return base
    profile = BATCH_PROFILES[name]
    return {**base, "batch_profile": name, "max_calls": profile.calls,
            "run_token_limit": profile.tokens, "run_cny_limit": str(profile.reservation_cny)}


def message_token_estimate(messages):
    return len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 4096


class ControlError(RuntimeError):
    pass


def load_config():
    """Read server configuration without treating technical readiness as permission."""
    if not CONFIG_PATH.exists():
        return None
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None
        value["_config_digest"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        return value
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError, ControlError):
        return None


def load_policy():
    """Compatibility helper for execution-time revalidation."""
    value = load_config()
    try:
        Policy(value).check("improvement")
        return value
    except (ValueError, KeyError, TypeError, ArithmeticError, ControlError):
        return None


def analysis_readiness(value, purpose):
    checks = {
        "youtube": ("check_youtube", "YouTube 衍生分析用途记录缺失、范围不符或已失效。"),
        "provider": ("check_provider", "Qwen 第三方处理用途、披露及供应商条款尚未确认。"),
        "technical": ("check_technical", "模型、Endpoint、价格或 Token/费用边界尚未就绪。"),
    }
    result = {}
    for name, (method, reason) in checks.items():
        try:
            getattr(Policy(value), method)(purpose)
            result[name] = {"ready": True, "reason": ""}
        except (ValueError, KeyError, TypeError, ArithmeticError, ControlError):
            if name == "youtube" and isinstance(value, dict) and value.get("batch_profile") == PHASE_K:
                reason = "缺少有效的 Phase K 扩容授权记录（20 个视频、每个 50 条、最多分析 80 条）。"
            result[name] = {"ready": False, "reason": reason}
    result["ready"] = all(result[k]["ready"] for k in checks)
    result["collection_enabled"] = True
    result["payment_required"] = True
    return result


class Policy:
    def __init__(self, value):
        self.value = value

    def check_youtube(self, purpose):
        p = self.value
        if purpose not in {"improvement", "competitor"}:
            raise ControlError("Invalid research purpose.")
        needed = (SCOPES - {"third_party_qwen"}) | ({"competitor_comparison"} if purpose == "competitor" else set())
        if not isinstance(p, dict) or p.get("approved") is not True or not needed <= set(p.get("scopes", [])):
            raise ControlError("Applicable YouTube and third-party analysis permissions are not configured.")
        for key in ("approval_reference", "project_reference"):
            if not isinstance(p.get(key), str) or not p[key].strip():
                raise ControlError("Incomplete server-side approval/pricing record.")
        if p.get("source_scope") != "public_videos_any_channel":
            raise ControlError("The current automatic search requires approval covering unrelated public channels.")
        if p.get("batch_profile") == PHASE_K:
            scope = p.get("phase_k_scope")
            if (not isinstance(scope, dict) or scope.get("approved") is not True
                    or not isinstance(scope.get("approval_reference"), str)
                    or not scope["approval_reference"].strip()
                    or (scope.get("videos"), scope.get("comments_per_video")) != PHASE_K_COLLECTION
                    or scope.get("model_comments") != BATCH_PROFILES[PHASE_K].comments):
                raise ControlError("No recorded approval for Phase K collection and processing limits.")
        if p.get("approval_validity") == "no_expiry_confirmed" and p.get("expires_at") is None:
            if not p.get("approval_attestation"):
                raise ControlError("An explicit no-expiry confirmation is required.")
        else:
            expiry = datetime.fromisoformat(p["expires_at"].replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                raise ControlError("Approval expired or has no timezone.")
        return p

    def check_provider(self, purpose):
        p = self.value
        if (not isinstance(p, dict) or "third_party_qwen" not in p.get("scopes", [])
            or not isinstance(p.get("provider_terms_reference"), str) or not p["provider_terms_reference"].strip()
            or p.get("provider_region") != "cn-beijing" or p.get("raw_storage") != "memory_only"):
            raise ControlError("Third-party processing and provider terms are not confirmed.")
        return p

    def check_technical(self, purpose):
        p = self.value
        if not ANALYSIS_ENABLED or not isinstance(p, dict):
            raise ControlError("Technical analysis switch is off or configuration is missing.")
        if p.get("analysis_schema_version"):
            from evidence_analysis import VERSION
            if p["analysis_schema_version"] != VERSION:
                raise ControlError("The approved experiment configuration uses a different analysis contract.")
        for key in ("price_reference", "model"):
            if not isinstance(p.get(key), str) or not p[key].strip():
                raise ControlError("Incomplete technical configuration.")
        if p.get("prices_verified") is not True:
            raise ControlError("Unverified pricing configuration.")
        if p.get("budget_mode") == BATCH_BUDGET_MODE:
            from multi_comment_research import BATCH_PROMPT
            from evidence_analysis import VERSION
            profile = batch_profile(p)
            if (p.get("token_estimate_risk_acknowledged") is not True
                or p.get("analysis_schema_version") != VERSION
                or p.get("analysis_prompt_sha256") != hashlib.sha256(BATCH_PROMPT.encode()).hexdigest()
                or p.get("max_calls") != profile.calls or p.get("max_input_tokens") != BATCH_INPUT
                or p.get("max_output_tokens") != BATCH_OUTPUT
                or p.get("run_token_limit") != profile.tokens
                or Decimal(str(p["run_cny_limit"])) != profile.reservation_cny):
                raise ControlError("Invalid multi-comment request, prompt or budget configuration.")
        elif p.get("token_bound_verified") is not True or p.get("budget_mode") == KEYWORD_BUDGET_MODE:
            # Explicitly risk-accepted single-request experiment, not a verified
            # tokenizer or a hard monetary guarantee. Never permits batching.
            if (p.get("budget_mode") not in {"single_request_estimate", KEYWORD_BUDGET_MODE}
                or p.get("token_estimate_risk_acknowledged") is not True
                or p.get("max_calls") != 1
                or type(p.get("max_input_tokens")) is not int or not 1 <= p["max_input_tokens"] <= 8000
                or type(p.get("max_output_tokens")) is not int or not 1 <= p["max_output_tokens"] <= 1500
                or type(p.get("run_token_limit")) is not int or not 1 <= p["run_token_limit"] <= 9500
            ):
                raise ControlError("Unverified Token bounds permit only a separately acknowledged single-request experiment.")
            if p.get("budget_mode") == KEYWORD_BUDGET_MODE:
                from evidence_analysis import PROMPT, VERSION
                if (p.get("analysis_schema_version") != VERSION
                    or p.get("analysis_prompt_sha256") != hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()):
                    raise ControlError("Keyword analysis requires the pinned evidence contract and prompt.")
            elif (not isinstance(p.get("selected_review_id"), str) or not p["selected_review_id"].startswith("youtube:")
                or not isinstance(p.get("selected_text_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", p["selected_text_sha256"])
                or not isinstance(p.get("single_request_id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", p["single_request_id"])):
                raise ControlError("Unverified Token bounds permit only a separately acknowledged single-request experiment.")
        elif not isinstance(p.get("token_bound_reference"), str) or not p["token_bound_reference"].strip():
            raise ControlError("Verified Token bounds require supporting reference.")
        if p["model"] != QWEN_MODEL or p.get("enable_thinking") is not False or p.get("response_format") != "json_object":
            raise ControlError("First experiment requires the pinned Qwen snapshot and non-thinking JSON mode.")
        base = p.get("api_base_url", "")
        if base != QWEN_BASE_URL and (not isinstance(base, str) or not re.fullmatch(r"https://[A-Za-z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com/compatible-mode/v1", base)):
            raise ControlError("Only a verified Beijing endpoint is allowed.")
        for key, maximum in (("max_calls", 50), ("max_input_tokens", 16000), ("max_output_tokens", 3000), ("run_token_limit", 950000)):
            if type(p.get(key)) is not int or not 1 <= p[key] <= maximum:
                raise ControlError("Invalid request/token limits.")
        for key in ("input_cny_per_million", "output_cny_per_million", "daily_cny_limit", "run_cny_limit"):
            number = Decimal(str(p[key]))
            if not number.is_finite() or number <= 0:
                raise ControlError("Invalid monetary budget.")
        if Decimal(str(p["input_cny_per_million"])) != Decimal("0.8") or Decimal(str(p["output_cny_per_million"])) != Decimal("2"):
            raise ControlError("Prices do not match the verified Beijing non-thinking snapshot tier.")
        if any(Decimal(str(p[key])) > 1 for key in ("run_cny_limit", "daily_cny_limit")):
            raise ControlError("The first experiment is capped at CNY 1 per run and UTC day.")
        return p

    def check(self, purpose):
        self.check_youtube(purpose)
        self.check_provider(purpose)
        return self.check_technical(purpose)


class Execution:
    """Only constructed by the server after operator attestation and user consent.

    Reservations are never refunded, including on timeouts. No comment text or
    identifiers are persisted. Config evidence is an operator attestation, not
    an automatically verified grant of platform rights.
    """
    def __init__(self, policy, purpose, *, paid_confirmed=False, run_id, ledger_path=LEDGER_PATH, batch_messages=()):
        if paid_confirmed is not True:
            raise ControlError("Explicit confirmation is required before paid model requests.")
        self.policy = Policy(policy)
        self.purpose = purpose
        self.run_id = run_id
        self.ledger_path = Path(ledger_path)
        self.policy.check(purpose)
        self._batch_lock = Lock()
        plans = list(batch_messages)
        self._remaining_batches = [self._message_digest(messages) for messages in plans]
        self._planned_batch_count = len(self._remaining_batches)
        if policy.get("budget_mode") == BATCH_BUDGET_MODE:
            profile = batch_profile(policy)
            try:
                counts = [len(json.loads(messages[1]["content"])["reviews"]) for messages in plans]
            except (IndexError, KeyError, TypeError, ValueError):
                raise ControlError("Invalid frozen batch plan.") from None
            if (not counts or len(counts) > profile.calls or sum(counts) > profile.comments
                or any(not 1 <= count <= BATCH_SIZE for count in counts)
                or len(set(self._remaining_batches)) != len(counts)):
                raise ControlError("Multi-comment execution requires a frozen request plan within the selected profile.")
        if policy.get("budget_mode") == KEYWORD_BUDGET_MODE:
            raise ControlError("Bind the keyword execution to one validated source before making a request.")
        if policy.get("budget_mode") == "single_request_estimate":
            # Reuse the experiment identity across reruns: one reservation total,
            # including timeouts/failures. Paid consent remains mandatory.
            self.run_id = policy["single_request_id"]

    def check(self):
        p = self.policy.check(self.purpose)
        if p.get("_config_digest"):
            current = load_policy()
            if current is None or current.get("_config_digest") != p["_config_digest"]:
                raise ControlError("Server approval configuration changed or was revoked.")
            if p.get("budget_mode") == BATCH_BUDGET_MODE and (
                with_batch_profile(current, p.get("batch_profile", "standard")) != p
            ):
                raise ControlError("Server batch profile changed or was revoked.")
        return p

    @staticmethod
    def _message_digest(messages):
        return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    @property
    def reserved_batch_count(self):
        with self._batch_lock:
            return self._planned_batch_count - len(self._remaining_batches)

    def reserve(self, payload):
        try:
            if self.policy.value.get("budget_mode") == BATCH_BUDGET_MODE:
                messages = payload.get("messages")
                digest = self._message_digest(messages)
                with self._batch_lock:
                    if not self._remaining_batches or digest != self._remaining_batches[0]:
                        raise ControlError("The batch differs from the next frozen request.")
                    if (not isinstance(messages, list) or not messages or messages[0].get("role") != "system"
                        or hashlib.sha256(messages[0]["content"].encode()).hexdigest() != self.policy.value["analysis_prompt_sha256"]):
                        raise ControlError("The batch prompt does not match the approved configuration.")
                    cost = self._reserve(payload)
                    self._remaining_batches.pop(0)
                    return cost
            return self._reserve(payload)
        except (OSError, sqlite3.Error):
            raise ControlError("Budget ledger unavailable; no model request was sent.") from None

    def _reserve(self, payload):
        p = self.check()
        if (payload.get("model") != p["model"] or payload.get("enable_thinking") is not False
            or payload.get("max_tokens") != p["max_output_tokens"] or payload.get("stream") is not False
            or payload.get("response_format") != {"type": p["response_format"]}
            or not isinstance(payload.get("messages"), list)):
            raise ControlError("Actual request does not match the verified billing configuration.")
        if p.get("budget_mode") == "single_request_estimate":
            try:
                messages = payload["messages"]
                data = json.loads(messages[1]["content"])
                if p.get("analysis_schema_version") or "evidence" in data:
                    from evidence_analysis import evidence_message
                    text = "".join(span["text"] for span in data["evidence"])
                    if data != evidence_message(text):
                        raise ValueError()
                else:
                    text = data["review_text"]
                if len(messages) != 2 or messages[1]["role"] != "user" or hashlib.sha256(text.encode("utf-8")).hexdigest() != p["selected_text_sha256"]:
                    raise ValueError()
                if p.get("analysis_prompt_sha256") and hashlib.sha256(messages[0]["content"].encode("utf-8")).hexdigest() != p["analysis_prompt_sha256"]:
                    raise ValueError()
            except (KeyError, IndexError, TypeError, ValueError, AttributeError):
                raise ControlError("Only the selected, unchanged real comment is allowed in this experiment.") from None
        # Byte count plus template allowance is only an estimate unless backed
        # by the separately verified tokenizer reference. Single-request mode
        # explicitly accepts this uncertainty; it must never enable batching.
        upper = message_token_estimate(payload["messages"])
        if upper > p["max_input_tokens"]:
            raise ControlError("Input exceeds the configured token estimate/bound; no request was sent.")
        worst = (Decimal(str(p["input_cny_per_million"])) * p["max_input_tokens"] + Decimal(str(p["output_cny_per_million"])) * p["max_output_tokens"]) / 1000000
        day = datetime.now(timezone.utc).date().isoformat()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.ledger_path, timeout=5)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS reservations(day TEXT, run TEXT, cost TEXT, tokens INTEGER NOT NULL DEFAULT 0)")
            if "tokens" not in {r[1] for r in db.execute("PRAGMA table_info(reservations)")}:
                db.execute("ALTER TABLE reservations ADD COLUMN tokens INTEGER NOT NULL DEFAULT 0")
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT day,run,cost,tokens FROM reservations").fetchall()
            run = [r for r in rows if r[1] == self.run_id]
            total = lambda rs: sum((Decimal(r[2]) for r in rs), Decimal(0))
            daily_used = total(r for r in rows if r[0] == day)
            if p.get("batch_profile") == PHASE_K and not run:
                planned = self._planned_batch_count * worst
                if daily_used + planned > Decimal(str(p["daily_cny_limit"])):
                    raise ControlError("The UTC daily budget cannot cover the planned run.")
            tokens = p["max_input_tokens"] + p["max_output_tokens"]
            if len(run) >= p["max_calls"] or sum(r[3] for r in run) + tokens > p["run_token_limit"] or total(run) + worst > Decimal(str(p["run_cny_limit"])) or daily_used + worst > Decimal(str(p["daily_cny_limit"])):
                raise ControlError("Request or monetary budget reached; no further request was sent.")
            db.execute("INSERT INTO reservations(day,run,cost,tokens) VALUES(?,?,?,?)", (day, self.run_id, str(worst), tokens))
        return worst
