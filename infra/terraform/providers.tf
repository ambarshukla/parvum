# Bucket name is hardcoded (not a variable) because backend blocks are
# evaluated before any variable or provider config exists — see
# bootstrap/main.tf, which creates this exact bucket.
terraform {
  required_version = ">= 1.10.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket       = "parvum-tfstate-656326303611"
    key          = "parvum/terraform.tfstate"
    region       = "us-east-1"
    profile      = "parvum-tf" # backend config is resolved separately from the provider block below, so this can't inherit var.aws_profile
    use_lockfile = true        # native S3 locking (TF 1.10+) — no DynamoDB table needed
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project = "parvum"
    }
  }
}
