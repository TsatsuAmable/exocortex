#!/usr/bin/env python3
from __future__ import annotations
from abc import ABC, abstractmethod
from neo4j import GraphDatabase
from neo4j_projection import _password

class GraphBackend(ABC):
    @abstractmethod
    def query(self, cypher:str, **params): ...
    @abstractmethod
    def close(self): ...

class Neo4jBackend(GraphBackend):
    def __init__(self, uri="bolt://127.0.0.1:7687", user="neo4j", password=None):
        self.driver=GraphDatabase.driver(uri,auth=(user,password or _password()))
        self.driver.verify_connectivity()
    def query(self, cypher:str, **params):
        with self.driver.session() as s:
            return [dict(r) for r in s.run(cypher,**params)]
    def close(self):
        self.driver.close()

def open_backend(kind="neo4j", **kwargs):
    if kind=="neo4j":
        return Neo4jBackend(**kwargs)
    if kind=="memgraph":
        # Memgraph speaks Bolt/Cypher, so this adapter can reuse the same driver.
        kwargs.setdefault("uri","bolt://127.0.0.1:7688")
        kwargs.setdefault("user","")
        kwargs.setdefault("password","")
        return Neo4jBackend(**kwargs)
    raise ValueError(f"unknown graph backend: {kind}")
