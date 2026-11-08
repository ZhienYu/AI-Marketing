"""One authorized, blinded comparison. The production research entry is separate."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from random import SystemRandom
from time import monotonic

from analysis_control import (
    BATCH_INPUT, BATCH_OUTPUT, ControlError, Execution, LEDGER_PATH, QWEN_MODEL,
    load_policy, message_token_estimate,
)
from business_report_live import build_business_view
from classify_reviews import ClassificationError, TOKEN_FIELDS, _send_qwen, extract_usage, load_local_settings
from evidence_analysis import VERSION
from multi_comment_research import BATCH_PROMPT, batch_messages, entity_source_observations, map_response, process_batch_comment
from research_quality import render_live_specialist
from session_memory import SessionResult


CANDIDATE = "qwen3.7-plus-2026-05-26"
RATES = {CANDIDATE: ("2", "8"), QWEN_MODEL: ("0.8", "2")}
RUN_ID = "phase-jb-frozen-v1"
RUN_LIMIT = Decimal("0.1824")
TTL = 900
MANIFEST = Path(__file__).with_name("model_benchmark_manifest.json")
MANIFEST_SHA256 = "aac387c3192be8ae130bbbc64a1270c5e1bf173e2ee5ca879a2fc71c70feadaf"
RAW_SCORES = ("supported", "missed", "unsupported", "entity_errors", "role_errors",
              "json_ok", "schema_ok", "missing_items")
REPORT_SCORES = ("retained", "missed", "unsupported", "misattributed", "duplicates", "traceable",
                 "specificity", "credibility", "readability")


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _locked_batches(batches, manifest):
    if _digest(BATCH_PROMPT) != manifest["prompt_sha256"] or VERSION != manifest["schema"]:
        raise ControlError("The benchmark prompt or schema changed.")
    root = Path(__file__).parent
    if any(hashlib.sha256((root / filename).read_bytes()).hexdigest() != digest
           for filename, digest in manifest["python_sha256"].items()):
        raise ControlError("The frozen post-processing code changed.")
    if len(batches) != 3 or len(manifest["batches"]) != 3:
        raise ControlError("The benchmark requires three frozen batches.")
    locked = []
    for (topic, rows), expected in zip(batches, manifest["batches"]):
        if topic != expected["topic"] or len(rows) != 4 or len(expected["sources"]) != 4:
            raise ControlError("The benchmark topic or batch size changed.")
        clean_rows = []
        for row, record in zip(rows, expected["sources"]):
            video, comment = record["video_id"], record["comment_id"]
            text = row.get("review_text")
            if (row.get("video_id") != video or row.get("comment_id") != comment
                    or not isinstance(text, str) or _digest(text) != record["text_sha256"]):
                raise ControlError("A benchmark source does not match the frozen manifest.")
            clean_rows.append({
                "video_id": video, "comment_id": comment, "review_id": f"youtube:{comment}",
                "review_text": text, "published_at": "", "source_platform": "youtube",
                "source_url": f"https://www.youtube.com/watch?v={video}&lc={comment}", "is_synthetic": False,
            })
        messages = batch_messages(clean_rows, topic)
        if message_token_estimate(messages) > BATCH_INPUT:
            raise ControlError("A frozen benchmark input exceeds the token estimate limit.")
        locked.append((topic, clean_rows, messages))
    return locked


class _BenchmarkExecution(Execution):
    """Reuse the production transaction and UTC daily cap with a fixed six-call plan."""

    def __init__(self, policy, ledger_path, plans, deadline):
        self.policy_digest = policy["_config_digest"]
        self.day = datetime.now(timezone.utc).date()
        self.ledger_path = Path(ledger_path)
        self.run_id = RUN_ID
        self.deadline = deadline
        self.plan = [(model, self._message_digest(messages))
                     for model in RATES for _, _, messages in plans]
        self.index = 0

    def check(self):
        policy = load_policy()
        if (policy is None or policy["_config_digest"] != self.policy_digest
                or datetime.now(timezone.utc).date() != self.day or monotonic() >= self.deadline):
            raise ControlError("Benchmark authorization or its run window is no longer valid.")
        model = self.plan[min(self.index, len(self.plan) - 1)][0]
        input_rate, output_rate = RATES[model]
        return {**policy, "model": model, "input_cny_per_million": input_rate,
                "output_cny_per_million": output_rate, "max_calls": 6,
                "run_token_limit": 6 * (BATCH_INPUT + BATCH_OUTPUT), "run_cny_limit": str(RUN_LIMIT)}

    def reserve(self, payload):
        if self.index >= len(self.plan):
            raise ControlError("The benchmark call limit was reached.")
        model, digest = self.plan[self.index]
        if payload.get("model") != model or self._message_digest(payload.get("messages")) != digest:
            raise ControlError("The benchmark request does not match the frozen plan.")
        reservation = self._reserve(payload, expected_run_calls=self.index)
        self.index += 1
        return reservation


class BenchmarkSession:
    """Expose two blind score stages and expire source material and model labels."""

    def __init__(self, raw, reports, identities, fees, deadline):
        self._data = SessionResult(
            {"raw": raw, "reports": reports, "identities": identities, "fees": fees},
            ttl=max(0, deadline - monotonic()),
        )
        self._scores = {}

    def raw_outputs(self):
        return self._data.snapshot().get("raw", {})

    def reports(self):
        if "raw" not in self._scores:
            raise ControlError("Complete blind scoring of the raw outputs first.")
        return self._data.snapshot().get("reports", {})

    def score(self, stage, scores):
        fields = {"raw": RAW_SCORES, "report": REPORT_SCORES}
        if (stage not in fields or stage in self._scores or not self._data.get("identities")
                or stage == "report" and "raw" not in self._scores):
            raise ControlError("The blind scoring stage is unavailable.")
        if set(scores) != {"A", "B"} or any(
            set(row) != set(fields[stage]) or any(
                type(value) is not int or value < 0
                or key in {"specificity", "credibility", "readability"} and value > 2
                for key, value in row.items())
            for row in scores.values()
        ):
            raise ControlError("Only the numeric benchmark aggregates are accepted.")
        self._scores[stage] = {label: dict(row) for label, row in scores.items()}

    def reveal(self):
        snapshot = self._data.snapshot()
        if set(self._scores) != {"raw", "report"} or "identities" not in snapshot:
            raise ControlError("Both blind score stages must be completed before reveal.")
        return {model: {**snapshot["fees"][label], **{stage: rows[label].copy()
                for stage, rows in self._scores.items()}}
                for label, model in snapshot["identities"].items()}

    def clear(self):
        self._data.clear()


def _report(topic, rows, mapped, execution, model):
    state = {"purpose": "improvement", "model": model, "schema_version": VERSION,
             "results": [], "failures": [], "source_observations": [], "submitted": len(rows)}
    for row, raw in mapped:
        processed = process_batch_comment(raw, row)
        if processed["status"] == "Invalid":
            state["failures"].append({"review_id": row["review_id"], "processing": processed})
            observation = entity_source_observations(processed, row)
            if observation:
                state["source_observations"].append(observation)
        else:
            analysis = processed["normalized"]
            state["results"].append({**row, "processing": processed, "analysis": analysis,
                                     "brand": analysis["brand"]["name"]})
    formal = render_live_specialist(state, execution=execution, statistics_only=True)
    return build_business_view(topic, state, formal, rows)


def run_benchmark(batches, *, data_confirmed=False, paid_confirmed=False, workspace_confirmed=False):
    """Run only after all three confirmations. Inputs are ordered in-memory rows."""
    if not all(flag is True for flag in (data_confirmed, paid_confirmed, workspace_confirmed)):
        raise ControlError("Benchmark data use, paid cap and Beijing workspace require explicit confirmation.")
    policy = load_policy()
    if policy is None:
        raise ControlError("The local data use and Beijing provider policy is unavailable.")
    manifest_bytes = MANIFEST.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256:
        raise ControlError("The frozen manifest changed.")
    manifest = json.loads(manifest_bytes)
    plans = _locked_batches(batches, manifest)
    deadline = monotonic() + TTL
    execution = _BenchmarkExecution(policy, LEDGER_PATH, plans, deadline)
    settings = load_local_settings()
    labels = ["A", "B"]
    SystemRandom().shuffle(labels)
    identities = dict(zip(labels, RATES))
    raw_outputs, reports, fees = {}, {}, {}
    try:
        for label, model in identities.items():
            raw_outputs[label], reports[label] = [], []
            fees[label] = {"prompt_tokens": 0, "completion_tokens": 0}
            for topic, rows, messages in plans:
                payload = {"model": model, "messages": messages, "max_tokens": BATCH_OUTPUT,
                           "enable_thinking": False, "stream": False, "temperature": 0,
                           "response_format": {"type": "json_object"}}
                body = _send_qwen(payload, settings, automatic=execution)
                execution.check()
                usage = extract_usage(body)
                choice, = body["choices"]
                message = choice["message"]
                content = message.get("content")
                if (body.get("model") != model or message.get("reasoning_content")
                        or choice.get("finish_reason") != "stop"
                        or not isinstance(content, str) or set(usage) != set(TOKEN_FIELDS)
                        or usage["prompt_tokens"] > BATCH_INPUT or usage["completion_tokens"] > BATCH_OUTPUT):
                    raise ControlError("The provider returned a different model, mode or token envelope.")
                for key in fees[label]:
                    fees[label][key] += usage[key]
                decoded = json.loads(content)
                if not isinstance(decoded, dict):
                    raise ControlError("The provider returned content outside JSON Object mode.")
                raw_outputs[label].append((topic, "stop", content))
                try:
                    mapped = map_response(decoded, rows)
                except ValueError:
                    mapped = []
                reports[label].append(_report(topic, rows, mapped, execution, model))
            i, o = map(Decimal, RATES[model])
            fees[label]["estimated_cny"] = str((i * fees[label]["prompt_tokens"]
                                               + o * fees[label]["completion_tokens"]) / 1_000_000)
        execution.check()
    except (ClassificationError, ControlError, KeyError, TypeError, ValueError, AttributeError, OSError):
        raise ControlError("Benchmark stopped. Check reservations and provider billing before any new authorization.") from None
    return BenchmarkSession(raw_outputs, reports, identities, fees, deadline)
