# UnoArena DevOps Checkpoint

## Context

This checkpoint validates that UnoArena microservices from the Architecture Checkpoint are independently buildable and deployable in a GitLab monorepo, with one fully wired service proving end-to-end staging deployment and CLI-driven integration smoke testing.

## Deployment Model Choice

Chosen model: Helm from pipeline.

Reasoning:

- Keeps deploy evidence in the same pipeline that built and delivered the artifact.
- Supports explicit readiness gates before integration tests.
- Provides a straightforward rollback action with Helm revision history.

## Repository Layout

| Service | Source Path | Pipeline Fragment | Helm Chart | Image Name | Helm Release | Wiring Depth |
|---|---|---|---|---|---|---|
| api-gateway | devOps/api-gateway/ | devOps/ci/services/api-gateway.gitlab-ci.yml | devOps/charts/api-gateway/ | $CI_REGISTRY_IMAGE/api-gateway | api-gateway | test, build, deliver, deploy-staging, integration-staging, optional prod |
| identity-service | devOps/identity-service/ | devOps/ci/services/identity-service.gitlab-ci.yml | devOps/charts/identity-service/ | $CI_REGISTRY_IMAGE/identity-service | identity-service | test, build, deliver |
| room-gameplay-service | devOps/room-gameplay-service/ | devOps/ci/services/room-gameplay-service.gitlab-ci.yml | devOps/charts/room-gameplay-service/ | $CI_REGISTRY_IMAGE/room-gameplay-service | room-gameplay-service | test, build, deliver |
| tournament-service | devOps/tournament-service/ | devOps/ci/services/tournament-service.gitlab-ci.yml | devOps/charts/tournament-service/ | $CI_REGISTRY_IMAGE/tournament-service | tournament-service | test, build, deliver |
| spectator-service | devOps/spectator-service/ | devOps/ci/services/spectator-service.gitlab-ci.yml | devOps/charts/spectator-service/ | $CI_REGISTRY_IMAGE/spectator-service | spectator-service | test, build, deliver |
| ranking-service | devOps/ranking-service/ | devOps/ci/services/ranking-service.gitlab-ci.yml | devOps/charts/ranking-service/ | $CI_REGISTRY_IMAGE/ranking-service | ranking-service | test, build, deliver |
| analytics-service | devOps/analytics-service/ | devOps/ci/services/analytics-service.gitlab-ci.yml | devOps/charts/analytics-service/ | $CI_REGISTRY_IMAGE/analytics-service | analytics-service | test, build, deliver |
| moderation-service | devOps/moderation-service/ | devOps/ci/services/moderation-service.gitlab-ci.yml | devOps/charts/moderation-service/ | $CI_REGISTRY_IMAGE/moderation-service | moderation-service | test, build, deliver |

## Pipeline Narrative

Stages are defined in this order:

1. test
2. build
3. deliver
4. deploy-staging
5. integration-staging
6. deliver-production (optional)
7. deploy-production (optional)

Fail-fast mechanics:

- Per-service jobs use needs relationships: test -> build -> deliver.
- For api-gateway full path: deliver -> deploy-staging -> integration-staging.
- If an upstream job fails, downstream jobs for that service do not run.

Independent deployability:

- Each service fragment uses rules:changes for its own source path, chart path, and relevant CI files.
- A change in one service path should not trigger unrelated service pipelines.

## Build and Promotion Model

Build once, promote:

- Deliver stage emits IMAGE_REPOSITORY, IMAGE_TAG, and IMAGE_DIGEST.
- Staging and production deploy jobs consume the same artifact identity.
- No rebuild occurs between staging and production.

## Environment Separation and Secrets

Environment differentiation is captured in chart values files:

- staging: values-staging.yaml
- production: values-production.yaml

At minimum, replicas and environment labels differ.

Secrets policy:

- No plaintext secrets in repository.
- Use masked GitLab variables and Kubernetes Secret references.

## Fully Wired Service and Smoke Test

Fully wired service: api-gateway.

Smoke test artifact: devOps/devops-checkpoint/smoke/api-gateway-smoke.sh

Behavior:

- Uses UNOARENA_API_URL (required env var).
- Calls gateway room-list endpoint as placeholder for canonical CLI flow.
- Asserts JSON response includes result == ok and rooms field.
- Retries at most once, then fails with non-zero exit code.

Note:

- Replace the placeholder transport call with your actual Client Checkpoint CLI command once your CLI binary is available in CI.

## Readiness Gate

Deployment path includes a readiness gate placeholder command:

- kubectl rollout status deployment/api-gateway -n staging

In shared environments, deploy job must remain blocked until rollout is healthy before integration-staging starts.

## Rollback Path

Rollback is executed with helm rollback api-gateway <previous_revision> in the target namespace, followed by rollout status verification.

## Coverage Matrix

| Service | test | build | deliver | deploy-staging | integration-staging | deliver-production | deploy-production | Notes |
|---|---|---|---|---|---|---|---|---|
| api-gateway | yes | yes | yes | yes | yes | optional | optional | fully wired |
| identity-service | yes | yes | yes | stubbed | stubbed | no | no | placeholder |
| room-gameplay-service | yes | yes | yes | stubbed | stubbed | no | no | placeholder |
| tournament-service | yes | yes | yes | stubbed | stubbed | no | no | placeholder |
| spectator-service | yes | yes | yes | stubbed | stubbed | no | no | placeholder |
| ranking-service | yes | yes | yes | stubbed | stubbed | no | no | placeholder |
| analytics-service | yes | yes | yes | stubbed | stubbed | no | no | placeholder |
| moderation-service | yes | yes | yes | stubbed | stubbed | no | no | placeholder |

Exactly one service has integration-staging active: api-gateway.

## Green Pipeline Evidence

Add at least one successful pipeline run URL reaching integration-staging:

- TODO: <paste green pipeline URL here>
