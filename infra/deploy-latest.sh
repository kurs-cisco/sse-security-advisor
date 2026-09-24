#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REGION="us-gov-east-1"
ACCOUNT_ID="135124134289"
STACK_NAME="cbom-workbench-dev"
CLUSTER_NAME="cbom-workbench-dev"
SERVICE_NAME="cbom-workbench-web"
BUCKET="cbom-workbench-data-135124134289-us-gov-east-1"
RELEASE_PREFIX="transfer/releases/2026-09-24"
JOB_SECURITY_GROUP="sg-0da5ac19f21682b69"
PRIVATE_SUBNETS="subnet-0a79a031b7da0ee66,subnet-0f1689d4dc8f2ad5d,subnet-06bec111d36991f2a"
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
WEB_REPOSITORY="${ECR_REGISTRY}/cbom-workbench/web"
CATALOG_REPOSITORY="${ECR_REGISTRY}/cbom-workbench/catalog"

TARGET_FILE="${REPO_ROOT}/FIPS-140-3-21-sept.json"
PUBLIC_EVIDENCE_FILE="${REPO_ROOT}/cbom-catalog/evidence/fips-module-public-evidence-2026-09-21.json"
CATALOG_EVIDENCE_FILE="${REPO_ROOT}/cbom-catalog/evidence/current-version-correlation-2026-09-21.json"
SERVICE_IMPACT_FILE="${REPO_ROOT}/service_impact.csv"

for command in aws docker jq npx npm shasum; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command is missing: ${command}" >&2
    exit 1
  }
done

actual_account="$(aws sts get-caller-identity --query Account --output text)"
if [[ "${actual_account}" != "${ACCOUNT_ID}" ]]; then
  echo "Refusing deployment: expected AWS account ${ACCOUNT_ID}, got ${actual_account}" >&2
  exit 1
fi

verify_sha256() {
  local expected="$1"
  local path="$2"
  local actual
  actual="$(shasum -a 256 "${path}" | awk '{print $1}')"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "Checksum mismatch for ${path}: expected ${expected}, got ${actual}" >&2
    exit 1
  fi
}

verify_sha256 "158c2d2c82ff1b1e3a7e57bb1e95edad16f1c670e4f9223c4ccffaf847c6d45c" "${TARGET_FILE}"
verify_sha256 "585ff2e7e8ca2e2e1e9b0d1bbb4482c2e709013f37a655a884b2972e7026f26a" "${PUBLIC_EVIDENCE_FILE}"
verify_sha256 "9fca3902cb8d4afa96d23ad923601ddff03c2e9cf92eab201df5f34dd5cd335f" "${CATALOG_EVIDENCE_FILE}"
verify_sha256 "5c481b5941d081b537c8f88805b78820fddfbe8d42af6bc9138d2dedce055ecc" "${SERVICE_IMPACT_FILE}"

IMAGE_TAG="$(jq -er '.context.imageTag' "${SCRIPT_DIR}/cdk.json")"
if ! [[ "${IMAGE_TAG}" =~ ^deploy-[0-9]{8}-[0-9]+$ ]]; then
  echo "Refusing deployment: unexpected immutable image tag ${IMAGE_TAG}" >&2
  exit 1
fi

aws s3 cp "${TARGET_FILE}" "s3://${BUCKET}/${RELEASE_PREFIX}/FIPS-140-3-21-sept.json" \
  --region "${REGION}" --sse aws:kms --content-type application/json
aws s3 cp "${PUBLIC_EVIDENCE_FILE}" "s3://${BUCKET}/${RELEASE_PREFIX}/fips-module-public-evidence-2026-09-21.json" \
  --region "${REGION}" --sse aws:kms --content-type application/json
aws s3 cp "${CATALOG_EVIDENCE_FILE}" "s3://${BUCKET}/${RELEASE_PREFIX}/current-version-correlation-2026-09-21.json" \
  --region "${REGION}" --sse aws:kms --content-type application/json
aws s3 cp "${SERVICE_IMPACT_FILE}" "s3://${BUCKET}/${RELEASE_PREFIX}/service_impact.csv" \
  --region "${REGION}" --sse aws:kms --content-type text/tab-separated-values

aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin "${ECR_REGISTRY}"

docker build --platform linux/amd64 \
  --tag "${CATALOG_REPOSITORY}:${IMAGE_TAG}" \
  "${REPO_ROOT}/cbom-catalog"
docker build --platform linux/amd64 \
  --build-arg CBOM_API_ORIGIN=http://127.0.0.1:8000 \
  --tag "${WEB_REPOSITORY}:${IMAGE_TAG}" \
  "${REPO_ROOT}/cbom-console"
docker push "${CATALOG_REPOSITORY}:${IMAGE_TAG}"
docker push "${WEB_REPOSITORY}:${IMAGE_TAG}"

cd "${SCRIPT_DIR}"
npm run build
npx cdk synth --strict >/dev/null
npx cdk diff
npx cdk publish-assets --unstable=publish-assets CbomWorkbenchDev
aws cloudformation deploy \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}" \
  --template-file cdk.out/CbomWorkbenchDev.template.json \
  --s3-bucket cdk-hnb659fds-assets-135124134289-us-gov-east-1 \
  --s3-prefix cbom-workbench-dev/templates \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --no-fail-on-empty-changeset \
  --tags \
    ApplicationName='CBOM Workbench' \
    Environment=NONPROD \
    EnvironmentSubcategory=DEV \
    DataClassification='Cisco Restricted' \
    IntendedPublic=False

aws ecs wait services-stable --region "${REGION}" --cluster "${CLUSTER_NAME}" --services "${SERVICE_NAME}"

JOB_TASK="$(aws cloudformation describe-stacks \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}" \
  --query 'Stacks[0].Outputs[?OutputKey==`JobTaskDefinitionArn`].OutputValue | [0]' \
  --output text)"
if [[ -z "${JOB_TASK}" || "${JOB_TASK}" == "None" ]]; then
  echo "CloudFormation did not return the current job task definition" >&2
  exit 1
fi

read -r -d '' JOB_COMMAND <<'EOF' || true
python -c 'import boto3,os; client=boto3.client("s3"); bucket=os.environ["CBOM_SNAPSHOT_BUCKET"]; files=[("transfer/releases/2026-09-24/FIPS-140-3-21-sept.json","/tmp/target-modules.json"),("transfer/releases/2026-09-24/fips-module-public-evidence-2026-09-21.json","/tmp/public-evidence.json"),("transfer/releases/2026-09-24/current-version-correlation-2026-09-21.json","/tmp/catalog-evidence.json"),("transfer/releases/2026-09-24/service_impact.csv","/tmp/service_impact.csv")]; [client.download_file(bucket,key,path) for key,path in files]'
cbom-catalog migrate --schema /app/db
cbom-catalog import-target-modules /tmp/target-modules.json
cbom-catalog import-target-evidence /tmp/public-evidence.json
cbom-catalog import-catalog-claim-evidence /tmp/catalog-evidence.json
cbom-catalog import-service-impact /tmp/service_impact.csv --collection sse-cboms
EOF

overrides="$(jq -cn --arg command "${JOB_COMMAND}" \
  '{containerOverrides:[{name:"job",command:["sh","-ec",$command]}]}')"

task_arn="$(aws ecs run-task \
  --region "${REGION}" \
  --cluster "${CLUSTER_NAME}" \
  --launch-type FARGATE \
  --platform-version LATEST \
  --task-definition "${JOB_TASK}" \
  --network-configuration "awsvpcConfiguration={subnets=[${PRIVATE_SUBNETS}],securityGroups=[${JOB_SECURITY_GROUP}],assignPublicIp=DISABLED}" \
  --overrides "${overrides}" \
  --query 'tasks[0].taskArn' \
  --output text)"

if [[ -z "${task_arn}" || "${task_arn}" == "None" ]]; then
  echo "ECS did not return a migration/import task ARN" >&2
  exit 1
fi

aws ecs wait tasks-stopped --region "${REGION}" --cluster "${CLUSTER_NAME}" --tasks "${task_arn}"
task_exit="$(aws ecs describe-tasks --region "${REGION}" --cluster "${CLUSTER_NAME}" \
  --tasks "${task_arn}" --query 'tasks[0].containers[0].exitCode' --output text)"
task_id="${task_arn##*/}"
aws logs get-log-events --region "${REGION}" --log-group-name /cbom-workbench/dev/jobs \
  --log-stream-name "job/job/${task_id}" --query 'events[*].message' --output text || true
if [[ "${task_exit}" != "0" ]]; then
  echo "Migration/import task failed with exit code ${task_exit}" >&2
  exit 1
fi

aws cloudformation describe-stacks --region "${REGION}" --stack-name "${STACK_NAME}" \
  --query 'Stacks[0].{Status:StackStatus,Outputs:Outputs[?OutputKey==`Hostname` || OutputKey==`ServicesActivated` || OutputKey==`OidcEnabled`]}' \
  --output json
aws ecs describe-services --region "${REGION}" --cluster "${CLUSTER_NAME}" --services "${SERVICE_NAME}" \
  --query 'services[0].{desiredCount:desiredCount,runningCount:runningCount,pendingCount:pendingCount,rolloutState:deployments[0].rolloutState}' \
  --output json
