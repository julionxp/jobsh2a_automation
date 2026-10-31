from core.database import DBBaseModel, engine


async def create_tables() -> None:
    # Importar os modelos registra suas tabelas no metadata.
    import models.__all_models  # noqa: F401

    print("Criando as tabelas no banco de dados...")
    async with engine.begin() as connection:
        # create_all cria apenas tabelas ausentes; não apaga dados existentes.
        await connection.run_sync(DBBaseModel.metadata.create_all)
    print("Tabelas verificadas/criadas com sucesso.")
    await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(create_tables())
