from blocks_genesis._auth.blocks_context import BlocksContext, BlocksContextManager
from blocks_genesis._auth.jwt_signing_algorithm import JwtSigningAlgorithm
from blocks_genesis._auth.third_party_provider import (
    ThirdPartyClaimsMapping,
    ThirdPartyJwtProvider,
)
from blocks_genesis._auth.third_party_provider_store import (
    ThirdPartyJwtProviderStore,
    get_third_party_provider_store,
    initialize_third_party_provider_store,
)
from blocks_genesis._cache import CacheClient
from blocks_genesis._cache.cache_provider import CacheProvider
from blocks_genesis._database.db_context import DbContext
from blocks_genesis._tenant.tenant import Tenant
from blocks_genesis._tenant.tenant_service import TenantService, get_tenant_service
from blocks_genesis._message.rabbit_mq.rabbit_message_client import RabbitMessageClient
from blocks_genesis._core.api import close_lifespan, configure_lifespan, configure_genesis, fast_api_app
from blocks_genesis._core.worker import WorkerConsoleApp
from blocks_genesis._core.configuration import get_configurations, load_configurations
from blocks_genesis._entities.base_entity import BaseEntity
from blocks_genesis._lmt.activity import Activity
from blocks_genesis._message.consumer_message import ConsumerMessage
from blocks_genesis._message.message_client import MessageClient
from blocks_genesis._utilities.crypto_service import CryptoService
from blocks_genesis._auth.auth import authorize, resolve_subscription_usage, subscription_usage_snapshot
from blocks_genesis._message.message_configuration import AzureServiceBusConfiguration, RabbitMqConfiguration, ConsumerSubscription, MessageConfiguration
from blocks_genesis._subscription.context import SubscriptionUsageContext
from blocks_genesis._subscription.usage_service import SubscriptionUsageService
from blocks_genesis._subscription.models import UsageResult
from blocks_genesis._subscription.enums import SubscriptionStatus
from blocks_genesis._delegation import (
    AuthClaimsContext,
    DelegatedTokenContext,
    DelegatedTokenProvider,
    DelegationGrantFactory,
    DelegationGrantRecord,
    DelegationGrantStore,
    DelegationTokenEndpointResolver,
    delegated_auth_headers,
    get_delegated_token_provider,
    get_delegation_grant_factory,
    get_delegation_grant_store,
    get_endpoint_resolver,
)

# The Azure classes need the optional "azure" extra, so they load on first use (PEP 562).
_AZURE_EXPORTS = {
    "AzureMessageClient": "blocks_genesis._message.azure.azure_message_client",
    "AzureKeyVault": "blocks_genesis._core.azure_key_vault",
}


def __getattr__(name):
    module_name = _AZURE_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_name), name)


__all__ = [
    "BlocksContext",
    "BlocksContextManager",
    "JwtSigningAlgorithm",
    "ThirdPartyClaimsMapping",
    "ThirdPartyJwtProvider",
    "ThirdPartyJwtProviderStore",
    "get_third_party_provider_store",
    "initialize_third_party_provider_store",
    "CacheClient",
    "CacheProvider",
    "DbContext",
    "Tenant",
    "TenantService",
    "get_tenant_service",
    "RabbitMessageClient",
    "RabbitMqConfiguration",
    "ConsumerSubscription",
    "MessageConfiguration",
    "close_lifespan",
    "configure_lifespan",
    "configure_genesis",
    "WorkerConsoleApp",
    "get_configurations",
    "load_configurations",
    "BaseEntity",
    "Activity",
    "ConsumerMessage",
    "MessageClient",
    "CryptoService",
    "AzureServiceBusConfiguration",
    "authorize",
    "subscription_usage_snapshot",
    "resolve_subscription_usage",
    "fast_api_app",
    "SubscriptionUsageContext",
    "SubscriptionUsageService",
    "UsageResult",
    "SubscriptionStatus",
    "AuthClaimsContext",
    "DelegatedTokenContext",
    "DelegatedTokenProvider",
    "DelegationGrantFactory",
    "DelegationGrantRecord",
    "DelegationGrantStore",
    "DelegationTokenEndpointResolver",
    "delegated_auth_headers",
    "get_delegated_token_provider",
    "get_delegation_grant_factory",
    "get_delegation_grant_store",
    "get_endpoint_resolver"
]
