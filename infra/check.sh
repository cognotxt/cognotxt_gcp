#!/usr/bin/env bash
set -euo pipefail
source "${1:-$(dirname "$0")/config.env}"
echo "Cloud Run:"
gcloud run services list --region="$REGION"
echo
echo "Cloud Run Jobs:"
gcloud run jobs list --region="$REGION"
echo
echo "Eventarc:"
gcloud eventarc triggers list --location="$REGION"
echo
echo "Bucket CORS:"
gcloud storage buckets describe "gs://$BUCKET_NAME" --format='json(cors)'
