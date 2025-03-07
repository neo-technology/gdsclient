from __future__ import annotations

import hashlib
import math
import warnings
from datetime import datetime, timedelta, timezone
from typing import Optional

from graphdatascience.query_runner.neo4j_query_runner import Neo4jQueryRunner
from graphdatascience.session.algorithm_category import AlgorithmCategory
from graphdatascience.session.aura_api import AuraApi
from graphdatascience.session.aura_api_responses import SessionDetails
from graphdatascience.session.aura_graph_data_science import AuraGraphDataScience
from graphdatascience.session.cloud_location import CloudLocation
from graphdatascience.session.dbms_connection_info import DbmsConnectionInfo
from graphdatascience.session.session_info import SessionInfo
from graphdatascience.session.session_sizes import SessionMemory, SessionMemoryValue


class DedicatedSessions:
    # Hardcoded neo4j user as sessions are always created with this user
    GDS_SESSION_USER = "neo4j"

    def __init__(self, aura_api: AuraApi) -> None:
        self._aura_api = aura_api

    def estimate(
        self,
        node_count: int,
        relationship_count: int,
        algorithm_categories: Optional[list[AlgorithmCategory]] = None,
    ) -> SessionMemory:
        if algorithm_categories is None:
            algorithm_categories = []
        estimation = self._aura_api.estimate_size(node_count, relationship_count, algorithm_categories)

        if estimation.did_exceed_maximum:
            warnings.warn(
                f"The estimated memory `{estimation.min_required_memory}` exceeds the maximum size"
                f" supported by your Aura tenant (`{estimation.recommended_size}`).",
                ResourceWarning,
            )

        return SessionMemory(SessionMemoryValue(estimation.recommended_size))

    def available_cloud_locations(self) -> list[CloudLocation]:
        """
        Retrieves the list of available cloud locations in Aura.

        Returns:
            list[CloudLocation]: The list of available cloud locations.
        """
        # return a list to allow index based access
        return list(self._aura_api.tenant_details().cloud_locations)

    def get_or_create(
        self,
        session_name: str,
        memory: SessionMemory,
        db_connection: Optional[DbmsConnectionInfo],
        ttl: Optional[timedelta] = None,
        cloud_location: Optional[CloudLocation] = None,
        timeout: Optional[int] = None,
    ) -> AuraGraphDataScience:
        db_runner: Optional[Neo4jQueryRunner] = None
        dbid: Optional[str] = None
        if db_connection:
            db_runner = Neo4jQueryRunner.create_for_db(
                endpoint=db_connection.uri,
                auth=db_connection.auth(),
                aura_ds=True,
                show_progress=False,
                database=db_connection.database,
            )
            self._validate_db_connection(db_runner)
            dbid = AuraApi.extract_id(db_connection.uri)

            # hashing the password to avoid storing the actual db password in Aura
            password = hashlib.sha256(db_connection.password.encode()).hexdigest()

        session_details = self._get_or_create_session(session_name, dbid, password, memory.value, ttl, cloud_location)

        if session_details.expiry_date:
            until_expiry: timedelta = session_details.expiry_date - datetime.now(timezone.utc)
            if until_expiry < timedelta(days=1):
                raise Warning(f"Session `{session_details.name}` is expiring in less than a day.")

        session_id = session_details.id

        connection_url = session_details.bolt_connection_url()
        if session_details.status != "Ready":
            max_wait_time = float(timeout) if timeout is not None else math.inf
            wait_result = self._aura_api.wait_for_session_running(session_id, max_wait_time=max_wait_time)
            if err := wait_result.error:
                raise RuntimeError(f"Failed to get or create session `{session_name}`: {err}")

        session_connection = DbmsConnectionInfo(
            uri=connection_url,
            username=DedicatedSessions.GDS_SESSION_USER,
            password=password,
        )

        return self._construct_client(
            session_id=session_id,
            session_connection=session_connection,
            db_runner=db_runner,
        )

    def delete(self, *, session_name: Optional[str] = None, session_id: Optional[str] = None) -> bool:
        if not session_name and not session_id:
            raise ValueError("Either session_name or session_id must be provided.")

        if session_id:
            return self._aura_api.delete_session(session_id) is not None

        if session_name:
            candidate = self._find_existing_session(session_name)
            if candidate:
                return self._aura_api.delete_session(candidate.id) is not None

        return False

    def list(self, dbid: Optional[str] = None) -> list[SessionInfo]:
        sessions: list[SessionDetails] = self._aura_api.list_sessions(dbid)

        return [SessionInfo.from_session_details(i) for i in sessions]

    def _find_existing_session(self, session_name: str) -> Optional[SessionDetails]:
        matched_sessions: list[SessionDetails] = []
        matched_sessions = [s for s in self._aura_api.list_sessions() if s.name == session_name]

        if len(matched_sessions) == 0:
            return None

        # this will only occur for admins as we cannot resolve Aura-API client_id -> console_user_id we fail for now
        if len(matched_sessions) > 1:
            raise RuntimeError(
                f"The user has access to multiple session with the name `{session_name}`. Please specify the id of the session that should be deleted."
            )

        return matched_sessions[0]

    @staticmethod
    def _validate_db_connection(db_runner: Neo4jQueryRunner) -> None:
        try:
            db_runner.verify_connectivity()
        except Exception as e:
            raise RuntimeError(f"Failed to connect to the Neo4j database: {e}")
        try:
            db_runner.verify_authentication()
        except Exception as e:
            raise RuntimeError(f"Failed to authenticate to the Neo4j database: {e}")

    def _get_or_create_session(
        self,
        session_name: str,
        dbid: Optional[str],
        pwd: str,
        memory: SessionMemoryValue,
        ttl: Optional[timedelta] = None,
        cloud_location: Optional[CloudLocation] = None,
    ) -> SessionDetails:
        db_instance = self._aura_api.list_instance(dbid) if dbid else None

        if not (db_instance or cloud_location):
            raise ValueError("cloud_location must be provided for sessions against a self-managed DB.")

        if cloud_location and db_instance:
            raise ValueError("cloud_location cannot be provided for sessions against an AuraDB.")

        # If cloud location is provided we go for self managed DBs path
        if cloud_location:
            return self._aura_api.get_or_create_session(
                name=session_name,
                pwd=pwd,
                memory=memory,
                ttl=ttl,
                cloud_location=cloud_location,
            )
        else:
            return self._aura_api.get_or_create_session(name=session_name, dbid=dbid, pwd=pwd, memory=memory, ttl=ttl)

    def _construct_client(
        self,
        session_id: str,
        session_connection: DbmsConnectionInfo,
        db_runner: Optional[Neo4jQueryRunner],
    ) -> AuraGraphDataScience:
        return AuraGraphDataScience.create(
            gds_session_connection_info=session_connection,
            db_endpoint=db_runner,
            delete_fn=lambda: self._aura_api.delete_session(session_id=session_id),
        )
