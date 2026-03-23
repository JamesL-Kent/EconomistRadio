variable "name" {
  description = "Base name for the ECS service and related resources."
  type        = string
  default     = "economist-radio"
}

variable "aws_region" {
  description = "AWS region for the deployment."
  type        = string
  default     = "eu-west-2"
}

variable "vpc_id" {
  description = "VPC that hosts the ALB and ECS service."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for the internet-facing ALB."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnets for the Fargate tasks."
  type        = list(string)
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the HTTPS listener."
  type        = string
}

variable "domain_name" {
  description = "Optional custom DNS name. If omitted, the ALB DNS name is used."
  type        = string
  default     = ""
}

variable "image_uri" {
  description = "Container image URI for the radio service."
  type        = string
}

variable "content_bucket" {
  description = "S3 bucket that stores source audio and metadata."
  type        = string
}

variable "content_prefix" {
  description = "S3 prefix under the source bucket."
  type        = string
}

variable "stream_mirror_bucket" {
  description = "Optional S3 bucket for mirroring generated HLS output."
  type        = string
  default     = ""
}

variable "stream_mirror_prefix" {
  description = "Optional prefix for mirrored HLS output."
  type        = string
  default     = "radio/live"
}

variable "app_port" {
  description = "Container port exposed by the FastAPI service."
  type        = number
  default     = 8000
}

variable "health_check_path" {
  description = "ALB health check path."
  type        = string
  default     = "/readyz"
}

variable "desired_count" {
  description = "Desired number of ECS tasks. The service is designed for a single live task."
  type        = number
  default     = 1
}

variable "cpu" {
  description = "Task CPU units."
  type        = number
  default     = 2048
}

variable "memory" {
  description = "Task memory in MiB."
  type        = number
  default     = 4096
}

variable "ephemeral_storage_gib" {
  description = "Ephemeral storage allocated to the task."
  type        = number
  default     = 50
}

variable "okta_issuer" {
  description = "Okta issuer URL."
  type        = string
}

variable "okta_authorization_endpoint" {
  description = "Okta authorization endpoint URL."
  type        = string
}

variable "okta_token_endpoint" {
  description = "Okta token endpoint URL."
  type        = string
}

variable "okta_user_info_endpoint" {
  description = "Okta user info endpoint URL."
  type        = string
}

variable "okta_client_id" {
  description = "Okta OIDC client ID used by the ALB."
  type        = string
}

variable "okta_client_secret_secret_id" {
  description = "Secrets Manager secret id or ARN containing the Okta client secret."
  type        = string
}

variable "okta_scope" {
  description = "OIDC scopes requested by the ALB."
  type        = string
  default     = "openid profile email"
}

variable "okta_session_timeout" {
  description = "Authentication session duration in seconds."
  type        = number
  default     = 604800
}
