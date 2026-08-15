# Remote state, held in Scaleway Object Storage via Terraform's built-in
# S3-compatible backend (Terraform core's generic "s3" backend, not the
# scaleway provider - see the credentials note below).
#
# Terraform cannot manage the bucket that holds its own state, so
# "legal-decisions-rag-tfstate" must exist BEFORE `terraform init` runs
# here. Create it manually once (console or `scw` CLI) or via a tiny
# separate bootstrap Terraform config that keeps its own state locally -
# see README.md for both options. Rename the bucket below first: bucket
# names are globally unique across all Scaleway accounts, so this exact
# name is very unlikely to be free.
#
# Backend argument names/values below (bucket, key, region, endpoints,
# skip_credentials_validation, skip_region_validation,
# skip_requesting_account_id, use_path_style) come from Terraform core's
# generic S3 backend, not the scaleway provider - they were not fetched
# from the scaleway/scaleway provider docs listed in the task and are
# **inferred** from Scaleway's own published Terraform-backend guidance.
# Two syntax variants exist across Terraform versions:
#   - Terraform >= 1.6: plural `endpoints = { s3 = "..." }` and
#     `use_path_style` (used below).
#   - Terraform < 1.6 / older guidance: singular `endpoint = "..."` and
#     `force_path_style`.
# If `terraform init` rejects the block below, switch to the older form.
terraform {
  backend "s3" {
    bucket = "legal-decisions-rag-tfstate" # CHANGE ME: must be created manually first, see README.md
    key    = "legal-decisions-rag/terraform.tfstate"
    region = "fr-par"

    endpoints = {
      s3 = "https://s3.fr-par.scw.cloud"
    }

    # Scaleway's S3-compatible API doesn't support every AWS-specific
    # behaviour the generic S3 backend otherwise assumes.
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    use_path_style              = true

    # No access_key/secret_key here (never commit credentials). This
    # backend is Terraform core's generic S3 backend, NOT the scaleway
    # provider - it does not read SCW_ACCESS_KEY/SCW_SECRET_KEY. Instead,
    # before `terraform init`, export the SAME Scaleway API credentials
    # under the AWS-style names this backend does understand:
    #
    #   export AWS_ACCESS_KEY_ID="$SCW_ACCESS_KEY"
    #   export AWS_SECRET_ACCESS_KEY="$SCW_SECRET_KEY"
    #
    # (see README.md for the full setup sequence).

    # No native state locking is configured (Scaleway Object Storage's
    # support for the conditional-write semantics Terraform's optional
    # `use_lockfile` relies on is unconfirmed at time of writing, and there
    # is no DynamoDB-equivalent lock table service in this all-Scaleway
    # setup). Acceptable for a solo maintainer applying from one place at a
    # time; revisit if that stops being true.
  }
}
