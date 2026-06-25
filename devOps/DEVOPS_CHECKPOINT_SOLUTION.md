# UnoArena DevOps Checkpoint Solution

## 1. Context and objective

UnoArena is a real-time multiplayer platform with casual rooms and large elimination tournaments. This DevOps checkpoint proves the architecture can be delivered as independently deployable services through a fail-fast CI/CD pipeline in one GitLab monorepo.

This solution intentionally keeps services as placeholders and validates delivery mechanics:

- Per-service pipeline fragments
- Independent change-triggered execution
- One service wired end to end to staging with CLI smoke test
- Build once, promote by immutable image digest

## 2. Selected strategy

- Deployment model: Helm from pipeline
- Fully wired service: api-gateway
- Service scope for this checkpoint:
  - api-gateway
  - identity-service
  - room-gameplay-service
  - tournament-service
  - spectator-service
  - ranking-service
  - analytics-service
  - moderation-service

Rationale:

- Helm from pipeline provides direct evidence of deploy readiness and rollback.
- api-gateway is the strongest CLI smoke-test entrypoint from the client contract.

## 3. Required repository layout

Recommended structure:

- api-gateway/
- identity-service/
- room-gameplay-service/
- tournament-service/
- spectator-service/
- ranking-service/
- analytics-service/
- moderation-service/
- ci/templates/
- ci/services/
- deploy/charts/
- devops-checkpoint/smoke/

Each service folder contains:

- Placeholder app with GET /health
- At least one trivial unit test
- Service-specific Dockerfile

For api-gateway only:

- One canned endpoint for CLI assertion, for example GET /v1/whoami

## 4. Architecture to delivery mapping

| Architecture service | Source folder | Pipeline fragment | Helm chart | Container image | Helm release | Wiring depth |
|---|---|---|---|---|---|---|
| api-gateway | api-gateway | ci/services/api-gateway.gitlab-ci.yml | deploy/charts/api-gateway | registry/group/project/api-gateway | api-gateway | test, build, deliver, deploy-staging, integration-staging, optional production |
| identity-service | identity-service | ci/services/identity-service.gitlab-ci.yml | deploy/charts/identity-service | registry/group/project/identity-service | identity-service | test, build, deliver |
| room-gameplay-service | room-gameplay-service | ci/services/room-gameplay-service.gitlab-ci.yml | deploy/charts/room-gameplay-service | registry/group/project/room-gameplay-service | room-gameplay-service | test, build, deliver |
| tournament-service | tournament-service | ci/services/tournament-service.gitlab-ci.yml | deploy/charts/tournament-service | registry/group/project/tournament-service | tournament-service | test, build, deliver |
| spectator-service | spectator-service | ci/services/spectator-service.gitlab-ci.yml | deploy/charts/spectator-service | registry/group/project/spectator-service | spectator-service | test, build, deliver |
| ranking-service | ranking-service | ci/services/ranking-service.gitlab-ci.yml | deploy/charts/ranking-service | registry/group/project/ranking-service | ranking-service | test, build, deliver |
| analytics-service | analytics-service | ci/services/analytics-service.gitlab-ci.yml | deploy/charts/analytics-service | registry/group/project/analytics-service | analytics-service | test, build, deliver |
| moderation-service | moderation-service | ci/services/moderation-service.gitlab-ci.yml | deploy/charts/moderation-service | registry/group/project/moderation-service | moderation-service | test, build, deliver |

## 5. Pipeline stage spine

Canonical stages per service:

1. test
2. build
3. deliver
4. deploy-staging
5. integration-staging
6. deliver-production (optional)
7. deploy-production (optional)

Rules:

- All services execute test, build, deliver.
- Only api-gateway executes deploy-staging and integration-staging.
- Per-service needs relationships enforce fail-fast progression.

## 6. Fail-fast and cross-service blocking

- If test fails for a service, build and all downstream stages for that service do not run.
- Shared contract checks run in test stage and block affected producer and consumer paths when contracts change.
- Retries, if any, must be explicit and bounded.

## 7. Change detection and independent deployability

Per-service jobs use path-based triggers on:

- Service source path
- Service Dockerfile
- Service chart path
- Shared CI template paths (when relevant)

Expected behavior:

- A change limited to one service triggers only that service path.
- No full-repo rebuild unless a shared base artifact changes and justification is documented.

## 8. Test stage minimum bar

Per service:

- One trivial unit test
- One static analysis step for chosen stack
- Optional but recommended illustrative contract check on one interface

## 9. Build and deliver model

- One service equals one container image.
- Image tags carry readable provenance and immutable identity.
- Deliver stage exports image digest artifact.
- Deploy stages consume digest, not mutable tags.
- Staging and production use the same built artifact.

## 10. Helm deployment requirements

For api-gateway full path:

- Deploy with helm upgrade --install
- Gate readiness with rollout status
- Start integration only after healthy rollout

Environment separation:

- Staging and production differ in at least one meaningful value, such as replicas or resource limits.

Secrets policy:

- No plaintext secrets in repo
- Use masked CI variables and Kubernetes Secret references

Rollback path:

- Use helm rollback to previous successful release revision and validate readiness before reopening traffic.

## 11. Staging integration smoke test via CLI

Smoke test requirements:

- Use Client CLI command against staging URL from UNOARENA_API_URL
- Use JSON output mode
- Assert canned response fields
- Fail non-zero on unreachable service, timeout, or payload mismatch
- Allow at most one explicit retry

Recommended flow:

1. Invoke CLI against api-gateway, for example whoami in JSON mode.
2. Validate result and expected payload fields.
3. Emit clear pass or fail status.

## 12. Observability seam

- api-gateway placeholder emits at least one structured log line on smoke-hit.
- Document operator retrieval path with kubectl logs for staging.

## 13. Service coverage matrix

| Service | test | build | deliver | deploy-staging | integration-staging | deliver-production | deploy-production | Notes |
|---|---|---|---|---|---|---|---|---|
| api-gateway | yes | yes | yes | yes | yes | optional | optional | fully wired demonstrator |
| identity-service | yes | yes | yes | no | no | no | no | placeholder |
| room-gameplay-service | yes | yes | yes | no | no | no | no | placeholder |
| tournament-service | yes | yes | yes | no | no | no | no | placeholder |
| spectator-service | yes | yes | yes | no | no | no | no | placeholder |
| ranking-service | yes | yes | yes | no | no | no | no | placeholder |
| analytics-service | yes | yes | yes | no | no | no | no | placeholder |
| moderation-service | yes | yes | yes | no | no | no | no | placeholder |

## 14. Mandatory deliverables checklist

1. Root .gitlab-ci.yml plus per-service pipeline fragments
2. Placeholder source, Dockerfile, and Helm chart per service
3. CLI-driven staging smoke test for api-gateway
4. devops-checkpoint README with pipeline narrative and matrix
5. One green pipeline run link reaching integration-staging
6. No plaintext secrets in repository
7. Build once and promote by digest

## 15. Green-run evidence placeholder

- integration-staging successful pipeline URL: TO_BE_FILLED

## 16. Suggested next implementation order

1. Scaffold service placeholders and Dockerfiles
2. Add Helm charts and staging or production values
3. Add root CI and per-service CI fragments
4. Implement api-gateway deploy-staging and CLI smoke test
5. Run first green pipeline and fill evidence URL
