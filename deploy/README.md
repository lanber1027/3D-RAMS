# Hosted MVP Deployment

This folder contains the public-safe deployment helpers for the hosted 3D-RAMS MVP.

Current MVP deployment:

- Frontend: `https://main.d62sagixyhsmv.amplifyapp.com`
- API: `https://1rfpw4fi53.execute-api.eu-west-2.amazonaws.com`
- Region: `eu-west-2`

Do not commit generated files:

- `hosted-mvp-private.local.json`
- `hosted-mvp-summary.json`
- `amplify-summary.json`
- `*.zip`

## Backend

Build the Lambda package:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\build-lambda.ps1
```

Create or update AWS backend resources:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\deploy-aws.ps1
```

The backend script creates or updates:

- Lambda function;
- API Gateway HTTP API;
- IAM role and inline policy;
- DynamoDB session table with TTL;
- private S3 upload bucket with lifecycle deletion;
- CloudWatch log retention;
- local private access-code handoff file.

## Frontend

Build the frontend with the API Gateway URL:

```powershell
$env:VITE_API_BASE_URL="https://example.execute-api.eu-west-2.amazonaws.com"
Push-Location frontend
npm.cmd run build
Pop-Location
```

Deploy the built frontend to Amplify manual hosting:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\deploy-amplify.ps1
```

After Amplify returns the hosted URL, rerun `deploy-aws.ps1` with `-AmplifyOrigin` so backend CORS is restricted to the final frontend URL.

The Amplify deployment script writes a root-relative ZIP archive so hosted paths resolve as `index.html`, `assets/...`, and `cesium/...`. Avoid replacing this with a default Windows `Compress-Archive` call because backslash entries can break nested hosted asset paths.

## Smoke Test

Run the low-cost hosted memory regression first. It does not request Bedrock and checks the guarded conversation route that prevents a follow-up such as `What do you mean` from becoming a fake site request:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\smoke-hosted.ps1 -MemoryOnly
```

Equivalent Python fallback:

```powershell
python deploy\smoke-hosted.py --memory-only
```

Run the full hosted smoke only when you intend to spend the bounded Bedrock calls:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\smoke-hosted.ps1 -IncludeUnsafe
```

The smoke test uses the private local access-code handoff file and does not print the raw access code. Success summaries redact live session/run ids by default. Use `-IncludeIds` or `--include-ids` only for private debugging, and do not paste that output into public issues or docs.

Known limitation: setting Lambda reserved concurrency to `2` may fail in small AWS accounts if it would reduce unreserved account concurrency below AWS's required minimum. The script warns and continues; access-code gating, low tester volume, Bedrock model-call caps, token caps, and the AWS budget alert remain the MVP cost controls.
