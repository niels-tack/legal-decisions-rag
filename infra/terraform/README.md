# Terraform: legal-decisions-rag Scaleway infrastructure

Manages, as code, everything the query service needs to run on Scaleway (`fr-par`):

- a private Object Storage bucket for the built `cases.db` artifact
- a public Container Registry namespace for the query-service Docker image
- a Serverless Containers namespace + container running the query API
- a narrowly-scoped IAM application/policy/API key the container uses to
  read `cases.db`, instead of the bucket being world-readable

See `../../context/Technical requirements.md` for the full architecture this implements.

## 0. Prerequisite: the Terraform state bucket (manual, one-time)

Terraform cannot manage the bucket that holds its own state. Before the
first `terraform init` in this directory, create a bucket for state
**manually**, once, using one of:

- the Scaleway console (Object Storage -> Create bucket -> private), or
- the `scw` CLI, e.g.:
  ```sh
  scw object bucket create name=legal-decisions-rag-tfstate region=fr-par
  ```
- a tiny separate bootstrap Terraform config (its own directory, e.g.
  `infra/bootstrap/`, using **local** state) containing just a
  `scaleway_object_bucket` + `scaleway_object_bucket_acl` (private) for the
  state bucket. This keeps the bootstrap itself in code, at the cost of that
  one config's state living locally (acceptable: it manages nothing else and
  changes essentially never).

Whichever route you take, update the `bucket` name in `backend.tf` to match
(bucket names are globally unique across all Scaleway accounts).

## 1. Required environment variables

Two distinct sets of credentials are needed - do not confuse them:

| Purpose | Variables | Read by |
|---|---|---|
| scaleway provider (creating/managing resources) | `SCW_ACCESS_KEY`, `SCW_SECRET_KEY` | the `scaleway/scaleway` Terraform provider |
| Terraform state backend (reading/writing the state file itself) | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Terraform core's generic S3 backend |

The backend is Terraform's generic S3-compatible backend (see `backend.tf`),
which has no knowledge of Scaleway-specific env var names - it only reads
the AWS-style ones. Set both pairs to the **same** Scaleway API key/secret:

```sh
export SCW_ACCESS_KEY="<your Scaleway API access key>"
export SCW_SECRET_KEY="<your Scaleway API secret key>"
export AWS_ACCESS_KEY_ID="$SCW_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$SCW_SECRET_KEY"
export TF_VAR_project_id="<your Scaleway project ID>"
export TF_VAR_allowed_origin="<the deployed website's origin, e.g. https://niels-tack.github.io>"
```

Never commit any of the above. `allowed_origin` isn't secret (the query
service is keyless - see `src/query_service/main.py`), but the Scaleway
access/secret keys are; the state bucket must stay private (step 0) and
never public regardless, since Terraform writes resolved variable values
into the state file in plaintext.

## 2. Init, plan, apply

```sh
cd infra/terraform
terraform init
terraform plan
terraform apply
```

On first apply, `bucket_name`, `registry_namespace_name`,
`container_namespace_name`, and `container_name` all have workable defaults
in `variables.tf` - override any of them with `-var` if they collide with an
existing name in your account (bucket names in particular are globally
unique across all Scaleway accounts, not just your project).

The very first `apply` will fail to pull a real image for
`scaleway_container.query_service` if nothing has been pushed yet to the
registry namespace - push at least one image first (see step 3), or expect
that first apply to leave the container in a non-serving state until CI's
first deploy completes.

## 3. How CI deploys

On every push that should ship a new query-service build, CI is expected to:

1. Build the Docker image from the repo's `Dockerfile`.
2. Log in and push it to the registry namespace's endpoint (Terraform output
   `registry_namespace_endpoint`), tagged with the git SHA:
   ```sh
   docker build -t "$REGISTRY_ENDPOINT/query-service:$GITHUB_SHA" .
   docker push "$REGISTRY_ENDPOINT/query-service:$GITHUB_SHA"
   ```
3. Run Terraform with that same tag so `scaleway_container.query_service`
   is updated to point at the image CI just pushed:
   ```sh
   terraform apply -auto-approve -var "image_tag=$GITHUB_SHA"
   ```

`image_tag` defaults to `"latest"` for local/manual convenience, but CI
should always pass an explicit git-SHA tag so every deploy is traceable to
an exact commit and `terraform apply` reliably detects a change.

## Required GitHub Actions secrets

| Secret | Used for |
|---|---|
| `SCW_ACCESS_KEY` | scaleway provider auth (Terraform) and `docker login` to the registry |
| `SCW_SECRET_KEY` | scaleway provider auth (Terraform) and `docker login` to the registry |
| `SCW_PROJECT_ID` | passed as `TF_VAR_project_id` |
| `ALLOWED_ORIGIN` (repo/org variable, not a secret) | passed as `TF_VAR_allowed_origin` - the deployed website's origin, locking down the query service's CORS policy |
| `TF_STATE_BUCKET` (optional) | if you don't want the state bucket name hardcoded in `backend.tf`, pass it instead via `terraform init -backend-config="bucket=$TF_STATE_BUCKET"` |

In the workflow, also set `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` from
the `SCW_ACCESS_KEY`/`SCW_SECRET_KEY` secrets before any `terraform init`
step, for the reason explained in step 1 above.

## What a human must still do before this is real

- Have (or create) a Scaleway account and Organization, and a Project
  within it (its ID is `TF_VAR_project_id` / `SCW_PROJECT_ID`).
- Generate a Scaleway API key (access key + secret key) for the identity
  Terraform itself runs as (a personal API key for manual applies, or a
  dedicated IAM application's key for CI) - this is distinct from the
  per-application key Terraform creates *for the query service* in `main.tf`.
- Create the Terraform state bucket manually (step 0).
- Pick globally-unique bucket and registry namespace names if the defaults
  in `variables.tf` are already taken.
- Once the Phase 1 static site is deployed to GitHub Pages, set
  `allowed_origin` to its real origin so the query service's CORS policy
  stops rejecting it (it fails closed - no origin allowed - until then).
- Wire the resulting `query_service_endpoint` output into the website's
  Phase 2 `RemoteApiProvider` configuration (see Technical requirements.md).
