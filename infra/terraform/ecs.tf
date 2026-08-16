# ECS Fargate services.
#
# Status: not applied to a live account. See the note at the top of main.tf.
#
# Four services on one cluster. The three APIs sit behind one load balancer
# routed by path prefix. The Celery worker has no load balancer and no
# inbound rule at all: it reaches Redis and FidelityCheck outbound and
# nothing reaches it.

locals {
  api_services = {
    synthecore = {
      port          = 8001
      path_prefix   = "/api/synthecore"
      cpu           = 512
      memory        = 1024
      desired_count = var.environment == "production" ? 2 : 1
    }
    fidelitycheck = {
      port        = 8002
      path_prefix = "/api/fidelity"
      # Validation is the CPU heavy path: scipy over a 100k row frame. It gets
      # the largest task size of the three APIs.
      cpu           = 1024
      memory        = 2048
      desired_count = var.environment == "production" ? 2 : 1
    }
    fhirlink = {
      port          = 8003
      path_prefix   = "/api/fhir"
      cpu           = 512
      memory        = 1024
      desired_count = var.environment == "production" ? 2 : 1
    }
  }
}

resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = var.environment == "production" ? "enabled" : "disabled"
  }
}

resource "aws_cloudwatch_log_group" "services" {
  for_each = merge(local.api_services, { synthecore-worker = {}, web = {} })

  name              = "/ecs/${local.name}/${each.key}"
  retention_in_days = var.environment == "production" ? 90 : 14
  kms_key_id        = aws_kms_key.data.arn
}

# ---------------------------------------------------------------------------
# Security groups
# ---------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name   = "${local.name}-alb"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.allowed_ingress_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "service" {
  name   = "${local.name}-service"
  vpc_id = aws_vpc.main.id

  # Only the load balancer may reach a task, and only on the app ports.
  ingress {
    from_port       = 8001
    to_port         = 8003
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # Services call each other by service discovery name inside the VPC.
  ingress {
    from_port = 8001
    to_port   = 8003
    protocol  = "tcp"
    self      = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

variable "allowed_ingress_cidrs" {
  type = list(string)
  # Deliberately not 0.0.0.0/0 by default. Opening this product to the public
  # internet should be a decision someone writes down, not an inherited
  # default.
  default     = []
  description = "CIDRs permitted to reach the load balancer. Empty blocks all ingress."
}

variable "certificate_arn" {
  type        = string
  description = "ACM certificate for the load balancer listener."
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Image tag to deploy. The deploy workflow passes the commit SHA."
}

variable "ecr_registry" {
  type = string
}

# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "task_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
}

data "aws_iam_policy_document" "task" {
  # Least privilege on the buckets: read seed, write exports, and nothing
  # else. In particular no s3:DeleteObject, so a bug in the service cannot
  # destroy a sponsor's uploaded extract.
  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.seed.arn}/*"]
  }

  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.export.arn}/*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.seed.arn, aws_s3_bucket.export.arn]
  }

  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.data.arn]
  }

  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.database.arn]
  }
}

resource "aws_iam_role_policy" "task" {
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# ---------------------------------------------------------------------------
# Load balancer
# ---------------------------------------------------------------------------

resource "aws_lb" "main" {
  name               = local.name
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]

  drop_invalid_header_fields = true
  enable_deletion_protection = var.environment == "production"
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_target_group" "api" {
  for_each = local.api_services

  name        = "${local.name}-${each.key}"
  port        = each.value.port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # SSE progress streams are long lived. The default 300 second deregistration
  # delay cuts them off mid job during a deploy.
  deregistration_delay = 60
}

resource "aws_lb_target_group" "web" {
  name        = "${local.name}-web"
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path    = "/"
    matcher = "200"
  }
}

resource "aws_lb_listener_rule" "api" {
  for_each = local.api_services

  listener_arn = aws_lb_listener.https.arn
  priority     = index(keys(local.api_services), each.key) + 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[each.key].arn
  }

  condition {
    path_pattern {
      values = ["${each.value.path_prefix}/*"]
    }
  }
}

# ---------------------------------------------------------------------------
# Task definitions and services
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  for_each = local.api_services

  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = each.key
      image     = "${var.ecr_registry}/pretrial-${each.key}:${var.image_tag}"
      essential = true

      portMappings = [{ containerPort = each.value.port, protocol = "tcp" }]

      environment = [
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "REDIS_URL", value = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0" },
        { name = "CELERY_BROKER_URL", value = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/1" },
        { name = "CELERY_RESULT_BACKEND", value = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/2" },
        { name = "COHORT_STORAGE", value = "s3" },
        { name = "S3_BUCKET_SEED", value = aws_s3_bucket.seed.id },
        { name = "S3_BUCKET_EXPORT", value = aws_s3_bucket.export.id },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "FIDELITYCHECK_URL", value = "http://fidelitycheck.${local.name}.local:8002" },
      ]

      secrets = [
        { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database.arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.services[each.key].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "api" {
  for_each = local.api_services

  name            = "pretrial-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api[each.key].arn
  desired_count   = each.value.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api[each.key].arn
    container_name   = each.key
    container_port   = each.value.port
  }

  service_registries {
    registry_arn = aws_service_discovery_service.api[each.key].arn
  }

  # Roll forward with both versions live briefly rather than taking capacity
  # down. A validation request in flight during a deploy should complete.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  health_check_grace_period_seconds = 60

  lifecycle {
    # The deploy workflow forces new deployments with the same task
    # definition family, so Terraform should not fight it over desired_count.
    ignore_changes = [desired_count]
  }
}

# ---------------------------------------------------------------------------
# The Celery worker
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-synthecore-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  # A CTGAN fit is the heaviest thing this system does, and it runs here
  # rather than in a request. The worker gets the largest task size.
  cpu                = 2048
  memory             = 8192
  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "synthecore-worker"
      image     = "${var.ecr_registry}/pretrial-synthecore:${var.image_tag}"
      essential = true

      command = [
        "celery", "-A", "app.celery_app:celery_app", "worker",
        "--loglevel=info", "--pool=solo", "--concurrency=1",
      ]

      environment = [
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "REDIS_URL", value = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0" },
        { name = "CELERY_BROKER_URL", value = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/1" },
        { name = "CELERY_RESULT_BACKEND", value = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/2" },
        { name = "COHORT_STORAGE", value = "s3" },
        { name = "S3_BUCKET_SEED", value = aws_s3_bucket.seed.id },
        { name = "S3_BUCKET_EXPORT", value = aws_s3_bucket.export.id },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "FIDELITYCHECK_URL", value = "http://fidelitycheck.${local.name}.local:8002" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.services["synthecore-worker"].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "worker" {
  name            = "pretrial-synthecore-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.environment == "production" ? 2 : 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = false
  }

  # Never run two versions of the worker at once. A job enqueued by one code
  # version and executed by another is the hardest class of bug to reproduce.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# Worker capacity follows queue depth, not CPU. A worker blocked on a long
# fit looks idle to a CPU based policy right when more capacity is needed.
resource "aws_appautoscaling_target" "worker" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.environment == "production" ? 2 : 1
  max_capacity       = var.environment == "production" ? 20 : 3
}

# ---------------------------------------------------------------------------
# Service discovery
# ---------------------------------------------------------------------------

resource "aws_service_discovery_private_dns_namespace" "main" {
  name = "${local.name}.local"
  vpc  = aws_vpc.main.id
}

resource "aws_service_discovery_service" "api" {
  for_each = local.api_services

  name = each.key

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

output "load_balancer_dns" {
  value = aws_lb.main.dns_name
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}
