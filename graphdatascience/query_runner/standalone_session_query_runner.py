from __future__ import annotations

from typing import Any, Optional

from pandas import DataFrame

from graphdatascience.query_runner.arrow_graph_constructor import ArrowGraphConstructor
from graphdatascience.query_runner.graph_constructor import GraphConstructor
from graphdatascience.query_runner.progress.query_progress_logger import QueryProgressLogger
from graphdatascience.server_version.server_version import ServerVersion

from ..call_parameters import CallParameters
from .gds_arrow_client import GdsArrowClient
from .query_runner import QueryRunner


class StandAloneSessionQueryRunner(QueryRunner):
    @staticmethod
    def create(
        gds_query_runner: QueryRunner,
        arrow_client: GdsArrowClient,
        show_progress: bool,
    ) -> StandAloneSessionQueryRunner:
        return StandAloneSessionQueryRunner(gds_query_runner, arrow_client, show_progress)

    def __init__(
        self,
        gds_query_runner: QueryRunner,
        arrow_client: GdsArrowClient,
        show_progress: bool,
    ):
        self._gds_query_runner = gds_query_runner
        self._gds_arrow_client = arrow_client
        self._show_progress = show_progress
        self._progress_logger = QueryProgressLogger(
            lambda query, database: self._gds_query_runner.run_cypher(query=query, database=database),
            self._gds_query_runner.server_version,
        )

    def run_cypher(
        self,
        query: str,
        params: Optional[dict[str, Any]] = None,
        database: Optional[str] = None,
        custom_error: bool = True,
    ) -> DataFrame:
        raise NotImplementedError("Cannot run Cypher against Sessions.")

    def call_function(self, endpoint: str, params: Optional[CallParameters] = None) -> Any:
        return self._gds_query_runner.call_function(endpoint, params)

    def call_procedure(
        self,
        endpoint: str,
        params: Optional[CallParameters] = None,
        yields: Optional[list[str]] = None,
        database: Optional[str] = None,
        logging: bool = False,
        custom_error: bool = True,
    ) -> DataFrame:
        return self._gds_query_runner.call_procedure(endpoint, params, yields, database, logging, custom_error)

    def server_version(self) -> ServerVersion:
        return self._gds_query_runner.server_version()

    def driver_config(self) -> dict[str, Any]:
        # TODO should return arrow config?
        return self._gds_query_runner.driver_config()

    def encrypted(self) -> bool:
        return self._gds_query_runner.encrypted()

    def set_database(self, database: str) -> None:
        raise NotImplementedError("Cannot set database as no db connection was specified.")

    def set_bookmarks(self, bookmarks: Optional[Any]) -> None:
        raise NotImplementedError("Cannot set database as no db connection was specified.")

    def bookmarks(self) -> Optional[Any]:
        return None

    def last_bookmarks(self) -> Optional[Any]:
        return None

    def database(self) -> Optional[str]:
        return None

    def create_graph_constructor(
        self, graph_name: str, concurrency: int, undirected_relationship_types: Optional[list[str]]
    ) -> GraphConstructor:
        return ArrowGraphConstructor(
            "",
            graph_name,
            self._gds_arrow_client,
            concurrency,
            undirected_relationship_types,
        )

    def set_show_progress(self, show_progress: bool) -> None:
        self._show_progress = show_progress
        self._gds_query_runner.set_show_progress(show_progress)

    def close(self) -> None:
        self._gds_arrow_client.close()
        self._gds_query_runner.close()
