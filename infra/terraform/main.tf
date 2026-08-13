# Core Scaleway infrastructure for legal-decisions-rag:
#   - a private Object Storage bucket holding the built cases.db artifact
#   - a public Container Registry namespace holding the query-service image
#   - a Serverless Containers namespace + container running the query API
#   - a narrowly-scoped IAM identity the container uses to read cases.db,
#     instead of the bucket being world-readable.
#
# Verified vs. inferred argument names are called out per-resource below;
# see the task report / README.md for the full verification summary.

# ---------------------------------------------------------------------------
# Object Storage: cases.db artifact
# ---------------------------------------------------------------------------

# Deliberately PRIVATE. A public-read bucket would let anyone bypass the
# query API's shared-key check and scrape the entire corpus directly by
# guessing/finding the object URL. The query service instead reads this
# bucket with its own scoped IAM credentials (see below).
resource "scaleway_object_bucket" "cases_db" {
  name       = var.bucket_name
  region     = var.region
  project_id = var.project_id

  tags = {
    project = "legal-decisions-rag"
  }
}

# The `acl` argument on scaleway_object_bucket itself is deprecated in
# favour of the dedicated scaleway_object_bucket_acl resource (verified via
# provider docs); "private" is also Scaleway's default ACL for new buckets,
# but it is set explicitly here so bucket privacy is visible in code and not
# left to an implicit provider default.
resource "scaleway_object_bucket_acl" "cases_db" {
  bucket     = scaleway_object_bucket.cases_db.id
  region     = var.region
  project_id = var.project_id
  acl        = "private"
}

# ---------------------------------------------------------------------------
# Container Registry: query-service image
# ---------------------------------------------------------------------------

# is_public = true keeps this simple and free at this project's scale
# (Scaleway Container Registry free tier: 75GB storage, free inbound
# bandwidth for a single small image) - per Technical requirements.md. The
# image itself contains no secrets; the shared API key is injected at
# container runtime, not baked into the image.
resource "scaleway_registry_namespace" "query_service" {
  name        = var.registry_namespace_name
  description = "Docker image registry for the legal-decisions-rag query service."
  region      = var.region
  project_id  = var.project_id
  is_public   = true
}

# ---------------------------------------------------------------------------
# Serverless Containers: query service
# ---------------------------------------------------------------------------

resource "scaleway_container_namespace" "query_service" {
  name        = var.container_namespace_name
  description = "Serverless Containers namespace for the legal-decisions-rag query service."
  region      = var.region
  project_id  = var.project_id
}

locals {
  # <registry endpoint>/<container name>:<image tag>, e.g.
  # rg.fr-par.scw.cloud/legal-decisions-rag/query-service:sha-abcdef.
  # image_tag defaults to "latest" but is overridden by CI on every deploy
  # with the git SHA of the image it just built and pushed (see README.md).
  container_image = "${scaleway_registry_namespace.query_service.endpoint}/${var.container_name}:${var.image_tag}"
}

resource "scaleway_container" "query_service" {
  name         = var.container_name
  description  = "Hybrid BM25 + vector search API over Belgian Constitutional Court rulings."
  namespace_id = scaleway_container_namespace.query_service.id
  region       = var.region
  # No project_id argument here (verified via provider docs: scaleway_container
  # has no project_id argument of its own - its project is inherited from
  # namespace_id).

  image    = local.container_image
  port     = 8080 # matches the app's PORT env default (src/query_service/main.py)
  protocol = "http1"

  # "public" here means the HTTPS endpoint is reachable without a Scaleway
  # IAM token (verified default/allowed value via provider docs) - i.e. it
  # controls network reachability, not application auth. The app itself
  # still rejects every request that lacks a valid X-API-Key header
  # (SHARED_API_KEY secret env var below); Copilot Studio / Custom GPT /
  # the MCP server hold that key server-side and call this public endpoint.
  privacy = "public"

  # Cost-conscious defaults: scale to zero when idle, never run more than
  # one instance. Raise max_scale later if traffic grows past what a single
  # instance can serve within the sub-1s target.
  min_scale = 0
  max_scale = 1

  # Plain (non-secret) environment variables: enough for the app to build
  # its own S3-compatible client and know which object to fetch. No
  # credentials here - those are injected as secret_environment_variables
  # below.
  environment_variables = {
    CASES_BUCKET_NAME     = scaleway_object_bucket.cases_db.name
    CASES_BUCKET_REGION   = var.region
    CASES_BUCKET_ENDPOINT = scaleway_object_bucket.cases_db.endpoint
  }

  # secret_environment_variables (verified argument name via provider docs):
  # Scaleway's mechanism for secret container env vars is a plain
  # map(string) on the container resource itself - there is no separate
  # "secret" resource/reference object to point at (unlike, say, AWS Secrets
  # Manager ARNs). Terraform still stores the resolved values in state, so
  # state must live in a private, access-controlled backend (see
  # backend.tf) and never be committed.
  secret_environment_variables = {
    SHARED_API_KEY          = var.shared_api_key
    CASES_BUCKET_ACCESS_KEY = scaleway_iam_api_key.cases_db_reader.access_key
    CASES_BUCKET_SECRET_KEY = scaleway_iam_api_key.cases_db_reader.secret_key
  }

  depends_on = [scaleway_object_bucket_policy.cases_db_read_only]
}

# ---------------------------------------------------------------------------
# IAM: scoped read-only credentials for the query service
# ---------------------------------------------------------------------------
#
# Scaleway containers cannot directly assume an IAM policy the way, say, AWS
# Lambda execution roles work (verified: no such mechanism is exposed on
# scaleway_container/scaleway_container_namespace in the provider docs), so
# the app must authenticate to Object Storage itself with an access/secret
# key pair, injected as secret env vars above.
#
# Two layers are used together, matching Scaleway's own documented pattern
# for combining IAM and bucket policies to reach bucket-level granularity
# (Scaleway IAM policy rules alone can only be scoped down to a *project*
# via project_ids, not to one specific bucket within it):
#   1. scaleway_iam_policy grants the application the ObjectStorageReadOnly
#      permission set, scoped to this project only.
#   2. scaleway_object_bucket_policy (an S3-style bucket resource policy)
#      further restricts that access to *this one bucket*, naming the
#      application as the sole allowed principal for GetObject/ListBucket.
# See the task report for what's verified vs. inferred here.

resource "scaleway_iam_application" "cases_db_reader" {
  name        = "legal-decisions-rag-query-service"
  description = "Identity used by the query-service container to read cases.db from Object Storage. Holds no other permissions."
}

resource "scaleway_iam_policy" "cases_db_reader" {
  name           = "legal-decisions-rag-cases-db-read-only"
  description    = "Read-only Object Storage access for the query service, scoped to this project. Narrowed further to the cases.db bucket alone by the bucket policy below."
  application_id = scaleway_iam_application.cases_db_reader.id

  rule {
    project_ids          = [var.project_id]
    permission_set_names = ["ObjectStorageReadOnly"]
  }
}

resource "scaleway_iam_api_key" "cases_db_reader" {
  application_id     = scaleway_iam_application.cases_db_reader.id
  description        = "Key for the query-service container to read cases.db from Object Storage."
  default_project_id = var.project_id
}

# Bucket-level restriction: only the application above may read this
# specific bucket, and only via GetObject/ListBucket (no writes/deletes).
resource "scaleway_object_bucket_policy" "cases_db_read_only" {
  # No region argument (verified via provider docs: scaleway_object_bucket_policy
  # only supports bucket, policy, and project_id).
  bucket     = scaleway_object_bucket.cases_db.name
  project_id = var.project_id

  policy = jsonencode({
    Version = "2023-04-17"
    Statement = [
      {
        Sid    = "QueryServiceReadOnly"
        Effect = "Allow"
        Principal = {
          SCW = "application_id:${scaleway_iam_application.cases_db_reader.id}"
        }
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
        ]
        Resource = [
          scaleway_object_bucket.cases_db.name,
          "${scaleway_object_bucket.cases_db.name}/*",
        ]
      }
    ]
  })
}
