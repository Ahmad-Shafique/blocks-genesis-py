import os
from typing import Dict, List, Optional

from dotenv import load_dotenv

# Same names as the .NET OnPremVault: the section "BlocksSecret" of the environment,
# where a variable BlocksSecret__<FieldName> is the secret <FieldName>.
ENV_PREFIX = "BlocksSecret__"


class OnPremVault:
    """
    Secret source for deployments without Azure Key Vault. It reads the
    ``BlocksSecret__<FieldName>`` environment variables and needs no Azure package.

    Case rules follow the .NET OnPremVault (Microsoft.Extensions.Configuration): the
    section name ``BlocksSecret`` and the field names are matched without regard to
    case, so ``BLOCKSSECRET__CACHECONNECTIONSTRING`` supplies ``CacheConnectionString``.
    Values are returned under the field name that was asked for. Unlike the .NET
    class, which returns every variable of the section, only the requested fields
    are returned, as ``AzureKeyVault.get_secrets`` does; an empty value counts as
    not set.
    """

    @staticmethod
    def _read_environment() -> Dict[str, str]:
        load_dotenv()
        prefix = ENV_PREFIX.lower()
        found: Dict[str, str] = {}
        for name, value in os.environ.items():
            if name.lower().startswith(prefix) and value:
                found[name[len(prefix):].lower()] = value
        return found

    async def get_secrets(self, fields: Optional[List[str]] = None) -> Dict[str, str]:
        available = self._read_environment()
        if not fields:
            return available
        return {field: available[field.lower()] for field in fields if field.lower() in available}

    async def close(self) -> None:
        return None
