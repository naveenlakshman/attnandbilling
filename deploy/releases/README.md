# Individual release builds

These Dockerfiles and Cloud Build configurations record the isolated releases used
to validate and publish specific ERP changes. They extend pinned historical images;
use the root build files for a full application build from the current source tree.

Run an individual release build from the **repository root**, specifying its config
under this directory. Dockerfile references inside each config have been updated
to this location. Supply the image substitutions required by the chosen config.

```powershell
gcloud builds submit . --config=deploy/releases/cloudbuild.cashfree-panel.yaml --substitutions=_IMAGE=REGION-docker.pkg.dev/PROJECT/REPOSITORY/IMAGE:TAG --project=PROJECT --region=REGION
```

This folder contains build definitions, not credentials or database exports.
Publishing an image does not itself apply schema migrations or route production
traffic. Follow the root deployment runbook for those steps.
