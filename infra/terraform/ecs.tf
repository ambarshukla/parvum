# D-005 originally named App Runner; it closed to new AWS customers on
# 2026-04-30 (maintenance mode), which this account hit on first apply.
# ECS Express Mode is AWS's direct successor — same pitch (point at an image,
# get a public HTTPS endpoint, no load balancer of your own to manage) built
# on ECS/Fargate, with its own managed ALB + ACM certificate + autoscaling.
# See docs/DECISIONS.md for the amendment.

# The RDS password never appears as a plain environment variable — it's
# written to SSM Parameter Store as a SecureString, and the execution role
# below resolves it at container start (`secrets`), the same "no static
# secret sitting around" instinct as the aws login setup (D-033).
resource "aws_ssm_parameter" "rds_password" {
  name  = "/parvum/rds/password"
  type  = "SecureString"
  value = random_password.rds.result
}

# Lets ECS pull the (private) ECR image, write CloudWatch logs, and resolve
# the RDS password secret at container start — the standard Fargate
# "execution role", not to be confused with the infrastructure role below.
resource "aws_iam_role" "ecs_execution" {
  name = "parvum-ecs-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_ssm" {
  name = "read-rds-password"
  role = aws_iam_role.ecs_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameters", "ssm:GetParameter"]
        Resource = aws_ssm_parameter.rds_password.arn
      },
      {
        Effect    = "Allow"
        Action    = "kms:Decrypt"
        Resource  = "*"
        Condition = { StringEquals = { "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com" } }
      }
    ]
  })
}

# Lets Express Mode provision and manage its own ALB, security groups, ACM
# certificate, and auto scaling on our behalf — the "no load balancer to
# manage" part of the pitch. AWS-managed policy, not written by hand.
resource "aws_iam_role" "ecs_infrastructure" {
  name = "parvum-ecs-infrastructure"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_infrastructure" {
  role       = aws_iam_role.ecs_infrastructure.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}

resource "aws_ecs_express_gateway_service" "serving" {
  service_name            = "parvum-serving"
  execution_role_arn      = aws_iam_role.ecs_execution.arn
  infrastructure_role_arn = aws_iam_role.ecs_infrastructure.arn

  cpu    = 512  # 0.5 vCPU
  memory = 1024 # 1 GB — Quarkus's whole appeal is not needing more

  health_check_path = "/q/health"

  primary_container {
    image          = "${aws_ecr_repository.serving.repository_url}:latest"
    container_port = 8080

    environment {
      name  = "QUARKUS_DATASOURCE_JDBC_URL"
      value = "jdbc:postgresql://${aws_db_instance.main.address}:5432/parvum?sslmode=require"
    }
    # The production domain plus a regex covering every preview deployment
    # (Vercel gives each one a random subdomain under the same project) —
    # supplied here rather than hardcoded in application.properties because
    # it's a fact about this deployment, not about the build.
    environment {
      name  = "QUARKUS_HTTP_CORS_ORIGINS"
      value = "https://parvum-dashboard.vercel.app,/https://parvum-dashboard-.*\\.vercel\\.app/"
    }
    environment {
      name  = "QUARKUS_DATASOURCE_USERNAME"
      value = "parvum"
    }
    secret {
      name       = "QUARKUS_DATASOURCE_PASSWORD"
      value_from = aws_ssm_parameter.rds_password.arn
    }
  }

  # Explicit, rather than left to Express Mode's own defaults, so the RDS
  # security group above can reference exactly this one by id.
  network_configuration {
    subnets         = data.aws_subnets.default.ids
    security_groups = [aws_security_group.ecs_tasks.id]
  }
}

output "ecs_ingress_paths" {
  value = aws_ecs_express_gateway_service.serving.ingress_paths
}
