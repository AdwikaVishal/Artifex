"""
Centralised NATS subject constants.
All inter-agent communication uses these subjects so that renaming
is a single-file change.
"""


class Subjects:
    # ── Planner ───────────────────────────────────────────────────────────────
    PLANNER_REQUEST = "agent.planner.request"
    PLANNER_REPLAN = "agent.planner.replan"

    # ── Retriever ─────────────────────────────────────────────────────────────
    RETRIEVER_INBOX = "agent.retriever.inbox"

    # ── Executor ──────────────────────────────────────────────────────────────
    EXECUTOR_INBOX = "agent.executor.inbox"

    # ── Validator ─────────────────────────────────────────────────────────────
    VALIDATOR_INBOX = "agent.validator.inbox"
    VALIDATOR_FAILED = "validator.failed"

    # ── Supervisor ────────────────────────────────────────────────────────────
    HEARTBEAT_WILDCARD = "agent.*.heartbeat"

    # ── Recovery ─────────────────────────────────────────────────────────────
    RECOVERY_INBOX = "agent.recovery.inbox"

    # ── API result bus ────────────────────────────────────────────────────────
    API_RESULT = "api.result"

    # ── Foster care ───────────────────────────────────────────────────────────
    FOSTER_PLACEMENTS = "foster.placements"

    # ── Validator subjects (per-model instance) ───────────────────────────────
    VALIDATOR_A_INBOX = "agent.validator_a.inbox"
    VALIDATOR_B_INBOX = "agent.validator_b.inbox"

    # ── Executor subjects (per-capability instance) ───────────────────────────
    EXECUTOR_GENERAL_INBOX  = "agent.executor.inbox"          # load-balanced queue group
    EXECUTOR_SEARCH_INBOX   = "agent.executor_search.inbox"   # search-capable executor
    EXECUTOR_TOOLS_INBOX    = "agent.executor_tools.inbox"    # http/shell/file executor

    # ── Agent-voting executor subjects (per-model instance) ───────────────────
    EXECUTOR_LLAMA_INBOX    = "agent.executor_llama.inbox"    # llama-3.1-8b-instant
    EXECUTOR_GEMMA_INBOX    = "agent.executor_gemma.inbox"    # gemma2-9b-it
    EXECUTOR_MIXTRAL_INBOX  = "agent.executor_mixtral.inbox"  # mixtral-8x7b-32768

    # ── Agent performance feedback ────────────────────────────────────────────
    AGENT_PERFORMANCE = "agent.performance"

    # ── Agent registration / discovery ───────────────────────────────────────
    AGENT_REGISTER = "agent.register"

    # ── Emergent swarm / auction subjects ────────────────────────────────────
    TASK_ANNOUNCEMENT = "swarm.task.announce"
    TASK_BID          = "swarm.task.bid"
    TEAM_PROPOSAL     = "swarm.team.propose"
    TEAM_VOTE         = "swarm.team.vote"
    TEAM_FORMED       = "swarm.team.formed"
    TASK_COMPLETION   = "swarm.task.complete"
    TASK_FAILED       = "swarm.task.failed"

    @staticmethod
    def heartbeat(agent_name: str) -> str:
        return f"agent.{agent_name}.heartbeat"

    @staticmethod
    def inbox(agent_name: str) -> str:
        return f"agent.{agent_name}.inbox"
