"""Neo4j 服务拓扑查询适配器。"""

from __future__ import annotations

from typing import Any, Callable


class Neo4jTopologyProvider:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        driver_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not isinstance(uri, str) or not uri.startswith(("bolt://", "neo4j://", "neo4j+s://")):
            raise ValueError("uri 必须是 Neo4j 地址")
        if not user or not password:
            raise ValueError("user 和 password 不能为空")
        self.uri = uri
        self.user = user
        self.password = password
        self._driver_factory = driver_factory
        self._driver: Any | None = None

    def _get_driver(self) -> Any:
        if self._driver is not None:
            return self._driver
        if self._driver_factory is not None:
            self._driver = self._driver_factory(self.uri, auth=(self.user, self.password))
            return self._driver
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError("Neo4j 模式需要安装 neo4j：python -m pip install neo4j") from exc
        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        return self._driver

    def get_dependencies(self, service: str) -> list[str]:
        if not isinstance(service, str) or not service.strip():
            raise ValueError("service 不能为空")
        query = (
            "MATCH (s:Service {name: $service})-[:DEPENDS_ON]->(d:Service) "
            "RETURN d.name AS name ORDER BY d.name"
        )
        with self._get_driver().session() as session:
            rows = session.run(query, service=service.strip())
            return [str(row["name"]) for row in rows if row.get("name")]

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
