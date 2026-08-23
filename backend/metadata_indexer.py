from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from google.cloud import bigquery
from llama_index.core import SQLDatabase, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.objects import ObjectIndex, SQLTableNodeMapping, SQLTableSchema
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from config import Settings, build_bigquery_client, get_settings

logger = logging.getLogger(__name__)

_PERSIST_DIR = Path(__file__).parent / ".index_store"


@dataclass(slots=True)
class ColumnMetadata:
    name: str
    field_path: str
    data_type: str | None = None


@dataclass(slots=True)
class TableMetadata:
    table_name: str
    fully_qualified_name: str
    columns: list[ColumnMetadata] = field(default_factory=list)
    table_description: str | None = None

    def to_context_str(self) -> str:
        column_lines = "\n".join(
            f"  - {c.name} ({c.data_type or 'UNKNOWN'})" for c in self.columns
        )
        description = self.table_description or "No table-level description available."
        return (
            f"Table `{self.fully_qualified_name}`: {description}\n"
            f"IMPORTANT: always reference this table in SQL using its full name exactly as shown above, "
            f"e.g. FROM `{self.fully_qualified_name}` — never the bare table name on its own.\n"
            f"Columns:\n{column_lines}"
        )


class SchemaExtractor:
    """Introspects BigQuery INFORMATION_SCHEMA to build table/column metadata without a manual glossary."""

    def __init__(self, client: bigquery.Client | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or build_bigquery_client(self._settings)

    def extract(self) -> list[TableMetadata]:
        field_paths_query = f"""
            SELECT table_name, field_path, data_type
            FROM `{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS`
            ORDER BY table_name, field_path
        """
        table_options_query = f"""
            SELECT table_name, option_name, option_value
            FROM `{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.INFORMATION_SCHEMA.TABLE_OPTIONS`
            WHERE option_name = 'description'
        """

        tables: dict[str, TableMetadata] = {}

        for row in self._client.query(field_paths_query).result():
            fully_qualified_name = (
                f"{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.{row.table_name}"
            )
            table = tables.setdefault(
                row.table_name,
                TableMetadata(table_name=row.table_name, fully_qualified_name=fully_qualified_name),
            )
            table.columns.append(
                ColumnMetadata(name=row.field_path, field_path=row.field_path, data_type=row.data_type)
            )

        try:
            for row in self._client.query(table_options_query).result():
                if row.table_name in tables:
                    tables[row.table_name].table_description = str(row.option_value).strip("'\" ")
        except Exception:
            logger.warning("TABLE_OPTIONS introspection failed; continuing without table descriptions.", exc_info=True)

        logger.info("Extracted metadata for %d tables from %s.", len(tables), self._settings.bigquery_dataset)
        return list(tables.values())


def build_sql_database(settings: Settings | None = None, engine: Engine | None = None) -> SQLDatabase:
    settings = settings or get_settings()
    engine = engine or create_engine(settings.bigquery_connection_string)
    return SQLDatabase(engine, schema=settings.bigquery_dataset)


class MetadataIndexBuilder:
    """Builds (or loads a persisted) LlamaIndex ObjectIndex over BigQuery table schemas for retrieval-augmented NL2SQL."""

    def __init__(
        self,
        sql_database: SQLDatabase,
        schema_extractor: SchemaExtractor | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._sql_database = sql_database
        self._schema_extractor = schema_extractor or SchemaExtractor(settings=settings)
        self._settings = settings or get_settings()

    def build(self, force_refresh: bool = False) -> ObjectIndex:
        table_node_mapping = SQLTableNodeMapping(self._sql_database)

        if not force_refresh and _PERSIST_DIR.exists():
            try:
                return self._load_persisted(table_node_mapping)
            except Exception:
                logger.warning("Failed to load persisted metadata index; rebuilding from scratch.", exc_info=True)

        tables = self._schema_extractor.extract()
        table_schema_objs = [
            SQLTableSchema(table_name=t.table_name, context_str=t.to_context_str()) for t in tables
        ]

        object_index = ObjectIndex.from_objects(
            table_schema_objs,
            table_node_mapping,
            index_cls=VectorStoreIndex,
        )
        self._persist(object_index)
        return object_index

    def _persist(self, object_index: ObjectIndex) -> None:
        _PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        object_index.index.storage_context.persist(persist_dir=str(_PERSIST_DIR))

    def _load_persisted(self, table_node_mapping: SQLTableNodeMapping) -> ObjectIndex:
        storage_context = StorageContext.from_defaults(persist_dir=str(_PERSIST_DIR))
        vector_index = load_index_from_storage(storage_context)
        return ObjectIndex(index=vector_index, object_node_mapping=table_node_mapping)
