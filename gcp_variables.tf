variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "us-central1"
}

variable "domain_name" {
  description = "Domain name for the managed SSL certificate (e.g. api.example.com)"
  type        = string
}

variable "alert_email" {
  description = "Email address for Cloud Monitoring alerts"
  type        = string
}
