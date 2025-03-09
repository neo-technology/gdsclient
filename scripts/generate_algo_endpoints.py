#!/usr/bin/env python3

from graphdatascience import GraphDataScience
from collections import defaultdict
import os

ALGO_MODES = {"mutate", "stats", "stream", "train", "write"}

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = ("neo4j", "password")
if os.environ.get("NEO4J_USER"):
    AUTH = (
        os.environ.get("NEO4J_USER", "DUMMY"),
        os.environ.get("NEO4J_PASSWORD", "neo4j"),
    )
DB = os.environ.get("NEO4J_DB", "neo4j")

gds = GraphDataScience(URI, auth=AUTH, database=DB)


all_endpoints = gds.list()["name"].tolist()
alpha_algo_endpoints = defaultdict(lambda: list())
beta_algo_endpoints = defaultdict(lambda: list())
prod_algo_endpoints = defaultdict(lambda: list())
asp_algo_endpoints = defaultdict(lambda: list())
sp_algo_endpoints = defaultdict(lambda: list())


def add_mode(algo_name, mode, endpoints):
    if mode == "mutate":
        endpoints[algo_name].append("MutateEndpoint")
    elif mode == "stats":
        endpoints[algo_name].append("StatsEndpoint")
    elif mode == "stream":
        endpoints[algo_name].append("StreamEndpoint")
    elif mode == "train":
        endpoints[algo_name].append("TrainEndpoint")
    elif mode == "write":
        endpoints[algo_name].append("WriteEndpoint")


def collect_algo_endpoints(all_endpoints):
    for e in all_endpoints:
        ep_components = e.split(".")

        if ep_components[-1] not in ALGO_MODES:
            continue

        if "graph" in ep_components:
            continue

        if "pipeline" in ep_components:
            continue

        ep_components = e.split(".")
        if len(ep_components) == 3:
            add_mode(ep_components[1], ep_components[2], prod_algo_endpoints)
        elif len(ep_components) == 4:
            if ep_components[1] == "alpha":
                add_mode(ep_components[2], ep_components[3], alpha_algo_endpoints)
            elif ep_components[1] == "beta":
                add_mode(ep_components[2], ep_components[3], beta_algo_endpoints)
            elif ep_components[1] == "allShortestPaths":
                add_mode(ep_components[2], ep_components[3], asp_algo_endpoints)
            elif ep_components[1] == "shortestPath":
                add_mode(ep_components[2], ep_components[3], sp_algo_endpoints)
            else:
                raise RuntimeError(f"Unable to handle algo endpoint '{e}'")
        else:
            # raise RuntimeError(f"Unable to handle algo endpoint '{e}'")
            print(e)


def generate_algo_endpoint_builder(algo_name, algo_memberships):
    return f"""
    @property
    def {algo_name}(self):
        return CallerBase({', '.join(algo_memberships)})
    """


def populate_class(class_base, algo_pairs):
    algo_eps = os.linesep.join([generate_algo_endpoint_builder(name, classes) for name, classes in algo_pairs.items()])
    # for name, super_classes in algo_pairs.items():
    #     class_base.append(generate_algo_endpoint_builder(name, super_classes))

    return f"{class_base}{algo_eps}"


collect_algo_endpoints(all_endpoints)

alpha_algos_class = "class AlphaAlgos(UncallableNamespace):"
beta_algos_class = "class BetaAlgos(UncallableNamespace):"
prod_algos_class = "class ProdAlgos(UncallableNamespace):"
asp_algos_class = "class ASPAlgos(UncallableNamespace):"
sp_algos_class = "class SPAlgos(UncallableNamespace):"

print(populate_class(alpha_algos_class, alpha_algo_endpoints))

# print(alpha_algos_class)
