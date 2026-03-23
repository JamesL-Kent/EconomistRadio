terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_secretsmanager_secret_version" "okta_client_secret" {
  secret_id = var.okta_client_secret_secret_id
}

locals {
  service_name    = var.name
  public_hostname = trimspace(var.domain_name) != "" ? var.domain_name : aws_lb.radio.dns_name
  public_base_url = "https://${local.public_hostname}"

  source_prefix     = trim(var.content_prefix, "/")
  source_bucket_arn = "arn:aws:s3:::${var.content_bucket}"
  source_object_arn = local.source_prefix != "" ? "${local.source_bucket_arn}/${local.source_prefix}/*" : "${local.source_bucket_arn}/*"

  environment = concat(
    [
      { name = "RADIO_CONFIG_PATH", value = "/app/config/radio.ecs.yaml" },
      { name = "RADIO__CONTENT__BACKEND", value = "s3" },
      { name = "RADIO__CONTENT__S3_BUCKET", value = var.content_bucket },
      { name = "RADIO__CONTENT__S3_PREFIX", value = var.content_prefix },
      { name = "RADIO__CONTENT__AWS_REGION", value = var.aws_region },
      { name = "RADIO__OUTPUT__PUBLIC_BASE_URL", value = local.public_base_url },
      { name = "PORT", value = tostring(var.app_port) }
    ],
    var.stream_mirror_bucket != "" ? [{ name = "RADIO__OUTPUT__S3_BUCKET", value = var.stream_mirror_bucket }] : [],
    var.stream_mirror_bucket != "" && var.stream_mirror_prefix != "" ? [{ name = "RADIO__OUTPUT__S3_PREFIX", value = var.stream_mirror_prefix }] : []
  )
}

resource "aws_cloudwatch_log_group" "radio" {
  name              = "/ecs/${local.service_name}"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "radio" {
  name = local.service_name
}

resource "aws_iam_role" "execution" {
  name = "${local.service_name}-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name = "${local.service_name}-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "task" {
  name = "${local.service_name}-task"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Effect   = "Allow"
          Action   = ["s3:ListBucket"]
          Resource = local.source_bucket_arn
          Condition = {
            StringLike = {
              "s3:prefix" = local.source_prefix != "" ? ["${local.source_prefix}/*"] : ["*"]
            }
          }
        },
        {
          Effect   = "Allow"
          Action   = ["s3:GetObject"]
          Resource = local.source_object_arn
        },
        {
          Effect   = "Allow"
          Action   = ["polly:SynthesizeSpeech"]
          Resource = "*"
        },
        {
          Effect = "Allow"
          Action = ["logs:CreateLogStream", "logs:PutLogEvents"]
          Resource = [
            aws_cloudwatch_log_group.radio.arn,
            "${aws_cloudwatch_log_group.radio.arn}:*"
          ]
        }
      ],
      var.stream_mirror_bucket != "" ? [
        {
          Effect = "Allow"
          Action = ["s3:PutObject"]
          Resource = [
            "arn:aws:s3:::${var.stream_mirror_bucket}/${trim(var.stream_mirror_prefix, "/")}/*"
          ]
        }
      ] : []
    )
  })
}

resource "aws_security_group" "alb" {
  name        = "${local.service_name}-alb"
  description = "ALB ingress for Economist Radio"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "service" {
  name        = "${local.service_name}-service"
  description = "App ingress from the Economist Radio ALB"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = var.app_port
    to_port         = var.app_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "radio" {
  name               = substr(regexreplace(local.service_name, "[^a-zA-Z0-9-]", "-"), 0, 32)
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids
}

resource "aws_lb_target_group" "radio" {
  name        = substr(regexreplace("${local.service_name}-tg", "[^a-zA-Z0-9-]", "-"), 0, 32)
  port        = var.app_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = var.health_check_path
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.radio.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.radio.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type  = "authenticate-oidc"
    order = 1

    authenticate_oidc {
      authorization_endpoint = var.okta_authorization_endpoint
      client_id              = var.okta_client_id
      client_secret          = data.aws_secretsmanager_secret_version.okta_client_secret.secret_string
      issuer                 = var.okta_issuer
      on_unauthenticated_request = "authenticate"
      scope                      = var.okta_scope
      session_cookie_name        = "${replace(local.service_name, "-", "_")}_auth"
      session_timeout            = var.okta_session_timeout
      token_endpoint             = var.okta_token_endpoint
      user_info_endpoint         = var.okta_user_info_endpoint
    }
  }

  default_action {
    type  = "forward"
    order = 2

    forward {
      target_group {
        arn = aws_lb_target_group.radio.arn
      }
    }
  }
}

resource "aws_ecs_task_definition" "radio" {
  family                   = local.service_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  ephemeral_storage {
    size_in_gib = var.ephemeral_storage_gib
  }

  container_definitions = jsonencode([
    {
      name      = "radio"
      image     = var.image_uri
      essential = true
      portMappings = [
        {
          containerPort = var.app_port
          hostPort      = var.app_port
          protocol      = "tcp"
        }
      ]
      environment = local.environment
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.radio.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "radio" {
  name                               = local.service_name
  cluster                            = aws_ecs_cluster.radio.id
  task_definition                    = aws_ecs_task_definition.radio.arn
  launch_type                        = "FARGATE"
  desired_count                      = var.desired_count
  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.radio.arn
    container_name   = "radio"
    container_port   = var.app_port
  }

  depends_on = [aws_lb_listener.https]
}
