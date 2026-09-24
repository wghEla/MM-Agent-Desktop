"""Agent Loop：task 级 tool-calling 执行器（总方案 §19 最低闭环）。

成功判定（declared != enforced；外审 P0/P1 修复后强化）——Task SUCCEEDED 必须全部满足：
  expected artifacts 存在 ∧ schema 校验通过 ∧ 内容封存 ∧ 状态事务成功（RUNNING + 租约 CAS）。
模型说"我完成了"不算完成。

并发语义（外审 P1-1/P1-2）：
- run() 入口只接受 PENDING/READY/QUEUED；终态/暂停态不隐式复活（重试走 retry_task）；
- QUEUED→RUNNING 是原子 CAS 租约：两个执行者只有一个能拿到；
- 全部状态迁移携带 owner_token，非持有者一律拒绝。

取消语义（外审 P1-3/P1-4）：
- DB CANCEL_REQUESTED 是持久真相，CancellationToken 是快速唤醒；
- 验收前复查 DB 取消状态；provider 返回 CANCELLED → 直接取消，不进入成功验收；
- 取消收口用 InvocationStatus.CANCELLED（不再洗成 FAILED）。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from mmagent.agent.context import ContextManifest
from mmagent.agent.errors import (
    ErrorKind,
    MMAgentError,
    RateLimitError,
    TaskCancelled,
    TaskLeaseHeld,
    TaskNotRunnable,
)
from mmagent.providers.base import BaseProvider
from mmagent.providers.normalized import (
    NormalizedMessage,
    NormalizedToolCall,
    StopReason,
    TextPart,
    Usage,
)
from mmagent.runtime.cancellation import CancellationToken
from mmagent.state import events, repositories
from mmagent.state.db import Database
from mmagent.state.models import InvocationStatus, TaskStatus, ToolCallStatus
from mmagent.tools.registry import ToolRegistry
from mmagent.tools.tool_protocol import ToolContext
from mmagent.workspace.artifacts import (
    ArtifactCheck,
    ExpectedArtifact,
    build_artifact_rows,
    seal_artifacts,
    verify_expected_artifacts,
)
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker

_MAX_TOOL_RESULT_CHARS = 30_000


@dataclass
class AgentTask:
    """一次 agent 任务的完整规格（编排层构造，loop 执行）。"""

    task_id: str
    node_key: str
    role_id: str
    system_prompt: str
    instructions: str
    model: str
    provider_profile: str = "default"
    reasoning: str | None = None
    expected_artifacts: list[ExpectedArtifact] = field(default_factory=list)
    max_turns: int = 16
    context_manifest: ContextManifest | None = None


@dataclass
class TaskOutcome:
    task_id: str
    status: TaskStatus
    error: str | None = None
    error_kind: ErrorKind | None = None
    retryable: bool = False
    artifacts: list[ArtifactCheck] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    turns: int = 0
    result: dict[str, Any] = field(default_factory=dict)


class AgentLoop:
    def __init__(
        self,
        db: Database,
        provider: BaseProvider,
        registry: ToolRegistry,
        permission: PermissionChecker,
        policy: PathPolicy,
        cancel: CancellationToken | None = None,
    ):
        self.db = db
        self.provider = provider
        self.registry = registry
        self.permission = permission
        self.policy = policy
        self.cancel = cancel or CancellationToken()

    # ------------------------------------------------------------------
    async def run(self, spec: AgentTask) -> TaskOutcome:
        task = repositories.get_task(self.db, spec.task_id)
        run_id = task.run_id

        # 1) 严格入口：只允许 PENDING/READY/QUEUED 启动（外审 P1-2，不吞异常不复活）
        if task.status not in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.QUEUED):
            raise TaskNotRunnable(
                f"任务 {spec.task_id} 状态为 {task.status.value}，不允许启动；"
                "重试请走 retry_task()（显式复活）"
            )
        # 2) 启动前校验期望产物的写权限（生产者必须有权写它声明要产的位置，外审 P1-7）
        for exp in spec.expected_artifacts:
            self.permission.check_write(exp.rel_path)
        if task.status is TaskStatus.PENDING:
            task = repositories.transition_task(self.db, spec.task_id, TaskStatus.READY)
        if task.status is TaskStatus.READY:
            task = repositories.transition_task(self.db, spec.task_id, TaskStatus.QUEUED)
        # 3) 租约 CAS（外审 P1-1）：抢不到就拒绝，绝不并行执行同一任务
        owner = repositories.new_owner_token()
        if not repositories.acquire_task_lease(self.db, spec.task_id, owner):
            raise TaskLeaseHeld(f"任务已被其他执行者持有: {spec.task_id}")

        invocation_id: str | None = None
        usage = Usage()
        turns = 0
        effective_model = self.provider.resolve_model(spec.model)
        effective_reasoning = self.provider.resolve_reasoning(spec.reasoning)
        try:
            # attempt+invocation+事件在同一事务（外审 round2 gate #4）
            attempt, invocation_id = repositories.begin_task_attempt(
                self.db,
                spec.task_id,
                owner,
                role_id=spec.role_id,
                provider_profile=spec.provider_profile,
                model=effective_model,
                reasoning=effective_reasoning,
                context_manifest=spec.context_manifest.to_dict() if spec.context_manifest else None,
            )

            messages = self._bootstrap_messages(spec)
            seq = 0
            for m in messages:
                seq += 1
                self._persist_message(invocation_id, m, seq=seq)
            tools = self.registry.normalized_tools(self.permission.perms.allowed_tools)
            tool_ctx = ToolContext(
                policy=self.policy,
                permission=self.permission,
                cancel=self.cancel,
                task_id=spec.task_id,
                invocation_id=invocation_id,
                extra={"owner_token": owner},
            )
            tool_seq = 0

            for turns in range(1, spec.max_turns + 1):  # noqa: B007 (turns 记录轮次)
                self.cancel.check()
                self._check_db_cancelled(spec.task_id)
                response = await self.provider.generate(
                    messages,
                    tools,
                    model=effective_model,
                    reasoning=effective_reasoning,
                )
                usage = Usage(
                    input_tokens=usage.input_tokens + response.usage.input_tokens,
                    output_tokens=usage.output_tokens + response.usage.output_tokens,
                )
                seq += 1
                self._persist_message(invocation_id, response.message, seq=seq)
                messages.append(response.message)

                if response.stop_reason == StopReason.CANCELLED:
                    # provider 明确取消 → 绝不进入成功验收（外审 P1-4）
                    raise TaskCancelled("provider 返回 stop_reason=CANCELLED")
                if not response.message.tool_calls:
                    break  # 终文本：进入验收
                task = repositories.transition_task(
                    self.db, spec.task_id, TaskStatus.WAITING_TOOL, owner_token=owner
                )
                for tc in response.message.tool_calls:
                    self.cancel.check()
                    self._check_db_cancelled(spec.task_id)  # 多工具调用逐个复查（外审 round2 gate #3）
                    started_iso = repositories.now_iso()
                    t0 = time.monotonic()
                    result = await self.registry.invoke(tc.name, tc.arguments_json, tool_ctx)
                    ended_iso = repositories.now_iso()
                    elapsed = round(time.monotonic() - t0, 3)
                    tool_seq += 1
                    self._persist_tool_call(
                        invocation_id, seq=tool_seq, call=tc, result=result,
                        task_id=spec.task_id, run_id=run_id,
                        started_at=started_iso, ended_at=ended_iso, elapsed_s=elapsed,
                    )
                    messages.append(
                        NormalizedMessage(
                            role="tool",
                            content=[TextPart(text=result.content or result.error or "")],
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
                    seq += 1
                    self._persist_message(invocation_id, messages[-1], seq=seq)
                task = self._safe_back_to_running(spec.task_id, owner)
            else:
                raise MMAgentError(f"agent 超过最大轮数 {spec.max_turns} 仍未给出终稿")

            # 4) 验收：取消复查（DB + token）→ 校验 → 封存 → 事务提交
            self.cancel.check()
            self._check_db_cancelled(spec.task_id)
            checks = verify_expected_artifacts(self.policy, spec.expected_artifacts)
            sealed = seal_artifacts(self.policy, checks, spec.task_id)
            rows = build_artifact_rows(self.db, spec.task_id, checks, sealed)
            final_text = messages[-1].text[:2000] if messages else ""
            task = repositories.commit_task_success(
                self.db,
                spec.task_id,
                artifacts=rows,
                result={"final_text": final_text, "turns": turns},
                owner_token=owner,
            )
            repositories.finish_invocation(
                self.db, invocation_id, InvocationStatus.SUCCEEDED,
                usage={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
            )
            return TaskOutcome(
                task_id=spec.task_id,
                status=TaskStatus.SUCCEEDED,
                artifacts=checks,
                usage=usage,
                turns=turns,
                result={"final_text": final_text},
            )
        except TaskCancelled as e:
            return self._cancelled(spec, invocation_id, e, usage=usage, owner=owner)
        except asyncio.CancelledError:
            # 外部 asyncio 取消：落 CANCELLED 后按 asyncio 语义上抛
            self._cancelled(
                spec, invocation_id, TaskCancelled("asyncio cancelled"), usage=usage, owner=owner
            )
            raise
        except RateLimitError as e:
            # 限流不是任务失败：回队列 + 释放租约（旧执行者释放后不得再触碰）
            events.append_event(
                self.db, "task.rate_limited", {"retry_after_s": e.retry_after_s},
                run_id=run_id, task_id=spec.task_id, invocation_id=invocation_id,
            )
            if invocation_id is not None:
                repositories.finish_invocation(
                    self.db, invocation_id, InvocationStatus.FAILED, error=str(e),
                    usage={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
                )
            # 原子收口：RUNNING→QUEUED；若取消已先到 → CANCELLED（外审 round2 gate #3）
            final = repositories.release_after_rate_limit(self.db, spec.task_id, owner)
            return TaskOutcome(
                task_id=spec.task_id, status=final, error=str(e),
                error_kind=ErrorKind.PROVIDER_RATE_LIMIT,
                retryable=(final is TaskStatus.QUEUED), usage=usage, turns=turns,
            )
        except MMAgentError as e:
            return self._fail(spec, invocation_id, e, usage=usage, owner=owner)
        except Exception as e:  # 未归类异常：FAILED + INTERNAL
            err = MMAgentError(f"内部错误: {e!r}")
            return self._fail(spec, invocation_id, err, usage=usage, owner=owner)

    # ------------------------------------------------------------------
    def _check_db_cancelled(self, task_id: str) -> None:
        """DB 取消状态是持久真相：CANCEL_REQUESTED/CANCELLED 一律中止（外审 P1-3）。"""
        row = self.db.query_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise LookupError(task_id)
        st = TaskStatus(row["status"])
        if st in (TaskStatus.CANCEL_REQUESTED, TaskStatus.CANCELLED):
            raise TaskCancelled(f"任务已被请求取消（DB 状态 {st.value}）")

    def _safe_back_to_running(self, task_id: str, owner: str) -> Any:
        """WAITING_TOOL → RUNNING；若期间被置 CANCEL_REQUESTED，抛 TaskCancelled 而不是状态错误。"""
        try:
            return repositories.transition_task(
                self.db, task_id, TaskStatus.RUNNING, owner_token=owner
            )
        except Exception as e:
            row = self.db.query_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
            if row is not None and TaskStatus(row["status"]) in (
                TaskStatus.CANCEL_REQUESTED,
                TaskStatus.CANCELLED,
            ):
                raise TaskCancelled(f"工具执行期间被取消（{row['status']}）") from e
            raise

    def _cancelled(
        self,
        spec: AgentTask,
        invocation_id: str | None,
        err: TaskCancelled,
        *,
        usage: Usage,
        owner: str,
    ) -> TaskOutcome:
        t = repositories.mark_task_cancelled(
            self.db, spec.task_id, owner_token=owner, reason=str(err)
        )
        if invocation_id is not None:
            repositories.finish_invocation(
                self.db,
                invocation_id,
                InvocationStatus.CANCELLED,  # 外审 P2-2
                error=str(err),
                usage={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
            )
        return TaskOutcome(
            task_id=spec.task_id,
            status=t.status,
            error=f"[{err.kind.value}] {err}",
            error_kind=err.kind,
            usage=usage,
        )

    def _fail(
        self,
        spec: AgentTask,
        invocation_id: str | None,
        err: MMAgentError,
        *,
        usage: Usage,
        owner: str,
    ) -> TaskOutcome:
        try:
            t = repositories.mark_task_failed(
                self.db, spec.task_id, error=f"[{err.kind.value}] {err}", owner_token=owner
            )
        except Exception:
            # 状态已被并发改变（如 CANCEL_REQUESTED）：取消优先，不得洗成 FAILED（外审 P1-3）
            row = self.db.query_one("SELECT status FROM tasks WHERE id = ?", (spec.task_id,))
            if row is not None and TaskStatus(row["status"]) is TaskStatus.CANCEL_REQUESTED:
                return self._cancelled(
                    spec, invocation_id, TaskCancelled("取消请求优先于失败"), usage=usage, owner=owner
                )
            t = repositories.get_task(self.db, spec.task_id)
        if invocation_id is not None:
            repositories.finish_invocation(
                self.db, invocation_id, InvocationStatus.FAILED, error=str(err),
                usage={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
            )
        return TaskOutcome(
            task_id=spec.task_id,
            status=t.status,
            error=f"[{err.kind.value}] {err}",
            error_kind=err.kind,
            usage=usage,
        )

    def _bootstrap_messages(self, spec: AgentTask) -> list[NormalizedMessage]:
        parts = [spec.instructions]
        if spec.context_manifest:
            parts.append("\n" + spec.context_manifest.render())
        return [
            NormalizedMessage(role="system", content=[TextPart(text=spec.system_prompt)]),
            NormalizedMessage(role="user", content=[TextPart(text="\n".join(parts))]),
        ]

    def _persist_message(self, invocation_id: str, msg: NormalizedMessage, *, seq: int) -> None:
        self.db.execute(
            "INSERT INTO messages(invocation_id, seq, role, content_json) VALUES (?,?,?,?)",
            (invocation_id, seq, msg.role, msg.model_dump_json()),
        )

    def _persist_tool_call(
        self,
        invocation_id: str,
        *,
        seq: int,
        call: NormalizedToolCall,
        result: Any,
        task_id: str | None = None,
        run_id: str | None = None,
        started_at: str = "",
        ended_at: str = "",
        elapsed_s: float = 0.0,
    ) -> None:
        status = ToolCallStatus.OK if result.ok else ToolCallStatus.ERROR
        if getattr(result, "meta", {}).get("denied"):
            status = ToolCallStatus.DENIED
        if getattr(result, "meta", {}).get("timed_out"):
            status = ToolCallStatus.TIMEOUT
        tid = f"tc_{uuid.uuid4().hex[:12]}"
        self.db.execute(
            "INSERT INTO tool_calls(id, invocation_id, seq, name, args_json, result_json,"
            " status, error, started_at, ended_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                invocation_id,
                seq,
                call.name,
                call.arguments_json,
                json.dumps(result.meta, ensure_ascii=False),
                status.value,
                result.error,
                started_at or repositories.now_iso(),
                ended_at or repositories.now_iso(),
            ),
        )
        events.append_event(
            self.db,
            "tool.call",
            {
                "name": call.name,
                "status": status.value,
                "error": (result.error or "")[:200],
                "elapsed_s": elapsed_s,
            },
            invocation_id=invocation_id,
            task_id=task_id,
            run_id=run_id,
        )
        # 截断过长的工具结果再回填模型
        if result.content and len(result.content) > _MAX_TOOL_RESULT_CHARS:
            result.content = result.content[:_MAX_TOOL_RESULT_CHARS] + "\n…(截断)"
