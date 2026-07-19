# A Terraform-generated master password, not a manually chosen one, and not
# AWS's Secrets-Manager-managed rotation (`manage_master_user_password`) —
# that would need the Quarkus datasource to fetch a rotating secret at
# runtime, which the current plain-JDBC-driver config doesn't do. Good
# enough here because access is protected by TLS + this password (see
# publicly_accessible below) and Terraform state already lives in an
# access-controlled, encrypted S3 bucket. Revisit if the datasource ever
# grows Secrets Manager support.
resource "random_password" "rds" {
  length  = 32
  special = false # simplest to pass through an env var with zero escaping surprises
}

resource "aws_db_subnet_group" "main" {
  name       = "parvum"
  subnet_ids = data.aws_subnets.default.ids
}

# Forces SSL for every connection (rds.force_ssl=1) — the app-layer defense
# that makes publicly_accessible below an acceptable trade rather than a
# shortcut. This parameter's AWS-defined ApplyType is "dynamic", so
# apply_method = "immediate" takes effect without a reboot.
resource "aws_db_parameter_group" "main" {
  name   = "parvum-postgres16"
  family = "postgres16"

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "immediate"
  }
}

# db.t4g.micro per D-005; engine_version pinned to match the local
# docker-compose Postgres exactly (dev/prod parity, D-005's stated goal) —
# both currently resolve to 16.14.
#
# publicly_accessible = true (amended from the original private-VPC design,
# see D-035): the export-gold reload runs from GitHub Actions' hosted
# runners, which need to reach both Databricks (public internet) and this
# database — a private subnet can't do the former without a NAT gateway,
# the exact fixed cost D-005 already ruled out. Security group stays open
# on 5432 (runner IPs are unpredictable, so allowlisting isn't practical);
# rds.force_ssl + the generated password are the real defense.
resource "aws_db_instance" "main" {
  identifier     = "parvum"
  engine         = "postgres"
  engine_version = "16.14"
  instance_class = "db.t4g.micro"

  allocated_storage = 20 # gp3 minimum for Postgres on RDS
  storage_type      = "gp3"

  db_name  = "parvum"
  username = "parvum"
  password = random_password.rds.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  parameter_group_name   = aws_db_parameter_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = true
  multi_az               = false # single-AZ; no standby to pay for on a demo workload

  backup_retention_period = 1
  skip_final_snapshot     = true # a from-gold rebuild is always available (D-029) — no final snapshot needed on teardown

  apply_immediately = true
}
