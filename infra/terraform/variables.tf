variable "aws_region" {
  default = "us-east-1"
}

variable "aws_profile" {
  # See bootstrap/main.tf for why this is "-tf" and not "parvum" directly.
  default = "parvum-tf"
}

# No default — a misconfigured deploy should fail loudly rather than
# silently alert nobody. Set via TF_VAR_alert_email, same pattern as the
# Databricks job's BUNDLE_VAR_alert_email (see Makefile deploy-job).
variable "alert_email" {
  description = "Where AWS Budgets sends threshold alerts."
  type        = string
}

variable "budget_limit_usd" {
  description = "Monthly budget AWS Budgets alerts against. Not a spend cap — just the threshold alerts are computed from."
  type        = number
  default     = 20
}
