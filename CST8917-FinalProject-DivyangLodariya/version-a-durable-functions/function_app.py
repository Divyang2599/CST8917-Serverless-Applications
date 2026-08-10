"""
CST8917 Assignment 2 - Version A: Expense Approval Workflow
Azure Durable Functions (Python v2 programming model)

Components:
  - Client function     : submit_expense   (HTTP -> starts orchestration)
  - Client function     : approve_expense  (HTTP -> raises external event = manager decision)
  - Orchestrator        : expense_orchestrator (the workflow brain)
  - Activity functions  : validate_expense, process_expense, send_notification

Human Interaction pattern: the orchestrator waits for an external event
("ManagerDecision") OR a durable timer (timeout). Whichever fires first wins.
Timeout -> the expense is auto-approved and flagged "escalated".
"""

import os
import json
import logging
from datetime import timedelta

import azure.functions as func
import azure.durable_functions as df

# DFApp = Function App that also supports Durable Functions triggers/bindings.
# ANONYMOUS auth keeps local testing simple (no function keys needed).
myApp = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# ---- Business constants -----------------------------------------------------
VALID_CATEGORIES = {"travel", "meals", "supplies", "equipment", "software", "other"}
REQUIRED_FIELDS = [
    "employee_name",
    "employee_email",
    "amount",
    "category",
    "description",
    "manager_email",
]
# Timeout for the manager decision. Kept short (120s) so the "escalated" demo
# is quick. Overridable via app setting APPROVAL_TIMEOUT_SECONDS.
APPROVAL_TIMEOUT_SECONDS = int(os.environ.get("APPROVAL_TIMEOUT_SECONDS", "120"))


# =============================================================================
# CLIENT FUNCTIONS (HTTP entry points)
# =============================================================================

@myApp.route(route="submit-expense")
@myApp.durable_client_input(client_name="client")
async def submit_expense(req: func.HttpRequest, client):
    """Start a new expense-approval orchestration from an HTTP POST body."""
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse("Request body must be valid JSON.", status_code=400)

    instance_id = await client.start_new("expense_orchestrator", client_input=payload)
    logging.info("Started orchestration with ID = %s", instance_id)

    # Returns the standard management URLs (statusQueryGetUri, etc.) so you can
    # poll the final result. The 'id' field is what you paste into /approve.
    return client.create_check_status_response(req, instance_id)


@myApp.route(route="approve/{instanceId}")
@myApp.durable_client_input(client_name="client")
async def approve_expense(req: func.HttpRequest, client):
    """Simulate a manager approving/rejecting by raising an external event."""
    instance_id = req.route_params.get("instanceId")

    # Accept decision from query string (?decision=approved) or JSON body.
    decision = req.params.get("decision")
    if decision not in ("approved", "rejected"):
        try:
            decision = (req.get_json() or {}).get("decision")
        except ValueError:
            decision = None

    if decision not in ("approved", "rejected"):
        return func.HttpResponse(
            "Provide decision=approved or decision=rejected.", status_code=400
        )

    # "ManagerDecision" must match the event name the orchestrator waits on.
    await client.raise_event(instance_id, "ManagerDecision", decision)
    return func.HttpResponse(
        f"Manager decision '{decision}' delivered to {instance_id}.", status_code=202
    )


# =============================================================================
# ORCHESTRATOR (must be deterministic - no I/O, no datetime.now, no random)
# =============================================================================

@myApp.orchestration_trigger(context_name="context")
def expense_orchestrator(context: df.DurableOrchestrationContext):
    expense = context.get_input()

    # 1) VALIDATION -----------------------------------------------------------
    validation = yield context.call_activity("validate_expense", expense)
    if not validation["valid"]:
        result = {
            "status": "rejected",
            "reason": validation["reason"],
            "stage": "validation",
            "expense": expense,
        }
        yield context.call_activity("send_notification", result)
        return result

    amount = float(expense["amount"])

    # 2) AUTO-APPROVE under $100 ---------------------------------------------
    if amount < 100:
        processed = yield context.call_activity("process_expense", expense)
        result = {
            "status": "approved",
            "reason": "Auto-approved (amount under $100).",
            "expense": expense,
            "processed": processed,
        }
        yield context.call_activity("send_notification", result)
        return result

    # 3) MANAGER APPROVAL with timeout (Human Interaction pattern) ------------
    approval_event = context.wait_for_external_event("ManagerDecision")
    deadline = context.current_utc_datetime + timedelta(seconds=APPROVAL_TIMEOUT_SECONDS)
    timeout_task = context.create_timer(deadline)

    winner = yield context.task_any([approval_event, timeout_task])

    if winner == approval_event:
        timeout_task.cancel()  # free the durable timer
        decision = approval_event.result
        if decision == "approved":
            processed = yield context.call_activity("process_expense", expense)
            result = {
                "status": "approved",
                "reason": "Manager approved.",
                "expense": expense,
                "processed": processed,
            }
        else:
            result = {
                "status": "rejected",
                "reason": "Manager rejected.",
                "expense": expense,
            }
    else:
        # Timer fired first = no manager response in time -> escalate.
        processed = yield context.call_activity("process_expense", expense)
        result = {
            "status": "escalated",
            "reason": f"No manager response within {APPROVAL_TIMEOUT_SECONDS}s; auto-approved and escalated.",
            "expense": expense,
            "processed": processed,
        }

    yield context.call_activity("send_notification", result)
    return result


# =============================================================================
# ACTIVITY FUNCTIONS (side effects live here, safe to be non-deterministic)
# =============================================================================

@myApp.activity_trigger(input_name="expense")
def validate_expense(expense: dict):
    """Check required fields, valid category, numeric amount."""
    if not isinstance(expense, dict):
        return {"valid": False, "reason": "Payload must be a JSON object."}

    missing = [f for f in REQUIRED_FIELDS if expense.get(f) in (None, "")]
    if missing:
        return {"valid": False, "reason": f"Missing required field(s): {', '.join(missing)}"}

    if expense.get("category") not in VALID_CATEGORIES:
        return {
            "valid": False,
            "reason": f"Invalid category '{expense.get('category')}'. "
            f"Valid: {', '.join(sorted(VALID_CATEGORIES))}.",
        }

    try:
        float(expense["amount"])
    except (ValueError, TypeError):
        return {"valid": False, "reason": "Amount must be a number."}

    return {"valid": True, "reason": "Validation passed."}


@myApp.activity_trigger(input_name="expense")
def process_expense(expense: dict):
    """Stand-in for 'record the approved expense' (e.g. write to a ledger/DB)."""
    logging.info(
        "Processing expense: %s $%s (%s)",
        expense.get("description"),
        expense.get("amount"),
        expense.get("category"),
    )
    return {"recorded": True, "reference": f"EXP-{abs(hash(json.dumps(expense, sort_keys=True))) % 100000:05d}"}


@myApp.activity_trigger(input_name="result")
def send_notification(result: dict):
    """
    Simulated email notification.

    """
    expense = result.get("expense", {})
    to = expense.get("employee_email", "unknown")
    message = (
        f"[EMAIL to {to}] Expense '{expense.get('description')}' "
        f"(${expense.get('amount')}, {expense.get('category')}) -> "
        f"{result['status'].upper()}. {result['reason']}"
    )
    logging.info("NOTIFICATION: %s", message)
    return message