# Shared networking for RDS + the ECS Express Mode service's tasks. Uses the
# account's default VPC and its public subnets (Express Mode's own default),
# rather than creating a new one — there's nothing this project needs from a
# custom VPC. No NAT gateway is needed: tasks get public IPs directly (so
# ECR pulls / CloudWatch logs work without one), and the managed ALB Express
# Mode provisions is the only other thing exposed to the internet.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Open on 5432 to any source (see D-035 / rds.tf: GitHub Actions' hosted
# runners need to reach this directly, and their IPs aren't allowlistable).
# TLS (rds.force_ssl) + the generated password are the actual defense.
resource "aws_security_group" "rds" {
  name_prefix = "parvum-rds-"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "ecs_tasks" {
  name_prefix = "parvum-ecs-tasks-"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}
