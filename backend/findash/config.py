"""Configuração: caminhos do projeto, fuso horário e credenciais da Pluggy."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, SecretStr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE_NAME = ".env"
CREDENTIAL_VARS = ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET")
ITEM_VARS = ("PLUGGY_ITEM_IDS", "PLUGGY_ITEM_ID")  # o segundo é aceito para quem tem um item só

# O Brasil não tem horário de verão desde 2019. Um offset fixo evita depender do pacote
# tzdata, que o Python no Windows não traz.
LOCAL_TZ = timezone(timedelta(hours=-3), "BRT")


class ConfigError(Exception):
    """Configuração ausente ou inválida."""


@dataclass(frozen=True)
class Paths:
    """Caminhos de dados locais. Tudo em data/ fica fora do Git."""

    root: Path
    config_root: Path = PROJECT_ROOT  # config/ é versionado: vem do projeto mesmo com dados em outra pasta

    @classmethod
    def default(cls) -> Paths:
        return cls(PROJECT_ROOT)

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "findash.db"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def config_dir(self) -> Path:
        """Regras e mapas versionados (genéricos, sem dados pessoais)."""
        return self.config_root / "config"

    @property
    def personal_rules_path(self) -> Path:
        """Regras pessoais (nomes de pessoas, lugares): ficam em data/, fora do Git."""
        return self.data_dir / "regras_pessoais.yaml"

    @property
    def asset_classes_path(self) -> Path:
        """Correção manual de classe por ticker (a composição da carteira é dado pessoal)."""
        return self.data_dir / "classes_ativos.yaml"

    def ensure(self) -> None:
        for directory in (self.data_dir, self.backups_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ItemConfig:
    """Um item da Pluggy (uma conexão com um banco) e o perfil de instituição usado para ele."""

    id: str
    institution: str = "generic"


class PluggySettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_id: str
    client_secret: SecretStr  # repr/str mostram '**********'
    items: tuple[ItemConfig, ...]


def parse_items(text: str) -> tuple[ItemConfig, ...]:
    """'id1:nubank, id2' -> itens; sem ':perfil', vale o perfil genérico."""
    from findash.institutions import PROFILES  # import local: institutions importa os modelos do banco

    items = []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        item_id, _, institution = part.partition(":")
        institution = institution.strip().lower() or "generic"
        if institution not in PROFILES:
            raise ConfigError(f"Perfil de instituição desconhecido: '{institution}' (opções: {', '.join(PROFILES)})")
        items.append(ItemConfig(item_id.strip(), institution))
    if len({item.id for item in items}) != len(items):
        raise ConfigError("PLUGGY_ITEM_IDS tem um item repetido")
    return tuple(items)


def load_settings(root: Path = PROJECT_ROOT) -> PluggySettings:
    """Lê as credenciais do arquivo de ambiente da raiz; variáveis do sistema têm precedência."""
    values = {key: value for key, value in dotenv_values(root / ENV_FILE_NAME).items() if value}
    for name in CREDENTIAL_VARS + ITEM_VARS:
        if os.environ.get(name):
            values[name] = os.environ[name]
    missing = [name for name in CREDENTIAL_VARS if not values.get(name)]
    item_text = values.get("PLUGGY_ITEM_IDS") or values.get("PLUGGY_ITEM_ID")
    if not item_text:
        missing.append("PLUGGY_ITEM_IDS")
    if missing:
        raise ConfigError(f"Variáveis ausentes no arquivo de ambiente: {', '.join(missing)}")
    items = parse_items(item_text)
    if not items:
        raise ConfigError("PLUGGY_ITEM_IDS está vazio")
    return PluggySettings(
        client_id=values["PLUGGY_CLIENT_ID"],
        client_secret=SecretStr(values["PLUGGY_CLIENT_SECRET"]),
        items=items,
    )


def utcnow() -> datetime:
    """Agora em UTC, sem tzinfo: é a convenção de todos os DateTime do banco."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def local_date(value: datetime) -> date:
    """Data no horário de Brasília. Datas sem fuso são tratadas como UTC (padrão da Pluggy)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(LOCAL_TZ).date()
