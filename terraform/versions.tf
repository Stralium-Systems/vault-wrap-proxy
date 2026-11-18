terraform {
  required_version = ">= 1.17.2, < 2.0.0"

  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "~> 5.13.0"
    }
  }
}
