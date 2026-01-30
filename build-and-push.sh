#!/bin/bash
# Build and push Kencove Sentry image to Google Artifact Registry
#
# Usage:
#   ./build-and-push.sh                    # Build with commit SHA tag
#   ./build-and-push.sh v26.1.0-gitlab     # Build with custom tag
#   ./build-and-push.sh --local            # Build locally without pushing

set -euo pipefail

# Configuration
PROJECT_ID="${PROJECT_ID:-kencove-prod}"
REGION="${REGION:-us-central1}"
REPOSITORY="${REPOSITORY:-kencove-docker-repo}"
IMAGE_NAME="${IMAGE_NAME:-sentry}"
TAG="${1:-$(git rev-parse --short HEAD)}"

FULL_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}"

echo "=== Kencove Sentry Build ==="
echo "Image: ${FULL_IMAGE}:${TAG}"
echo "Commit: $(git rev-parse HEAD)"
echo ""

if [[ "${1:-}" == "--local" ]]; then
    echo "Building locally (not pushing)..."
    docker build \
        -t "${IMAGE_NAME}:${TAG}" \
        -t "${IMAGE_NAME}:latest" \
        -f self-hosted/Dockerfile.kencove \
        --build-arg SOURCE_COMMIT="$(git rev-parse HEAD)" \
        --progress=plain \
        .
    echo ""
    echo "Local build complete: ${IMAGE_NAME}:${TAG}"
    exit 0
fi

# Check if using Cloud Build or local Docker
if command -v gcloud &> /dev/null && [[ "${USE_CLOUD_BUILD:-true}" == "true" ]]; then
    echo "Using Cloud Build..."
    gcloud builds submit \
        --config=cloudbuild.yaml \
        --substitutions="_TAG=${TAG}" \
        --project="${PROJECT_ID}" \
        .
else
    echo "Using local Docker build + push..."

    # Configure Docker for GAR
    gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

    # Build
    docker build \
        -t "${FULL_IMAGE}:${TAG}" \
        -t "${FULL_IMAGE}:latest" \
        -f self-hosted/Dockerfile.kencove \
        --build-arg SOURCE_COMMIT="$(git rev-parse HEAD)" \
        --progress=plain \
        .

    # Push
    docker push "${FULL_IMAGE}:${TAG}"
    docker push "${FULL_IMAGE}:latest"
fi

echo ""
echo "=== Build Complete ==="
echo "Image: ${FULL_IMAGE}:${TAG}"
echo ""
echo "To use in Helm values:"
echo "  images:"
echo "    sentry:"
echo "      repository: ${FULL_IMAGE}"
echo "      tag: \"${TAG}\""
