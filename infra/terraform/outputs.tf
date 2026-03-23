output "cluster_name" {
  value       = aws_ecs_cluster.radio.name
  description = "ECS cluster name."
}

output "service_name" {
  value       = aws_ecs_service.radio.name
  description = "ECS service name."
}

output "alb_dns_name" {
  value       = aws_lb.radio.dns_name
  description = "Public DNS name for the load balancer."
}

output "service_base_url" {
  value       = local.public_base_url
  description = "Base URL for the authenticated radio service."
}

output "okta_redirect_uri" {
  value       = "${local.public_base_url}/oauth2/idpresponse"
  description = "Redirect URI to register in the Okta OIDC app."
}
