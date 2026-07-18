# The one guardrail D-005 requires before any billable resource exists:
# an email alert when actual spend crosses a threshold. This is a monitor,
# not a spend cap — the Free Plan account already carries its own hard cap
# per docs/ARCHITECTURE.md, so this exists to catch drift early, not to
# stop overspend that structurally can't happen.
resource "aws_budgets_budget" "monthly" {
  name         = "parvum-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}
