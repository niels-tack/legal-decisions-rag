# Provider requirements and configuration for the legal-decisions-rag
# Scaleway infrastructure.
#
# Authentication: the scaleway/scaleway provider reads the account's API
# credentials from the SCW_ACCESS_KEY and SCW_SECRET_KEY environment
# variables (its documented default behaviour). They are never set as HCL
# arguments here and must never be committed to version control. Export them
# in your shell (or as GitHub Actions secrets, see README.md) before running
# any `terraform` command:
#
#   export SCW_ACCESS_KEY="..."
#   export SCW_SECRET_KEY="..."
#
# Note the S3-compatible Terraform *state backend* configured in backend.tf
# is a separate, generic Terraform mechanism (not the scaleway provider) and
# does not read SCW_ACCESS_KEY/SCW_SECRET_KEY automatically - see the note
# there.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    scaleway = {
      source  = "scaleway/scaleway"
      version = "~> 2.45"
    }
  }
}

provider "scaleway" {
  region     = var.region
  zone       = var.zone
  project_id = var.project_id

  # access_key / secret_key are intentionally omitted here: they come from
  # the SCW_ACCESS_KEY / SCW_SECRET_KEY environment variables.
}
