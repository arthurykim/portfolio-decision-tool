#!/usr/bin/env bash
# Build, push to ECR, and create/update an AWS App Runner service.
# Prereqs: aws cli v2 configured (aws configure), docker running.
# Usage: ./deploy/aws-apprunner.sh [region]
set -euo pipefail

REGION="${1:-us-east-1}"
APP_NAME="portfolio-decision-tool"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${APP_NAME}"

echo "==> Ensuring ECR repository exists"
aws ecr describe-repositories --repository-names "$APP_NAME" --region "$REGION" >/dev/null 2>&1 ||
  aws ecr create-repository --repository-name "$APP_NAME" --region "$REGION" >/dev/null

echo "==> Building and pushing image"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REPO"
docker build --platform linux/amd64 -t "$ECR_REPO:latest" .
docker push "$ECR_REPO:latest"

echo "==> Ensuring App Runner ECR access role exists"
ROLE_NAME="AppRunnerECRAccessRole"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "build.apprunner.amazonaws.com"}, "Action": "sts:AssumeRole"}]
  }' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess
  echo "    created ${ROLE_NAME}; waiting for IAM propagation"
  sleep 15
fi
ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)

SERVICE_ARN=$(aws apprunner list-services --region "$REGION" \
  --query "ServiceSummaryList[?ServiceName=='${APP_NAME}'].ServiceArn" --output text)

if [ -z "$SERVICE_ARN" ]; then
  echo "==> Creating App Runner service"
  aws apprunner create-service --region "$REGION" --service-name "$APP_NAME" \
    --source-configuration '{
      "AuthenticationConfiguration": {"AccessRoleArn": "'"$ROLE_ARN"'"},
      "AutoDeploymentsEnabled": true,
      "ImageRepository": {
        "ImageIdentifier": "'"$ECR_REPO"':latest",
        "ImageRepositoryType": "ECR",
        "ImageConfiguration": {"Port": "8000"}
      }
    }' \
    --instance-configuration '{"Cpu": "1024", "Memory": "2048"}' \
    --health-check-configuration '{"Protocol": "HTTP", "Path": "/healthz"}' \
    --query "Service.ServiceUrl" --output text
else
  echo "==> Service exists; starting new deployment"
  aws apprunner start-deployment --region "$REGION" --service-arn "$SERVICE_ARN" >/dev/null
  aws apprunner describe-service --region "$REGION" --service-arn "$SERVICE_ARN" \
    --query "Service.ServiceUrl" --output text
fi

echo "==> Done. The URL above serves the app once the service reaches RUNNING."
