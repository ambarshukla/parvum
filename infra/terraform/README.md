# infra/terraform/ — the AWS deployment (retired 2026-09-21)

**These resources no longer exist.** They were destroyed on 2026-09-21 when the
serving stack moved to a single host (D-092), after the free credits ran down at
a measured $2.56/day. The code is kept deliberately: it is the record of how this
project was deployed on AWS, and the decisions around it are the point.

Production now lives in [`../hetzner/`](../hetzner/).

## What this built

| File | Resources |
|---|---|
| `ecs.tf` | ECS Express Mode service, its execution and infrastructure IAM roles, three SSM SecureString parameters |
| `rds.tf` | Postgres 16 instance, parameter group (`rds.force_ssl`), subnet group, generated password |
| `ecr.tf` | Container registry and its lifecycle policy |
| `github_oidc.tf` | OIDC provider and the role GitHub Actions assumed — no static access keys |
| `network.tf` | Security groups over the default VPC; deliberately no NAT gateway |
| `budget.tf` | A monthly cost alert |

23 resources in total at teardown.

## What it is worth reading for

- **D-005 → D-035:** the original design named App Runner. It closed to new
  customers on 2026-04-30 and this was discovered at the first `apply`, not in the
  docs. ECS Express Mode replaced it. Verify a managed service still accepts new
  customers before writing Terraform for it.
- **D-036:** why RDS was `publicly_accessible = true` — a GitHub-hosted runner
  cannot reach a private subnet without a NAT gateway, the one fixed cost the
  budget had ruled out. Defended with `rds.force_ssl` and a generated password.
  **D-092 closed this**, because the constraint was an AWS networking fact rather
  than a property of the design, and it did not survive the move.
- **D-038:** the GitHub OIDC trust policy uses the immutable-subject-claim format
  (`repo:owner@id/repo@id:ref:...`). The classic form fails.
- **D-039:** `parvum-terraform` cannot read SSM values, which is why the internal
  app's password had to come from `terraform show -json` rather than the CLI.

## The three findings the teardown itself produced

- 🔴 **`Destroy complete!` did not mean everything was destroyed.** Terraform
  emptied its state and reported success, while the Express Mode **ALB and its
  six public IPs were still `active`** — along with two target groups. Express
  Mode creates that load balancer *on your behalf*, so it is AWS-owned rather
  than Terraform-managed, and destroying the service does not reliably take it
  with it. It had to be deleted directly through the CLI. **Had the success
  message been trusted, the single largest line on the bill would have kept
  running against an account with days of credit left.** The state file
  describes what Terraform believes it owns, not what exists — and a managed
  service's side effects are precisely the gap between the two. Verify by
  listing resources, not by reading the summary.
- **Teardown needed three passes, not one.** First run: the ECS service timed
  out after 20 minutes stuck in `DRAINING` (destroy is not atomic — 8 of 23
  resources were gone). Second: reached RDS, then failed on the ECR repository,
  which refuses deletion while it holds images (18 of them). Third succeeded
  after emptying it. `force_delete = true` on the repository would have avoided
  the third.

- **`budget.tf` was never in the state.** The destroy plan listed 23 resources and
  the budget was not among them — so the alert that was supposed to catch cost
  drift had never existed, while an unread AWS default sat at 336% of a $10 limit.
  A guardrail declared in code is not a guardrail until something confirms it is
  there.
- **Half the bill was one load balancer.** $16.75/mo of ELB plus **eight** public
  IPv4 addresses at $29.78/mo — six of them held by the managed ALB, one per
  default subnet, because `network.tf` passed it every `data.aws_subnets.default.ids`.
  For a single container serving a few requests a day. Managed convenience prices
  itself per availability zone whether or not you asked for availability.
