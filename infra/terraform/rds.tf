# PostgreSQL: cohort job records, validation reports, and the audit log.
#
# Status: not applied to a live account. See the note at the top of main.tf.
#
# Redis carries job progress because it is fast and disposable. Postgres
# carries the record of what was generated, what it scored, and who exported
# it, because that record has to survive a cache eviction and has to be
# queryable a year later when someone asks how a cohort was produced.

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_security_group" "database" {
  name   = "${local.name}-database"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.service.id]
  }

  # No egress rule. The database has no reason to originate a connection.
  tags = { Name = "${local.name}-database" }
}

resource "random_password" "database" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "database" {
  name       = "${local.name}/database-url"
  kms_key_id = aws_kms_key.data.arn

  # Long enough to recover from an accidental destroy, short enough that a
  # rotated credential does not linger.
  recovery_window_in_days = 14
}

resource "aws_secretsmanager_secret_version" "database" {
  secret_id = aws_secretsmanager_secret.database.id
  secret_string = format(
    "postgresql+asyncpg://%s:%s@%s:5432/%s",
    aws_db_instance.main.username,
    random_password.database.result,
    aws_db_instance.main.address,
    aws_db_instance.main.db_name,
  )
}

resource "aws_db_parameter_group" "main" {
  name   = local.name
  family = "postgres16"

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  # Connections from ECS tasks must be encrypted. Without this a
  # misconfigured client silently falls back to plaintext inside the VPC.
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_instance" "main" {
  identifier = local.name

  engine         = "postgres"
  engine_version = "16.4"
  instance_class = var.environment == "production" ? "db.t4g.medium" : "db.t4g.micro"

  db_name  = "pretrial"
  username = "pretrial"
  password = random_password.database.result

  allocated_storage     = 50
  max_allocated_storage = var.environment == "production" ? 500 : 100
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.data.arn

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  parameter_group_name   = aws_db_parameter_group.main.name
  publicly_accessible    = false

  multi_az = var.environment == "production"

  # Thirty days of backups because the audit log lives here and a sponsor
  # asking how a cohort was produced may ask weeks after the fact.
  backup_retention_period = var.environment == "production" ? 30 : 7
  backup_window            = "02:00-03:00"
  maintenance_window       = "sun:03:30-sun:04:30"
  copy_tags_to_snapshot    = true
  delete_automated_backups = false

  performance_insights_enabled    = var.environment == "production"
  performance_insights_kms_key_id = var.environment == "production" ? aws_kms_key.data.arn : null
  enabled_cloudwatch_logs_exports = ["postgresql"]

  auto_minor_version_upgrade = true
  deletion_protection        = var.environment == "production"
  skip_final_snapshot        = var.environment != "production"
  final_snapshot_identifier  = var.environment == "production" ? "${local.name}-final" : null

  lifecycle {
    # Rotating the password through Terraform would recreate the secret
    # version on every apply and break running tasks mid rotation.
    ignore_changes = [password]
  }
}

resource "aws_cloudwatch_metric_alarm" "database_storage" {
  alarm_name          = "${local.name}-database-storage-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 10737418240 # 10 GB

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }
}

output "database_endpoint" {
  value     = aws_db_instance.main.address
  sensitive = true
}

output "database_secret_arn" {
  value = aws_secretsmanager_secret.database.arn
}
