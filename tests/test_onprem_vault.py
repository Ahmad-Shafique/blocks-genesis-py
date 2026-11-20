import os
import subprocess
import sys
import textwrap

import pytest

from blocks_genesis._core import secret_loader
from blocks_genesis._core.onprem_vault import OnPremVault
from blocks_genesis._core.secret_loader import SecretLoader, resolve_vault_type

# Fake values only.
FAKE_CACHE = "redis://cache.invalid:6379"
FAKE_DB = "mongodb://db.invalid:27017"


@pytest.fixture(autouse=True)
def clean_vault_environment(monkeypatch, tmp_path):
    """No inherited vault settings, and no .env file picked up from the working directory."""
    for name in list(os.environ):
        if name.lower().startswith("blockssecret__") or name.lower() in ("blocks_vault_type", "keyvault__keyvaulturl"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(secret_loader, "_loaded_secret", None)


@pytest.mark.asyncio
async def test_reads_requested_fields_from_environment(monkeypatch):
    monkeypatch.setenv("BlocksSecret__CacheConnectionString", FAKE_CACHE)
    monkeypatch.setenv("BlocksSecret__DatabaseConnectionString", FAKE_DB)
    monkeypatch.setenv("BlocksSecret__ServiceName", "not-requested")

    result = await OnPremVault().get_secrets(["CacheConnectionString", "DatabaseConnectionString", "LogDatabaseName"])

    assert result == {"CacheConnectionString": FAKE_CACHE, "DatabaseConnectionString": FAKE_DB}


@pytest.mark.asyncio
async def test_section_and_field_names_ignore_case(monkeypatch):
    # The .NET configuration binder matches the section and the keys without regard to case.
    monkeypatch.setenv("BLOCKSSECRET__CACHECONNECTIONSTRING", FAKE_CACHE)
    monkeypatch.setenv("blockssecret__databaseconnectionstring", FAKE_DB)

    result = await OnPremVault().get_secrets(["CacheConnectionString", "DatabaseConnectionString"])

    assert result == {"CacheConnectionString": FAKE_CACHE, "DatabaseConnectionString": FAKE_DB}


@pytest.mark.asyncio
async def test_empty_value_counts_as_not_set(monkeypatch):
    monkeypatch.setenv("BlocksSecret__CacheConnectionString", "")

    assert await OnPremVault().get_secrets(["CacheConnectionString"]) == {}


@pytest.mark.asyncio
async def test_other_variables_are_not_secrets(monkeypatch):
    monkeypatch.setenv("CacheConnectionString", "plain-name-is-not-in-the-section")
    monkeypatch.setenv("BlocksSecretCacheConnectionString", "no-separator")

    assert await OnPremVault().get_secrets(["CacheConnectionString"]) == {}


@pytest.mark.asyncio
async def test_without_field_list_returns_the_whole_section(monkeypatch):
    monkeypatch.setenv("BlocksSecret__CacheConnectionString", FAKE_CACHE)

    result = await OnPremVault().get_secrets()

    assert result == {"cacheconnectionstring": FAKE_CACHE}


@pytest.mark.asyncio
async def test_close_is_a_no_op():
    await OnPremVault().close()


@pytest.mark.parametrize(
    "vault_type, url, expected",
    [
        (None, None, "onprem"),
        (None, "", "onprem"),
        (None, "   ", "onprem"),
        (None, "https://vault.invalid/", "azure"),
        ("Azure", None, "azure"),
        ("azure", "", "azure"),
        ("OnPrem", "https://vault.invalid/", "onprem"),
        ("ONPREM", None, "onprem"),
        ("garbage", None, "onprem"),
        ("garbage", "https://vault.invalid/", "azure"),
        ("", "https://vault.invalid/", "azure"),
    ],
)
def test_vault_choice_follows_the_net_rule(monkeypatch, vault_type, url, expected):
    if vault_type is not None:
        monkeypatch.setenv("BLOCKS_VAULT_TYPE", vault_type)
    if url is not None:
        monkeypatch.setenv("KeyVault__KeyVaultUrl", url)

    assert resolve_vault_type() == expected


def test_vault_url_is_found_in_the_upper_case_form_too(monkeypatch):
    monkeypatch.setenv("KEYVAULT__KEYVAULTURL", "https://vault.invalid/")

    assert resolve_vault_type() == "azure"


def test_secret_loader_uses_the_environment_vault_by_default():
    assert isinstance(SecretLoader("svc").vault, OnPremVault)


def test_secret_loader_uses_azure_when_a_vault_url_is_set(monkeypatch):
    from blocks_genesis._core.azure_key_vault import AzureKeyVault

    monkeypatch.setenv("KeyVault__KeyVaultUrl", "https://vault.invalid/")

    assert isinstance(SecretLoader("svc").vault, AzureKeyVault)


@pytest.mark.asyncio
async def test_secret_loader_loads_the_secret_from_the_environment(monkeypatch):
    monkeypatch.setenv("BlocksSecret__CacheConnectionString", FAKE_CACHE)
    monkeypatch.setenv("BlocksSecret__DatabaseConnectionString", FAKE_DB)

    await SecretLoader("svc").load_secrets()

    loaded = secret_loader.get_blocks_secret()
    assert loaded.CacheConnectionString == FAKE_CACHE
    assert loaded.DatabaseConnectionString == FAKE_DB
    assert loaded.ServiceName == "svc"


NO_AZURE_SCRIPT = textwrap.dedent(
    """
    import asyncio
    import sys

    class BlockAzure:
        # Makes every azure package unimportable, as in an install without the "azure" extra.
        def find_spec(self, name, path=None, target=None):
            if name == "azure" or name.startswith("azure."):
                raise ModuleNotFoundError("No module named " + repr(name))

    sys.meta_path.insert(0, BlockAzure())

    import blocks_genesis
    import blocks_genesis._core.api
    import blocks_genesis._core.worker
    from blocks_genesis._core.secret_loader import SecretLoader, get_blocks_secret

    asyncio.run(SecretLoader("svc").load_secrets())
    secret = get_blocks_secret()
    assert secret.CacheConnectionString == "redis://cache.invalid:6379", secret.CacheConnectionString
    assert secret.ServiceName == "svc"

    for name in ("AzureKeyVault", "AzureMessageClient"):
        try:
            getattr(blocks_genesis, name)
        except ImportError:
            pass
        else:
            raise AssertionError(name + " imported without the azure package")

    assert not [m for m in sys.modules if m == "azure" or m.startswith("azure.")]
    print("ok")
    """
)


def test_loads_from_environment_with_no_azure_package_importable(tmp_path):
    env = {k: v for k, v in os.environ.items() if k.lower() not in ("blocks_vault_type", "keyvault__keyvaulturl")}
    env["BlocksSecret__CacheConnectionString"] = FAKE_CACHE

    done = subprocess.run(
        [sys.executable, "-c", NO_AZURE_SCRIPT],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip() == "ok"
