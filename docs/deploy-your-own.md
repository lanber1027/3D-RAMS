# Deploy Your Own 3D-RAMS LLM Stack

This guide is for external users who clone or fork the repo and want their own live Bedrock-backed 3D-RAMS agent.

Judges and teammates should normally use the hosted demo URL plus the private access code from the maintainer. Cloning the repo alone does not give you access to the maintained hosted Bedrock backend.

## What Works Without AWS

You can run the local deterministic demo without AWS:

- FastAPI backend;
- React/Vite frontend;
- cached public and synthetic fixtures;
- intent parsing, location confirmation, evidence register, trace, safety gate, 3D scene config;
- deterministic fallback review pack;
- local tests and evaluation scripts.

Without AWS, the live Bedrock planner/synthesis path, hosted session tracing, private S3 upload targets, CloudWatch logs, and deployed browser URL are not available.

## AWS Prerequisites

Before deploying the live LLM version, prepare:

- an AWS account you control;
- billing/payment preferences and a small budget alert;
- AWS CLI or another deployment method with permissions to create/update the resources below;
- Bedrock model access in your target region;
- a private tester access code that you do not commit.

The maintained demo used Amazon Bedrock Claude in `eu-west-2`, but you should choose a model and region that are enabled in your own AWS account.

## Required AWS Resources

A production-shaped MVP needs these resources:

- Lambda for the FastAPI backend;
- API Gateway HTTP API in front of Lambda;
- Amazon Bedrock for server-side model calls;
- Amplify Hosting, or S3 plus CloudFront, for the frontend;
- DynamoDB for tester session/run metadata;
- private S3 bucket for uploaded PDF/image evidence targets;
- IAM role scoped to Bedrock invoke, DynamoDB, S3, and CloudWatch logs;
- CloudWatch Logs for structured operational events.

The frontend must call only your hosted API. It must not call Bedrock, S3, DynamoDB, or AWS APIs directly.

## Backend Environment Variables

Set these on the backend runtime, not in the frontend bundle and not in GitHub:

```bash
APP_ENV=hosted
ALLOWED_ORIGINS=https://your-frontend.example.com,http://localhost:5173,http://127.0.0.1:5173
APP_ACCESS_TOKEN_HASH=<sha256-of-private-test-code>
APP_ACCESS_CODE_LABEL=team-test
ENABLE_BEDROCK=true
AWS_REGION=<your-aws-region>
BEDROCK_MODEL_ID=<enabled-bedrock-model-id>
BEDROCK_MAX_TOKENS=1200
BEDROCK_TEMPERATURE=0.2
BEDROCK_MAX_MODEL_CALLS=2
BEDROCK_PLANNER_MAX_TOKENS=900
BEDROCK_REASONER_MAX_TOKENS=1500
BEDROCK_COMPILER_MAX_TOKENS=2200
DURABLE_RUN_MAX_TOOL_CALLS=10
DURABLE_RUN_TIMEOUT_SECONDS=45
DURABLE_RUN_PROCESS_INLINE=true
DYNAMODB_SESSION_TABLE=<your-session-table>
S3_UPLOAD_BUCKET=<your-private-upload-bucket>
UPLOAD_RETENTION_DAYS=7
SESSION_RETENTION_DAYS=7
ENABLE_GEOAPIFY_GEOCODING=false
GEOAPIFY_API_KEY=
```

For local development with AWS credentials, you may also use `AWS_PROFILE=<your-local-profile>`. Do not set local profile names or AWS credentials in hosted frontend code.

## Frontend Environment Variable

Set this before building the frontend for deployment:

```bash
VITE_API_BASE_URL=https://your-api-gateway-url.example.com
```

Leave `VITE_API_BASE_URL` blank only for local development where the Vite dev proxy is configured.

## Access-Code Hash Pattern

Choose a private access code and store only its SHA-256 hash in the backend environment:

```bash
python -c "import hashlib; print(hashlib.sha256('replace-with-private-code'.encode()).hexdigest())"
```

Rules:

- never commit the raw access code;
- never commit the live hash if it identifies your hosted environment;
- never place the raw access code in screenshots, issue reports, public docs, or frontend code;
- rotate the code if it is shared outside the intended test group.

## Security Rules

- Bedrock must be called only from the backend.
- The browser frontend must not contain AWS credentials, Bedrock calls, S3 credentials, DynamoDB access, or API keys.
- Restrict CORS to your frontend URL and local development URLs.
- Keep S3 buckets private and block public access.
- Use IAM least privilege for Lambda.
- Do not log raw access codes, uploaded file contents, private documents, or secrets.
- Do not upload client data, access-controlled planning documents, or confidential site records for demo testing.
- Keep all outputs bounded as a human-review pre-visit pack, not certified RAMS, emergency guidance, or approval to work.

## Deployment Sequence

High-level sequence:

1. Confirm AWS budget, model access, and region.
2. Create or choose the private access code and generate its SHA-256 hash.
3. Create DynamoDB session table with TTL.
4. Create private S3 upload bucket with lifecycle deletion.
5. Create Lambda IAM role and scoped inline policy.
6. Package and deploy the FastAPI backend to Lambda.
7. Create API Gateway HTTP API pointing to Lambda.
8. Configure backend environment variables and CORS.
9. Build frontend with `VITE_API_BASE_URL` set to the API Gateway URL.
10. Deploy frontend through Amplify Hosting, or S3 plus CloudFront.
11. Run smoke checks: health, wrong access code `401`, session start, upload registration, Bedrock run, location confirmation, unsafe request block.
12. Monitor CloudWatch logs and Bedrock usage.

This repo includes deployment scripts used for the maintained demo, but they are not a universal installer. Review them before use and adapt names, regions, permissions, budget controls, and hosting choices to your AWS account.

## Cost Controls

Recommended MVP controls:

- set a small AWS budget alert before testing;
- keep `BEDROCK_MAX_MODEL_CALLS=2` per run;
- keep output token caps modest;
- use low temperature such as `0.2`;
- keep test access code private;
- avoid public unrestricted endpoints;
- use API Gateway throttling or WAF/rate limiting for broader testing;
- set S3 upload lifecycle deletion;
- set CloudWatch log retention.

## Teardown Reminder

When testing is complete, remove or disable resources you no longer need:

- Amplify app or S3/CloudFront frontend;
- API Gateway;
- Lambda function;
- DynamoDB table;
- S3 upload bucket and objects;
- IAM role/policies;
- CloudWatch log group;
- any provider keys or environment variables.

Check AWS Billing and Cost Management afterward.
