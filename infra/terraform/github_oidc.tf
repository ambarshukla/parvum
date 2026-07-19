# Lets GitHub Actions assume an AWS role via short-lived OIDC tokens —
# no static AWS access key sitting in a repo secret, same "nothing
# permanent to leak" instinct as the aws login setup (D-033).
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # AWS validates the token against its own trusted CA store for this
  # well-known issuer regardless of this value; recent provider versions
  # accept it being effectively a formality but still require the argument.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# Scoped to this exact repo, and only the main branch — a PR from a fork
# (or any other branch) cannot assume this role.
resource "aws_iam_role" "github_actions" {
  name = "parvum-github-actions"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          # GitHub's "immutable subject claims" change (2026-04-23) rewrote
          # the sub claim to embed permanent owner/repo IDs instead of the
          # classic repo:owner/repo:ref:... form — confirmed against the
          # actual failing run via CloudTrail, not assumed from docs. These
          # numeric IDs are exactly that: permanent for this repo, so this
          # condition doesn't break on a future rename the way the old
          # name-based form would have.
          "token.actions.githubusercontent.com:sub" = "repo:ambarshukla@59102691/parvum@1302835881:ref:refs/heads/main"
        }
      }
    }]
  })
}

# Just enough to push one image and redeploy one service — not general ECR
# or ECS admin.
resource "aws_iam_role_policy" "github_actions_deploy" {
  name = "deploy-serving"
  role = aws_iam_role.github_actions.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRAuth"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*" # this action has no resource-level scoping in IAM
      },
      {
        Sid    = "ECRPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
        ]
        Resource = aws_ecr_repository.serving.arn
      },
      {
        Sid      = "ECSDeploy"
        Effect   = "Allow"
        Action   = ["ecs:UpdateService", "ecs:DescribeServices"]
        Resource = aws_ecs_express_gateway_service.serving.service_arn
      },
    ]
  })
}

# Lets export-gold.yml read the RDS password at runtime instead of
# duplicating it into a GitHub secret — one source of truth for the
# secret (SSM), not two copies to keep in sync if it's ever rotated.
# Reuses the same role as the deploy workflow rather than minting a
# second one: both run only from this repo's main branch, so there's no
# meaningfully different trust boundary between them on a single-owner
# project.
resource "aws_iam_role_policy" "github_actions_read_rds_password" {
  name = "read-rds-password"
  role = aws_iam_role.github_actions.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadRdsPassword"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = aws_ssm_parameter.rds_password.arn
      },
      {
        Sid       = "DecryptRdsPassword"
        Effect    = "Allow"
        Action    = "kms:Decrypt"
        Resource  = "*"
        Condition = { StringEquals = { "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com" } }
      },
    ]
  })
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}
