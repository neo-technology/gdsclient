from __future__ import annotations

import time
from typing import Any, Optional
from uuid import uuid4

from pandas import DataFrame

from graphdatascience.query_runner.graph_constructor import GraphConstructor
from graphdatascience.query_runner.progress.query_progress_logger import QueryProgressLogger
from graphdatascience.query_runner.termination_flag import TerminationFlag
from graphdatascience.server_version.server_version import ServerVersion

from ..call_parameters import CallParameters
from ..session.dbms.protocol_resolver import ProtocolVersionResolver
from .gds_arrow_client import GdsArrowClient
from .protocol.project_protocols import ProjectProtocol
from .protocol.write_protocols import WriteProtocol
from .query_runner import QueryRunner


class SessionQueryRunner(QueryRunner):
    GDS_REMOTE_PROJECTION_PROC_NAME = "gds.arrow.project"

    @staticmethod
    def create(
        gds_query_runner: QueryRunner, db_query_runner: QueryRunner, arrow_client: GdsArrowClient, show_progress: bool
    ) -> SessionQueryRunner:
        return SessionQueryRunner(gds_query_runner, db_query_runner, arrow_client, show_progress)

    def __init__(
        self,
        gds_query_runner: QueryRunner,
        db_query_runner: QueryRunner,
        arrow_client: GdsArrowClient,
        show_progress: bool,
    ):
        self._gds_query_runner = gds_query_runner
        self._db_query_runner = db_query_runner
        self._gds_arrow_client = arrow_client
        self._resolved_protocol_version = ProtocolVersionResolver(db_query_runner).resolve()
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
        return self._db_query_runner.run_cypher(query, params, database, custom_error)

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
        if params is None:
            params = CallParameters()

        if SessionQueryRunner.GDS_REMOTE_PROJECTION_PROC_NAME in endpoint:
            terminationFlag = TerminationFlag.create()
            return self._remote_projection(endpoint, params, terminationFlag, yields, database, logging)

        elif ".write" in endpoint and self.is_remote_projected_graph(params["graph_name"]):
            terminationFlag = TerminationFlag.create()
            return self._remote_write_back(endpoint, params, terminationFlag, yields, database, logging, custom_error)

        return self._gds_query_runner.call_procedure(endpoint, params, yields, database, logging, custom_error)

    def is_remote_projected_graph(self, graph_name: str) -> bool:
        database_location: str = self._gds_query_runner.call_procedure(
            endpoint="gds.graph.list",
            yields=["databaseLocation"],
            params=CallParameters(graph_name=graph_name),
        ).squeeze()
        return database_location == "remote"

    def server_version(self) -> ServerVersion:
        return self._gds_query_runner.server_version()

    def driver_config(self) -> dict[str, Any]:
        return self._db_query_runner.driver_config()

    def encrypted(self) -> bool:
        return self._db_query_runner.encrypted()

    def set_database(self, database: str) -> None:
        self._db_query_runner.set_database(database)

    def set_bookmarks(self, bookmarks: Optional[Any]) -> None:
        self._db_query_runner.set_bookmarks(bookmarks)

    def bookmarks(self) -> Optional[Any]:
        return self._db_query_runner.bookmarks()

    def last_bookmarks(self) -> Optional[Any]:
        return self._db_query_runner.last_bookmarks()

    def database(self) -> Optional[str]:
        return self._db_query_runner.database()

    def create_graph_constructor(
        self, graph_name: str, concurrency: int, undirected_relationship_types: Optional[list[str]]
    ) -> GraphConstructor:
        return self._gds_query_runner.create_graph_constructor(graph_name, concurrency, undirected_relationship_types)

    def set_show_progress(self, show_progress: bool) -> None:
        self._show_progress = show_progress
        self._gds_query_runner.set_show_progress(show_progress)

    def close(self) -> None:
        self._gds_arrow_client.close()
        self._gds_query_runner.close()
        self._db_query_runner.close()

    def _remote_projection(
        self,
        endpoint: str,
        params: CallParameters,
        terminationFlag: TerminationFlag,
        yields: Optional[list[str]] = None,
        database: Optional[str] = None,
        logging: bool = False,
    ) -> DataFrame:
        self._inject_arrow_config(params["arrow_configuration"])

        graph_name = params["graph_name"]
        query = params["query"]
        arrow_config = params["arrow_configuration"]

        job_id = params["job_id"] if "job_id" in params and params["job_id"] else str(uuid4())
        project_protocol = ProjectProtocol.select(self._resolved_protocol_version)
        project_params = project_protocol.project_params(graph_name, query, job_id, params, arrow_config)

        try:

            def run_projection() -> DataFrame:
                return project_protocol.run_projection(
                    self._db_query_runner, endpoint, project_params, terminationFlag, yields, database, logging
                )

            if self._resolve_show_progress(logging):
                return self._progress_logger.run_with_progress_logging(run_projection, job_id, database)
            else:
                return run_projection()
        except Exception as e:
            GdsArrowClient.handle_flight_error(e)
            raise e  # above should already raise

    def _remote_write_back(
        self,
        endpoint: str,
        params: CallParameters,
        terminationFlag: TerminationFlag,
        yields: Optional[list[str]] = None,
        database: Optional[str] = None,
        logging: bool = False,
        custom_error: bool = True,
    ) -> DataFrame:
        if params["config"] is None:
            params["config"] = {}

        config: dict[str, Any] = params.get("config", {})

        # we pop these out so that they are not retained for the GDS proc call
        db_arrow_config = config.pop("arrowConfiguration", {})

        job_id = config["jobId"] if "jobId" in config else str(uuid4())
        config["jobId"] = job_id

        config["writeToResultStore"] = True

        gds_write_result = self._gds_query_runner.call_procedure(
            endpoint, params, yields, database, logging, custom_error
        )
        terminationFlag.assert_running()

        self._inject_arrow_config(db_arrow_config)

        graph_name = params["graph_name"]

        write_protocol = WriteProtocol.select(self._resolved_protocol_version)
        write_back_params = write_protocol.write_back_params(
            graph_name, job_id, config, db_arrow_config, self._db_query_runner.database()
        )

        write_back_start = time.time()

        def run_write_back() -> DataFrame:
            return write_protocol.run_write_back(self._db_query_runner, write_back_params, yields, terminationFlag)

        try:
            if self._resolve_show_progress(logging):
                database_write_result = self._progress_logger.run_with_progress_logging(
                    run_write_back, job_id, database
                )
            else:
                database_write_result = run_write_back()
        except Exception as e:
            # catch the case nothing was needed to write-back (empty graph)
            # once we have the Arrow Endpoints V2, we could catch by first checking the jobs summary
            if "No entry with job id" in str(e) and gds_write_result.iloc[0].get("writeMillis", -1) == 0:
                return gds_write_result
            raise e

        write_millis = (time.time() - write_back_start) * 1000
        gds_write_result["writeMillis"] = write_millis

        if "nodePropertiesWritten" in gds_write_result:
            gds_write_result["nodePropertiesWritten"] = database_write_result["writtenNodeProperties"]
        if "propertiesWritten" in gds_write_result:
            gds_write_result["propertiesWritten"] = database_write_result["writtenNodeProperties"]
        if "nodeLabelsWritten" in gds_write_result:
            gds_write_result["nodeLabelsWritten"] = database_write_result["writtenNodeLabels"]
        if "relationshipsWritten" in gds_write_result:
            gds_write_result["relationshipsWritten"] = database_write_result["writtenRelationships"]

        return gds_write_result

    def _resolve_show_progress(self, show_progress: bool) -> bool:
        return self._show_progress and show_progress

    def _inject_arrow_config(self, params: dict[str, Any]) -> None:
        host, port = self._gds_arrow_client.connection_info()
        token = self._gds_arrow_client.request_token()
        if token is None:
            token = "IGNORED"

        params["host"] = host
        params["port"] = port
        params["token"] = token
        params["encrypted"] = self._gds_query_runner.encrypted()
