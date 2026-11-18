# =============================================================================
# Vault Wrap Proxy - Configuration Terraform
# =============================================================================
#
# Ce fichier configure l'authentification et les policies pour le service
# vault-wrap-proxy qui expose les opérations wrap/unwrap à tous.
#
# Usage:
#   1. Adaptez les variables à votre environnement
#   2. Appliquez avec : terraform apply
#
# Prérequis:
#   - Provider Vault configuré
#   - Kubernetes Auth Method activé sur Vault
#   - Cluster Kubernetes avec accès au serveur Vault
# =============================================================================

# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------

variable "kubernetes_auth_backend" {
  description = "Nom du backend Kubernetes Auth dans Vault"
  type        = string
  default     = "kubernetes"
}

variable "service_account_name" {
  description = "Nom du ServiceAccount Kubernetes pour le proxy"
  type        = string
  default     = "vault-wrap-proxy"
}

variable "allowed_namespaces" {
  description = "Namespaces Kubernetes autorisés à utiliser ce rôle"
  type        = list(string)
  default     = ["vault-wrap-proxy"]
}

variable "token_ttl" {
  description = "TTL du token Vault (secondes)"
  type        = number
  default     = 3600 # 1 heure
}

variable "token_max_ttl" {
  description = "TTL maximum du token Vault (secondes)"
  type        = number
  default     = 86400 # 24 heures
}

# -----------------------------------------------------------------------------
# Policy pour le vault-wrap-proxy
# -----------------------------------------------------------------------------
#
# Cette policy donne uniquement accès aux opérations de wrapping.
# AUCUN accès aux secrets stockés dans Vault (secret/*, kv/*, etc.)

resource "vault_policy" "vault_wrap_proxy" {
  name = "vault-wrap-proxy"

  policy = <<-EOT
    # Permet de wrapper des données arbitraires
    # Les données sont chiffrées par Vault et stockées dans un cubbyhole
    path "sys/wrapping/wrap" {
      capabilities = ["update"]
    }

    # Permet de unwrapper des tokens
    # Consomme le token (usage unique)
    path "sys/wrapping/unwrap" {
      capabilities = ["update"]
    }

    # Permet d'inspecter un wrapped token sans le consommer
    # Retourne le TTL restant et la date de création
    path "sys/wrapping/lookup" {
      capabilities = ["update"]
    }

  EOT
}

# -----------------------------------------------------------------------------
# Rôle Kubernetes Auth pour vault-wrap-proxy
# -----------------------------------------------------------------------------
#
# Le proxy s'authentifie via son ServiceAccount Kubernetes :
# 1. Le JWT du ServiceAccount est envoyé à Vault
# 2. Vault vérifie le JWT auprès de l'API Kubernetes
# 3. Vault retourne un token avec les permissions de la policy

resource "vault_kubernetes_auth_backend_role" "vault_wrap_proxy" {
  backend                          = var.kubernetes_auth_backend
  role_name                        = "vault-wrap-proxy"
  bound_service_account_names      = [var.service_account_name]
  bound_service_account_namespaces = var.allowed_namespaces
  token_ttl                        = var.token_ttl
  token_max_ttl                    = var.token_max_ttl
  token_policies                   = ["default", vault_policy.vault_wrap_proxy.name]
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "policy_name" {
  description = "Nom de la policy Vault créée"
  value       = vault_policy.vault_wrap_proxy.name
}

output "role_name" {
  description = "Nom du rôle Kubernetes Auth créé"
  value       = vault_kubernetes_auth_backend_role.vault_wrap_proxy.role_name
}

output "usage_instructions" {
  description = "Instructions pour utiliser cette configuration"
  value       = <<-EOT
    Configuration appliquée. Pour utiliser le proxy :
    
    1. Déployez le chart Helm avec :
       helm upgrade --install vault-wrap-proxy ./helm/vault-wrap-proxy \
         --namespace ${var.allowed_namespaces[0]} \
         --create-namespace \
         --set serviceAccount.name=${var.service_account_name} \
         --set vault.authMount=${var.kubernetes_auth_backend} \
         --set vault.role=${vault_kubernetes_auth_backend_role.vault_wrap_proxy.role_name}
    
    2. Le ServiceAccount '${var.service_account_name}' dans le namespace 
       '${var.allowed_namespaces[0]}' pourra s'authentifier à Vault.
  EOT
}
