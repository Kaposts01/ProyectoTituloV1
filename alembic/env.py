from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import settings
from app.db.session import Base
from app.models.auth import Permission, Role, User  # noqa: F401
from app.models.payku_channel import PaykuClient, PaykuPlan, PaykuSubscription, PaykuTransaction  # noqa: F401
from app.models.tch import (  # noqa: F401
    TchBanco,
    TchCentroCosto,
    TchCliente,
    TchOrigen,
    TchRecaudacionMensual,
    TchSuscripcion,
    TchTipoMandato,
    TchTransaccion,
)
from app.models.crm import (  # noqa: F401
    Charge,
    Client,
    Payment,
    PaymentMethod,
    Plan,
    Subscription,
)
from app.models.source_record import SourceRecord  # noqa: F401
from app.models.sync_run import SyncRun  # noqa: F401
from app.models.toku_channel import TokuCustomer, TokuInvoice, TokuPaymentMethod, TokuSubscription, TokuTransaction  # noqa: F401
from app.models.vp import VpCharge, VpClient, VpPayment, VpPlan, VpSubscription  # noqa: F401
from app.models.write_run import WriteRun  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
