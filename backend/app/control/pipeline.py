"""
SLA Guardian - Policy Execution Pipeline
Coordinates the closed-loop control sequence:
[NetworkState] -> Policy.predict -> SafetyShield.validate -> Simulator.step -> Evaluator.evaluate_transition
Enforces that no rejected proposal ever touches the network simulator.
"""

from typing import Optional, Tuple, Any
from pydantic import BaseModel, Field

from ..schemas.config import RunConfig
from ..schemas.state import NetworkState
from ..schemas.actions import ProposedAction, ExecutedAction, SafetyResult, SafetyValidationStatus
from ..schemas.metrics import StepMetrics
from ..interfaces.policy import PolicyInterface, EvaluatorInterface
from ..interfaces.simulator import SimulatorInterface
from .safety_shield import SafetyShield


class DecisionRecord(BaseModel):
    """
    Auditable log of a single policy-execution and safety validation cycle.
    """
    step: int
    sim_time_sec: float
    policy_id: str
    safety_result: SafetyResult
    accepted: bool
    rejection_reason: Optional[str] = None
    step_metrics: Optional[StepMetrics] = None


class PolicyExecutionPipeline:
    """
    Safe Policy Execution Orchestrator.
    Sandwiches the Safety Shield between arbitrary allocation policies and the network simulator.
    """

    def __init__(
        self,
        simulator: SimulatorInterface,
        evaluator: Optional[EvaluatorInterface] = None,
        safety_shield: Optional[SafetyShield] = None,
        config: Optional[RunConfig] = None,
    ):
        self.simulator = simulator
        self.evaluator = evaluator
        self.safety_shield = safety_shield or SafetyShield()
        self.config = config

    def execute_step(
        self,
        current_state: NetworkState,
        policy: PolicyInterface,
    ) -> Tuple[NetworkState, DecisionRecord]:
        """
        Executes one safe policy iteration:
        1. Queries policy for ProposedAction.
        2. Validates proposal with SafetyShield -> SafetyResult.
        3. If REJECTED:
           - Simulator clock does NOT advance.
           - Returns current_state and DecisionRecord with accepted=False.
        4. If ACCEPTED:
           - Advances simulator with ExecutedAction -> (next_state, diag).
           - Computes StepMetrics via evaluator.
           - Returns next_state and DecisionRecord with accepted=True.
        """
        step = current_state.step
        sim_time = current_state.sim_time_sec

        # 1. Query policy proposal
        try:
            proposal: ProposedAction = policy.predict(current_state)
        except Exception as e:
            # Handle malformed proposal at policy boundary
            dummy_prop = ProposedAction(
                radio_allocations={s: 0.0 for s in current_state.slice_states},
                compute_allocations={s: 0.0 for s in current_state.slice_states},
                priorities={s: 1 for s in current_state.slice_states},
                policy_id=policy.policy_id,
            )
            rejection = self.safety_shield._build_rejection(
                dummy_prop, step, f"Policy predict() raised exception: {str(e)}"
            )
            record = DecisionRecord(
                step=step,
                sim_time_sec=sim_time,
                policy_id=policy.policy_id,
                safety_result=rejection,
                accepted=False,
                rejection_reason=f"Policy exception: {e}",
                step_metrics=None,
            )
            return current_state, record

        # 2. Safety Shield validation & projection
        safety_result: SafetyResult = self.safety_shield.validate(
            proposed_action=proposal,
            network_state=current_state,
            config=self.config,
        )

        # 3. Intercept Rejections: Do NOT advance simulator
        if safety_result.validation_status == SafetyValidationStatus.REJECTED or safety_result.executed_action is None:
            record = DecisionRecord(
                step=step,
                sim_time_sec=sim_time,
                policy_id=policy.policy_id,
                safety_result=safety_result,
                accepted=False,
                rejection_reason="; ".join(safety_result.intervention_reasons),
                step_metrics=None,
            )
            return current_state, record

        # 4. Action Accepted: Advance simulator with verified ExecutedAction
        executed_action = safety_result.executed_action
        next_state, diagnostics = self.simulator.step(executed_action)

        # 5. Evaluate transition
        step_metrics = None
        if self.evaluator:
            step_metrics = self.evaluator.evaluate_transition(
                current_state=current_state,
                executed_action=executed_action,
                next_state=next_state,
                config=self.config,
                diagnostics=diagnostics,
            )

        record = DecisionRecord(
            step=step,
            sim_time_sec=sim_time,
            policy_id=policy.policy_id,
            safety_result=safety_result,
            accepted=True,
            rejection_reason=None,
            step_metrics=step_metrics,
        )

        return next_state, record
