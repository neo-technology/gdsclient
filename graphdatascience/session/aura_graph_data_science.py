from __future__ import annotations

from typing import Any, Callable, Optional, Union

from pandas import DataFrame

from graphdatascience import QueryRunner, ServerVersion
from graphdatascience.call_builder import IndirectCallBuilder
from graphdatascience.endpoints import (
    AlphaRemoteEndpoints,
    BetaEndpoints,
    DirectEndpoints,
)
from graphdatascience.error.uncallable_namespace import UncallableNamespace
from graphdatascience.graph.graph_remote_proc_runner import GraphRemoteProcRunner
from graphdatascience.query_runner.arrow_info import ArrowInfo
from graphdatascience.query_runner.arrow_query_runner import ArrowQueryRunner
from graphdatascience.query_runner.gds_arrow_client import GdsArrowClient
from graphdatascience.query_runner.neo4j_query_runner import Neo4jQueryRunner
from graphdatascience.query_runner.session_query_runner import SessionQueryRunner
from graphdatascience.query_runner.standalone_session_query_runner import StandAloneSessionQueryRunner
from graphdatascience.session.dbms_connection_info import DbmsConnectionInfo
from graphdatascience.utils.util_remote_proc_runner import UtilRemoteProcRunner


class AuraGraphDataScience(DirectEndpoints, UncallableNamespace):
    """
    Primary API class for interacting with Neo4j database + Graph Data Science Session.
    Always bind this object to a variable called `gds`.
    """

    @classmethod
    def create(
        cls,
        gds_session_connection_info: DbmsConnectionInfo,
        db_endpoint: Optional[Union[Neo4jQueryRunner, DbmsConnectionInfo]],
        delete_fn: Callable[[], bool],
        arrow_disable_server_verification: bool = False,
        arrow_tls_root_certs: Optional[bytes] = None,
        bookmarks: Optional[Any] = None,
        show_progress: bool = True,
    ) -> AuraGraphDataScience:
        # we need to explicitly set this as the default value is None
        # database in the session is always neo4j
        session_bolt_query_runner = Neo4jQueryRunner.create_for_session(
            endpoint=gds_session_connection_info.uri,
            auth=gds_session_connection_info.auth(),
            show_progress=show_progress,
        )

        arrow_info = ArrowInfo.create(session_bolt_query_runner)
        session_arrow_query_runner = ArrowQueryRunner.create(
            fallback_query_runner=session_bolt_query_runner,
            arrow_info=arrow_info,
            auth=gds_session_connection_info.auth(),
            encrypted=session_bolt_query_runner.encrypted(),
            disable_server_verification=arrow_disable_server_verification,
            tls_root_certs=arrow_tls_root_certs,
        )

        # TODO: merge with the gds_arrow_client created inside ArrowQueryRunner
        session_arrow_client = GdsArrowClient.create(
            arrow_info,
            gds_session_connection_info.auth(),
            session_bolt_query_runner.encrypted(),
            arrow_disable_server_verification,
            arrow_tls_root_certs,
        )

        if not db_endpoint:
            db_bolt_query_runner = None
        elif isinstance(db_endpoint, Neo4jQueryRunner):
            db_bolt_query_runner = db_endpoint
        else:
            db_bolt_query_runner = Neo4jQueryRunner.create_for_db(
                db_endpoint.uri,
                db_endpoint.auth(),
                aura_ds=True,
                show_progress=False,
                database=db_endpoint.database,
            )
        if db_bolt_query_runner and bookmarks:
            db_bolt_query_runner.set_bookmarks(bookmarks)

        if db_bolt_query_runner:
            session_query_runner: QueryRunner = SessionQueryRunner.create(
                session_arrow_query_runner, db_bolt_query_runner, session_arrow_client, show_progress
            )
        else:
            session_query_runner: QueryRunner = StandAloneSessionQueryRunner.create(
                session_arrow_query_runner, session_arrow_client, show_progress
            )

        gds_version = session_bolt_query_runner.server_version()
        return cls(
            query_runner=session_query_runner,
            delete_fn=delete_fn,
            gds_version=gds_version,
        )

    def __init__(
        self,
        query_runner: QueryRunner,
        delete_fn: Callable[[], bool],
        gds_version: ServerVersion,
    ):
        self._query_runner = query_runner
        self._delete_fn = delete_fn
        self._server_version = gds_version

        super().__init__(self._query_runner, namespace="gds", server_version=self._server_version)

    def run_cypher(
        self,
        query: str,
        params: Optional[dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> DataFrame:
        """
        Run a Cypher query against the Neo4j database.

        Parameters
        ----------
        query: str
            the Cypher query
        params: dict[str, Any]
            parameters to the query
        database: str
            the database on which to run the query

        Returns:
            The query result as a DataFrame
        """
        return self._query_runner.run_cypher(query, params, database, False)

    @property
    def graph(self) -> GraphRemoteProcRunner:
        return GraphRemoteProcRunner(self._query_runner, f"{self._namespace}.graph", self._server_version)

    @property
    def util(self) -> UtilRemoteProcRunner:
        return UtilRemoteProcRunner(self._query_runner, f"{self._namespace}.util", self._server_version)

    @property
    def alpha(self) -> AlphaRemoteEndpoints:
        return AlphaRemoteEndpoints(self._query_runner, "gds.alpha", self._server_version)

    @property
    def beta(self) -> BetaEndpoints:
        return BetaEndpoints(self._query_runner, "gds.beta", self._server_version)

    def __getattr__(self, attr: str) -> IndirectCallBuilder:
        return IndirectCallBuilder(self._query_runner, f"gds.{attr}", self._server_version)

    def set_database(self, database: str) -> None:
        """
        Set the database which cypher queries are run against.

        Parameters
        -------
        database: str
            The name of the database to run queries against.
        """
        self._query_runner.set_database(database)

    def set_bookmarks(self, bookmarks: Any) -> None:
        """
        Set Neo4j bookmarks to require a certain state before the next query gets executed

        Parameters
        ----------
        bookmarks: Bookmark(s)
            The Neo4j bookmarks defining the required state
        """
        self._query_runner.set_bookmarks(bookmarks)

    def set_show_progress(self, show_progress: bool) -> None:
        """
        Set whether to show progress for running procedures.

        Parameters
        ----------
        show_progress: bool
            Whether to show progress for procedures.
        """
        self._query_runner.set_show_progress(show_progress)

    def database(self) -> Optional[str]:
        """
        Get the database which cypher queries are run against.

        Returns:
            The name of the database.
        """
        return self._query_runner.database()

    def bookmarks(self) -> Optional[Any]:
        """
        Get the Neo4j bookmarks defining the currently required states for cypher queries to execute

        Returns
        -------
        The (possibly None) Neo4j bookmarks defining the currently required state
        """
        return self._query_runner.bookmarks()

    def last_bookmarks(self) -> Optional[Any]:
        """
        Get the Neo4j bookmarks defining the state following the most recently called query

        Returns
        -------
        The (possibly None) Neo4j bookmarks defining the state following the most recently called query
        """
        return self._query_runner.last_bookmarks()

    def driver_config(self) -> dict[str, Any]:
        """
        Get the configuration used to create the underlying driver used to make queries to Neo4j.

        Returns:
            The configuration as a dictionary.
        """
        return self._query_runner.driver_config()

    def delete(self) -> bool:
        """
        Delete a GDS session.
        """
        self.close()
        return self._delete_fn()

    def close(self) -> None:
        """
        Close the GraphDataScience object and release any resources held by it.
        """
        self._query_runner.close()
