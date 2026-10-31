---
name: build-docker
description: Build and smoke-test the offline submission Docker image with predict.sh. Use for the final solution submission (deadline 2026-11-16 23:59 GMT+7).
---
Run `/compliance-audit` first. Then delegate to the `docker-packager` agent. Output: image tag, size, sha256 checksum command for the upload form, smoke-test result with `--network none`, and estimated full private-set runtime. Do not upload or push anything without explicit user confirmation.
