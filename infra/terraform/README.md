# Terraform Deployment

This stack provisions the minimum AWS shape for the radio service:

- ECS Fargate cluster, task definition, and single-task service
- Application Load Balancer with HTTP to HTTPS redirect
- HTTPS listener using Okta OIDC authentication at the ALB
- Target group health checks against `/readyz`
- CloudWatch log group
- IAM roles for task execution and app access to S3 and Polly

## Inputs

The stack assumes you already have:

- An existing VPC with public and private subnets
- An ACM certificate in `eu-west-2`
- A pushed container image in ECR or another registry
- An Okta OIDC web app with the ALB callback URL registered
- An AWS Secrets Manager secret containing the Okta client secret

Start from `terraform.tfvars.example` and set the real values for your environment.

## Okta Setup

After the ALB exists, register this redirect URI in the Okta app:

```text
https://<service-hostname>/oauth2/idpresponse
```

If you use a custom domain, that is the hostname to register. Otherwise use the ALB DNS name emitted in `alb_dns_name`.

## Notes

- The ECS service is intentionally configured with `desired_count = 1`, `deployment_minimum_healthy_percent = 0`, and `deployment_maximum_percent = 100` so a new deployment replaces the single live task instead of overlapping two HLS generators.
- Terraform reads the Okta client secret from Secrets Manager and passes it to the ALB listener. Use encrypted remote state and restrict state access accordingly.
- Production config is injected through `RADIO__...` environment overrides, with `/app/config/radio.ecs.yaml` as the base file.
