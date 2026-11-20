from typing import Dict, Optional, List
import logging
import os
from dotenv import load_dotenv
from blocks_genesis._core.blocks_secret import BlocksSecret
from blocks_genesis._core.onprem_vault import OnPremVault

logger = logging.getLogger(__name__)

# Module-level private variable to hold the immutable singleton secret
_loaded_secret: Optional[BlocksSecret] = None

_KEY_VAULT_URL_NAME = "keyvault__keyvaulturl"
_VAULT_TYPES = {"azure": "azure", "2": "azure", "onprem": "onprem", "1": "onprem"}


def resolve_vault_type() -> str:
    """
    Same rule as the .NET ApplicationConfigurations.ResolveVaultType (I02-WP1):
    a valid BLOCKS_VAULT_TYPE ("Azure" or "OnPrem", any case) wins. Otherwise the
    vault is Azure only when KeyVault__KeyVaultUrl is set to a non-blank value, and
    on-premises (environment variables) when it is not.
    """
    load_dotenv()
    configured = (os.environ.get("BLOCKS_VAULT_TYPE") or "").strip().lower()
    if configured in _VAULT_TYPES:
        return _VAULT_TYPES[configured]
    for name, value in os.environ.items():
        if name.lower() == _KEY_VAULT_URL_NAME and value.strip():
            return "azure"
    return "onprem"


def _create_vault():
    if resolve_vault_type() == "azure":
        # Imported here so the Azure packages are needed only when this vault is chosen.
        from blocks_genesis._core.azure_key_vault import AzureKeyVault
        return AzureKeyVault()
    return OnPremVault()


class SecretLoader:
    def __init__(self, service_name: str = "blocks_service"):
        self.vault = _create_vault()
        self.service_name = service_name

    async def load_secrets(self, fields: Optional[List[str]] = None) -> None:
        global _loaded_secret
        if _loaded_secret is not None:
            logger.debug("Secrets already loaded, skipping reload.")
            return

        fields = fields or list(BlocksSecret.model_fields.keys())
        try:
            logger.info("Loading secrets from %s...", type(self.vault).__name__)
            raw_secrets: Dict[str, str] = await self.vault.get_secrets(fields)

            processed_secrets: Dict[str, object] = {
                key: (
                    value.lower() == "true"
                    if isinstance(value, str) and value.lower() in ["true", "false"]
                    else value
                )
                for key, value in raw_secrets.items()
            }

            secret = BlocksSecret(**processed_secrets)
            secret.ServiceName = self.service_name

            _loaded_secret = secret
            logger.info("Secrets loaded successfully")
        except Exception:
            logger.exception("Failed to load secrets")
            raise

    async def close(self) -> None:
        if hasattr(self.vault, "close") and callable(self.vault.close):
            await self.vault.close()

def get_blocks_secret() -> BlocksSecret:
    if _loaded_secret is None:
        raise RuntimeError("Secrets not loaded")
    return _loaded_secret
