"""
CST8917 Assignment 2 - Version B: Validation Function
HTTP-triggered Azure Function called by the Logic App to validate an expense.
Returns 200 with {"valid": bool, "reason": str} for BOTH valid and invalid
input, so the Logic App treats every call as a successful lookup and branches
on the "valid" field (instead of catching HTTP errors).
"""

import json
import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

VALID_CATEGORIES = {"travel", "meals", "supplies", "equipment", "software", "other"}
REQUIRED_FIELDS = [
    "employee_name", "employee_email", "amount",
    "category", "description", "manager_email",
]


@app.route(route="validate", methods=["POST"])
def validate(req: func.HttpRequest) -> func.HttpResponse:
    try:
        expense = req.get_json()
    except ValueError:
        return _json({"valid": False, "reason": "Request body must be valid JSON."})

    missing = [f for f in REQUIRED_FIELDS if expense.get(f) in (None, "")]
    if missing:
        result = {"valid": False, "reason": f"Missing required field(s): {', '.join(missing)}"}
    elif expense.get("category") not in VALID_CATEGORIES:
        result = {
            "valid": False,
            "reason": f"Invalid category '{expense.get('category')}'. "
                      f"Valid: {', '.join(sorted(VALID_CATEGORIES))}.",
        }
    else:
        try:
            float(expense["amount"])
            result = {"valid": True, "reason": "Validation passed."}
        except (ValueError, TypeError):
            result = {"valid": False, "reason": "Amount must be a number."}

    return _json(result)


def _json(payload: dict) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload), status_code=200, mimetype="application/json"
    )