# Outputs consumed by CI (to smoke-test a deploy) and by whoever configures
# the website's Phase 2 remote search backend.

output "query_service_endpoint" {
  description = "Public HTTPS endpoint of the query-service Serverless Container. Point the website's RemoteApiProvider config at <this>/search."
  value       = scaleway_container.query_service.public_endpoint
}

output "registry_namespace_endpoint" {
  description = "Docker-reachable endpoint of the Container Registry namespace. CI pushes the query-service image to <this>/<container_name>:<tag> before running terraform apply."
  value       = scaleway_registry_namespace.query_service.endpoint
}

output "cases_db_bucket_name" {
  description = "Name of the private Object Storage bucket hosting the built cases.db artifact."
  value       = scaleway_object_bucket.cases_db.name
}
