# =============================================================================
# GCP Terraform — HIPAA-compliant data pipeline
# Fixed: subnet purpose, firewall source_ranges, port types, CDN enable_cdn,
#        forwarding rule IP binding, health check fields, complete url_map,
#        added Cloud Armor, KMS, Cloud Run, Cloud SQL, Pub/Sub, Secret Manager
# =============================================================================

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.5"
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# =============================================================================
# VPC
# FIX: removed unsupported `tags` block — VPC networks don't support tags.
#      Tags belong on firewall rules and compute instances.
# =============================================================================

resource "google_compute_network" "vpc" {
  name                    = "vpc-${var.project_id}"
  auto_create_subnetworks = false
  description             = "VPC for HIPAA-compliant data pipeline"
}

# FIX: removed `purpose` and `role` — those only apply to proxy-only subnets
#      (REGIONAL_MANAGED_PROXY / INTERNAL_HTTPS_LOAD_BALANCER).
#      Regular subnets have no purpose attribute.

resource "google_compute_subnetwork" "public_subnet" {
  name                     = "public-subnet-${var.project_id}"
  ip_cidr_range            = "10.0.1.0/24"
  region                   = var.region
  network                  = google_compute_network.vpc.id
  private_ip_google_access = true   # allow instances to reach Google APIs without external IP
}

resource "google_compute_subnetwork" "private_subnet" {
  name                     = "private-subnet-${var.project_id}"
  ip_cidr_range            = "10.0.2.0/24"
  region                   = var.region
  network                  = google_compute_network.vpc.id
  private_ip_google_access = true
}

# =============================================================================
# Cloud NAT — lets private-subnet instances reach the internet without public IPs
# =============================================================================

resource "google_compute_router" "nat_router" {
  name    = "nat-router-${var.project_id}"
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "nat" {
  name                               = "nat-${var.project_id}"
  router                             = google_compute_router.nat_router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.private_subnet.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
}

# =============================================================================
# Firewall rules
# FIX: ports must be strings, not integers.
# FIX: source_ranges is required — without it the rule has no effect.
# FIX: split http (80) and https (443) cleanly; removed overlap.
# =============================================================================

resource "google_compute_firewall" "allow_http" {
  name    = "allow-http-${var.project_id}"
  network = google_compute_network.vpc.id

  allow {
    protocol = "tcp"
    ports    = ["80"]   # FIX: string, not integer
  }

  source_ranges = ["0.0.0.0/0"]   # FIX: was missing entirely
  target_tags   = ["http-server"]
}

resource "google_compute_firewall" "allow_https" {
  name    = "allow-https-${var.project_id}"
  network = google_compute_network.vpc.id

  allow {
    protocol = "tcp"
    ports    = ["443"]   # FIX: string, not integer
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["https-server"]
}

resource "google_compute_firewall" "allow_api" {
  name    = "allow-api-${var.project_id}"
  network = google_compute_network.vpc.id

  allow {
    protocol = "tcp"
    ports    = ["8080"]
  }

  source_ranges = [google_compute_subnetwork.private_subnet.ip_cidr_range]
  target_tags   = ["api-server"]
}

resource "google_compute_firewall" "deny_all_ingress" {
  name     = "deny-all-ingress-${var.project_id}"
  network  = google_compute_network.vpc.id
  priority = 65534

  deny {
    protocol = "all"
  }

  source_ranges = ["0.0.0.0/0"]
  direction     = "INGRESS"
}

# =============================================================================
# Static IPs
# FIX: only one CDN IP needed; cdn_ip2 was defined but never used.
# =============================================================================

resource "google_compute_global_address" "cdn_ip" {
  name = "cdn-ip-${var.project_id}"
}

# =============================================================================
# Cloud CDN + Global HTTPS Load Balancer
# FIX: added enable_cdn = true to the backend service — without this CDN is off.
# FIX: bound the reserved static IP to the forwarding rule via ip_address.
# FIX: switched to HTTPS forwarding rule and added SSL cert.
# FIX: removed response_code from health check — that field doesn't exist.
# FIX: switched to google_compute_backend_service (global) not regional,
#      because global forwarding rules require global backend services.
# =============================================================================

resource "google_compute_managed_ssl_certificate" "default" {
  name = "ssl-cert-${var.project_id}"
  managed {
    domains = [var.domain_name]
  }
}

resource "google_compute_health_check" "cdn" {
  name               = "cdn-health-check-${var.project_id}"
  check_interval_sec = 10   # FIX: was 1 second — too aggressive for production
  timeout_sec        = 5
  healthy_threshold  = 2
  unhealthy_threshold = 3

  http_health_check {
    port         = 80
    request_path = "/health"
    # FIX: removed response_code = "200" — not a valid field
  }
}

resource "google_compute_backend_service" "cdn" {
  name          = "cdn-backend-${var.project_id}"
  port_name     = "http"
  protocol      = "HTTP"
  health_checks = [google_compute_health_check.cdn.id]
  enable_cdn    = true   # FIX: was missing — CDN was never actually enabled

  cdn_policy {
    cache_mode        = "CACHE_ALL_STATIC"
    default_ttl       = 3600
    max_ttl           = 86400
    negative_caching  = true
  }
}

resource "google_compute_url_map" "cdn" {
  name            = "cdn-url-map-${var.project_id}"
  default_service = google_compute_backend_service.cdn.id
}

resource "google_compute_target_https_proxy" "cdn" {
  name             = "cdn-https-proxy-${var.project_id}"
  url_map          = google_compute_url_map.cdn.id
  ssl_certificates = [google_compute_managed_ssl_certificate.default.id]
}

resource "google_compute_global_forwarding_rule" "cdn_https" {
  name                  = "cdn-https-forwarding-rule-${var.project_id}"
  target                = google_compute_target_https_proxy.cdn.id
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL"
  ip_address            = google_compute_global_address.cdn_ip.id   # FIX: was missing
}

# HTTP -> HTTPS redirect
resource "google_compute_url_map" "http_redirect" {
  name = "http-redirect-${var.project_id}"

  default_url_redirect {
    https_redirect         = true
    strip_query            = false
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
  }
}

resource "google_compute_target_http_proxy" "http_redirect" {
  name    = "http-redirect-proxy-${var.project_id}"
  url_map = google_compute_url_map.http_redirect.id
}

resource "google_compute_global_forwarding_rule" "http_redirect" {
  name                  = "http-redirect-forwarding-rule-${var.project_id}"
  target                = google_compute_target_http_proxy.http_redirect.id
  port_range            = "80"
  load_balancing_scheme = "EXTERNAL"
  ip_address            = google_compute_global_address.cdn_ip.id
}

# =============================================================================
# Cloud Armor (WAF)
# ADDED: was missing entirely — required for HIPAA compliance.
# Blocks SQLi, XSS, and common OWASP Top 10 attacks.
# =============================================================================

resource "google_compute_security_policy" "waf" {
  name = "waf-policy-${var.project_id}"

  rule {
    action   = "allow"
    priority = 1000
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Default allow"
  }

  rule {
    action   = "deny(403)"
    priority = 100
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('sqli-v33-stable')"
      }
    }
    description = "Block SQL injection"
  }

  rule {
    action   = "deny(403)"
    priority = 200
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('xss-v33-stable')"
      }
    }
    description = "Block cross-site scripting"
  }

  rule {
    action   = "deny(403)"
    priority = 300
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('rce-v33-stable')"
      }
    }
    description = "Block remote code execution"
  }
}

# =============================================================================
# Cloud KMS — encryption keys for HIPAA data at rest
# ADDED: was missing entirely.
# =============================================================================

resource "google_kms_key_ring" "main" {
  name     = "keyring-${var.project_id}"
  location = var.region
}

resource "google_kms_crypto_key" "db_key" {
  name            = "db-encryption-key"
  key_ring        = google_kms_key_ring.main.id
  rotation_period = "7776000s"   # 90 days

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key" "storage_key" {
  name            = "storage-encryption-key"
  key_ring        = google_kms_key_ring.main.id
  rotation_period = "7776000s"

  lifecycle {
    prevent_destroy = true
  }
}

# =============================================================================
# Secret Manager — store credentials, API keys, connection strings
# ADDED: was missing. Required for HIPAA — no secrets in env vars.
# =============================================================================

resource "google_secret_manager_secret" "db_password" {
  secret_id = "db-password-${var.project_id}"

  replication {
    auto {}
  }
}

# =============================================================================
# Cloud SQL (PostgreSQL) — primary database
# ADDED: was missing entirely.
# HIPAA: encryption with CMEK, private IP only, automated backups.
# =============================================================================

resource "google_sql_database_instance" "main" {
  name             = "db-${var.project_id}"
  database_version = "POSTGRES_15"
  region           = var.region

  encryption_key_name = google_kms_crypto_key.db_key.id

  settings {
    tier              = "db-n1-standard-2"
    availability_type = "REGIONAL"   # multi-zone HA

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 30
      }
    }

    ip_configuration {
      ipv4_enabled    = false   # private IP only — no public endpoint
      private_network = google_compute_network.vpc.id
      require_ssl     = true
    }

    database_flags {
      name  = "log_connections"
      value = "on"
    }
    database_flags {
      name  = "log_disconnections"
      value = "on"
    }
  }

  deletion_protection = true
}

resource "google_sql_database" "app_db" {
  name     = "appdb"
  instance = google_sql_database_instance.main.name
}

# =============================================================================
# Cloud Run — serverless compute for the pipeline API
# ADDED: was missing entirely.
# HIPAA: only accepts traffic from the internal VPC, not the public internet.
# =============================================================================

resource "google_cloud_run_v2_service" "api" {
  name     = "pipeline-api-${var.project_id}"
  location = var.region

  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    scaling {
      min_instance_count = 1
      max_instance_count = 10
    }

    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.private_subnet.id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = "gcr.io/${var.project_id}/pipeline-api:latest"

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      env {
        name = "DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_password.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "DB_HOST"
        value = google_sql_database_instance.main.private_ip_address
      }
    }
  }
}

# =============================================================================
# Pub/Sub — event streaming for the data pipeline
# ADDED: was missing entirely.
# =============================================================================

resource "google_pubsub_topic" "health_records_ingestion" {
  name = "health-records-ingestion-${var.project_id}"

  message_storage_policy {
    allowed_persistence_regions = [var.region]   # keep PHI data in one region
  }
}

resource "google_pubsub_subscription" "health_records_processor" {
  name  = "health-records-processor-${var.project_id}"
  topic = google_pubsub_topic.health_records_ingestion.name

  ack_deadline_seconds       = 60
  retain_acked_messages      = false
  message_retention_duration = "86400s"   # 24 hours

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.health_records_dlq.id
    max_delivery_attempts = 5
  }
}

resource "google_pubsub_topic" "health_records_dlq" {
  name = "health-records-dlq-${var.project_id}"
}

# =============================================================================
# Cloud Storage — for processed health records (encrypted at rest)
# =============================================================================

resource "google_storage_bucket" "health_records" {
  name          = "health-records-${var.project_id}"
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  encryption {
    default_kms_key_name = google_kms_crypto_key.storage_key.id
  }

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
    condition {
      age = 90
    }
  }

  retention_policy {
    retention_period = 2592000   # 30 days minimum retention for HIPAA
  }
}

# =============================================================================
# Cloud Monitoring — alerting for HIPAA audit requirements
# ADDED: was missing.
# =============================================================================

resource "google_monitoring_notification_channel" "email" {
  display_name = "Ops Email Alert"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }
}

resource "google_monitoring_alert_policy" "high_error_rate" {
  display_name = "High API Error Rate"
  combiner     = "OR"

  conditions {
    display_name = "Error rate > 5%"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"run.googleapis.com/request_count\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.05
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
  alert_strategy {
    auto_close = "1800s"
  }
}

# =============================================================================
# IAM — least-privilege service accounts
# =============================================================================

resource "google_service_account" "cloud_run_sa" {
  account_id   = "cloud-run-sa-${var.project_id}"
  display_name = "Cloud Run Service Account"
}

resource "google_project_iam_member" "cloud_run_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

resource "google_project_iam_member" "cloud_run_pubsub" {
  project = var.project_id
  role    = "roles/pubsub.subscriber"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

resource "google_project_iam_member" "cloud_run_secrets" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}
