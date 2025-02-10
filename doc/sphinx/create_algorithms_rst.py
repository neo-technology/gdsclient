import json
from textwrap import dedent

INCLUDED_ALGORITHMS = {
    "Article Rank",
    "Articulation Points",
    "Betweenness Centrality",
    "Bridges",
    # "CELF",
    # "Closeness Centrality",
    "Degree Centrality",
    "Eigenvector Centrality",
    "PageRank",
    # "Harmonic Centrality",
    # "HITS",
    "Conductance metric",
    # "K-Core Decomposition",
    # "K-1 Coloring",
    # "K-Means Clustering",
    # "Label Propagation",
    # "Leiden",
    "Local Clustering Coefficient",
    # "Louvain",
    "Modularity metric",
    # "Modularity Optimization",
    # "Strongly Connected Components",
    "Triangle Count",
    # "Weakly Connected Components",
    # "Approximate Maximum k-cut",
    # "Speaker-Listener Label Propagation",
    "Node Similarity",
    # "Filtered Node Similarity",
    # "K-Nearest Neighbors",
    # "Filtered K-Nearest Neighbors",
    "Delta-Stepping Single-Source Shortest Path",
    # "Dijkstra Source-Target Shortest Path",
    # "Dijkstra Single-Source Shortest Path",
    # "A* Shortest Path",
    # "Yen's Shortest Path algorithm",
    # "Minimum Weight Spanning Tree",
    # "Minimum Directed Steiner Tree",
    # "Random Walk",
    "Breadth First Search",
    "Depth First Search",
    # "Bellman-Ford Single-Source Shortest Path",
    # "Longest Path for DAG",
    # "All Pairs Shortest Path",
    # "Topological Sort",
    # "Longest Path for DAG",
    "Fast Random Projection",
    "GraphSAGE",
    "Node2Vec",
    "HashGNN",
}


def write_param(param, optional):
    name, description, default = conf["name"], conf["description"], conf["default"]
    default_placeholder = f' ({conf["default_placeholder"]})' if "default_placeholder" in conf else ""
    description = description.replace("\n", "\n                ")

    if optional:
        return f"        * **{name}** - *(Optional)* {description} *Default*: {default}{default_placeholder}."
    else:
        return f"        * **{name}** - {description}"


def get_required_conf(config):
    return [conf for conf in config if not conf["optional"]]


def get_optional_conf(config):
    return [conf for conf in config if conf["optional"]]


def enrich_signature(sig, required, optional):
    conf_string = []

    for conf in required:
        conf_string.append(conf["name"])

    for conf in optional:
        conf_name, conf_type, conf_default = conf["name"], conf["type"], conf["default"]
        # if conf_type == "Float":
        #     try:
        #         conf_default = float(conf_default)
        #     except:
        #         print(f"{conf_default} not a float")
        # elif conf_type == "Integer":
        #     try:
        #         conf_default = int(conf_default)
        #     except:
        #         print(f"{conf_default} not an int")

        if conf_default == "null":
            conf_default = None

        conf_string.append(f"{conf_name}={conf_default}")

    if conf_string:
        return sig.replace("**config: Any", f"*, {', '.join(conf_string)}")
    else:
        return sig


with open("algorithms-conf.json") as f:
    j = json.load(f)
    modes = j["modes"]
    algorithms = {algo["procedure"]: algo for algo in j["algorithms"] if algo["name"] in INCLUDED_ALGORITHMS}

PREAMBLE = """\
    ..
        DO NOT EDIT - File generated automatically

    Algorithms procedures
    ----------------------
    Listing of all algorithm procedures in the Neo4j Graph Data Science Python Client API.
    These all assume that an object of :class:`.GraphDataScience` is available as `gds`.

"""

with open("algorithms.json") as f, open("source/algorithms.rst", "w") as fw:
    functions = json.load(f)

    fw.write(dedent(PREAMBLE))

    for function in functions:
        name, sig, ret_type = (
            function["function"]["name"],
            function["function"]["signature"],
            function["function"]["return_type"],
        )

        # Example: gds.triangleCount.stream -> (gds.triangleCount, stream)
        proc_name, proc_mode = name.rsplit(".", maxsplit=1)
        required = []
        optional = []

        if proc_name in algorithms and proc_mode == "stream":
            mode_config = modes[proc_mode]["config"]
            config = algorithms[proc_name]["config"]

            required = get_required_conf(mode_config) + get_required_conf(config)
            optional = get_optional_conf(mode_config) + get_optional_conf(config)

        fw.write(f".. py:function:: {name}({enrich_signature(sig, required, optional)}) -> {ret_type}\n\n")

        if "description" in function:
            description = function["description"].strip()
            for desc in description.split("\n"):
                fw.write(f"    {desc}\n")

            fw.write("\n")

        if "deprecated" in function:
            version, message = function["deprecated"]["version"], function["deprecated"]["message"]
            fw.write(f".. deprecated:: {version}\n")
            fw.write(f"   {message}\n\n")

        if required or optional:
            fw.write("    |\n\n")
            fw.write("    **Parameters:**\n\n")

            for param in sig.split(","):
                param_name, param_type = param.split(":")
                param_name = param_name.strip()
                param_type = param_type.strip()

                if param_name != "**config":
                    fw.write(f"        * **{param_name}** - {param_type}\n\n")
                else:
                    for conf in required:
                        fw.write(write_param(conf, False) + "\n\n")

                    for conf in optional:
                        fw.write(write_param(conf, True) + "\n\n")

                    fw.write("\n\n")
