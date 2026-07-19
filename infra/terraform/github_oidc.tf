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
          "token.actions.githubusercontent.com:sub" = "repo:ambarshukla/parvum:ref:refs/heads/main"
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

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}
