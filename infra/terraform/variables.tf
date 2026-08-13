# Input variables for the legal-decisions-rag Scaleway infrastructure.

variable "project_id" {
  description = "Scaleway project ID that owns every resource in this configuration."
  type        = string
}

variable "region" {
  description = "Scaleway region for all regional resources (Object Storage, Container Registry, Serverless Containers). Fixed to Paris per the project's EU-data-residency requirement."
  type        = string
  default     = "fr-par"
}

variable "zone" {
  description = "Scaleway availability zone used as the provider's default zone. None of the resources managed here are zonal, but the provider block expects a value."
  type        = string
  default     = "fr-par-1"
}

variable "registry_namespace_name" {
  description = "Name of the Scaleway Container Registry namespace that hosts the query-service Docker image."
  type        = string
  default     = "legal-decisions-rag"
}

variable "container_namespace_name" {
  description = "Name of the Scaleway Serverless Containers namespace for the query service."
  type        = string
  default     = "legal-decisions-rag"
}

variable "container_name" {
  description = "Name of the query-service Scaleway Serverless Container. Also used as the image repository name inside the registry namespace (<registry_endpoint>/<container_name>:<image_tag>)."
  type        = string
  default     = "query-service"
}

variable "bucket_name" {
  description = "Name of the private Object Storage bucket that hosts the built cases.db artifact. Bucket names are globally unique across all Scaleway accounts, so the default is unlikely to be usable as-is."
  type        = string
  default     = "legal-decisions-rag-cases-db"
}

variable "image_tag" {
  description = "Tag of the query-service image to deploy, e.g. \"rg.fr-par.scw.cloud/<ns>/query-service:<image_tag>\". Defaults to \"latest\" for local/manual use; CI overrides this on every deploy with the git SHA of the image it just built and pushed, e.g. `terraform apply -var image_tag=$GITHUB_SHA`."
  type        = string
  default     = "latest"
}

variable "shared_api_key" {
  description = "Shared static API key the query service checks every incoming request against (the X-API-Key header, see src/query_service/auth.py). Held only in Terraform variables / GitHub Actions secrets, never committed or logged."
  type        = string
  sensitive   = true
}
