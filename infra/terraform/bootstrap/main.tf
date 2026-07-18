# Bootstraps the S3 bucket that holds the MAIN config's remote state
# (../*.tf). This config's own state stays local (gitignored) on purpose —
# it manages exactly one bucket, so the chicken-and-egg problem of "state
# needs a bucket, the bucket's creation needs to be tracked in state" is
# solved by keeping this one tiny piece out of the remote backend entirely.
#
# Apply once: terraform -chdir=infra/terraform/bootstrap init && apply
# The bucket name is deterministic (account id suffix, not random) so the
# main config's backend block below can hardcode it — backend blocks
# cannot reference variables or outputs.

terraform {
  required_version = ">= 1.10.0" # S3 native locking (use_lockfile) needs 1.10+
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

variable "aws_region" {
  default = "us-east-1"
}

variable "aws_profile" {
  # "parvum" is what `aws login` writes to and what you sign in with; "-tf"
  # is a credential_process shim over the same session (see ~/.aws/config)
  # because Terraform's AWS SDK doesn't understand login_session directly.
  default = "parvum-tf"
}

data "aws_caller_identity" "current" {}

locals {
  state_bucket_name = "parvum-tfstate-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "tfstate" {
  bucket = local.state_bucket_name

  # A destroyed state bucket takes the whole project's Terraform history
  # with it — this is the one resource in the entire deploy that must
  # never go via a casual `terraform destroy`.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "state_bucket_name" {
  value = aws_s3_bucket.tfstate.id
}
