import os
import time
import warnings
from collections import defaultdict

from neo4j.exceptions import ClientError
from tqdm import tqdm

from graphdatascience import GraphDataScience

warnings.filterwarnings("ignore", category=DeprecationWarning)


def setup_connection():
    NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_AUTH = None
    NEO4J_DB = os.environ.get("NEO4J_DB", "neo4j")
    if os.environ.get("NEO4J_USER") and os.environ.get("NEO4J_PASSWORD"):
        NEO4J_AUTH = (
            os.environ.get("NEO4J_USER"),
            os.environ.get("NEO4J_PASSWORD"),
        )
    gds = GraphDataScience(NEO4J_URI, auth=NEO4J_AUTH, database=NEO4J_DB, arrow=True)

    return gds


def create_constraint(gds):
    try:
        _ = gds.run_cypher("CREATE CONSTRAINT entity_id FOR (e:Entity) REQUIRE e.id IS UNIQUE")
    except ClientError:
        print("CONSTRAINT entity_id already exists")


def download_data(raw_file_names):
    import os
    import zipfile

    from ogb.utils.url import download_url

    url = "https://download.microsoft.com/download/8/7/0/8700516A-AB3D-4850-B4BB-805C515AECE1/FB15K-237.2.zip"
    raw_dir = "./data_from_zip"
    download_url(f"{url}", raw_dir)

    with zipfile.ZipFile(raw_dir + "/" + os.path.basename(url), "r") as zip_ref:
        for filename in raw_file_names:
            zip_ref.extract(f"Release/{filename}", path=raw_dir)
    data_dir = raw_dir + "/" + "Release"
    return data_dir


def read_data():
    rel_types = {
        "train.txt": "TRAIN",
        "valid.txt": "VALID",
        "test.txt": "TEST",
    }
    raw_file_names = ["train.txt", "valid.txt", "test.txt"]

    data_dir = download_data(raw_file_names)

    rel_id_to_text_dict = {}
    rel_dict = {}
    node_id_set = {}
    dataset = defaultdict(lambda: defaultdict(list))
    for file_name in raw_file_names:
        file_name_path = data_dir + "/" + file_name

        with open(file_name_path, "r") as f:
            data = [x.split("\t") for x in f.read().split("\n")[:-1]]

        for i, (src_text, rel_text, dst_text) in enumerate(data):
            if src_text not in node_id_set:
                node_id_set[src_text] = len(node_id_set)
            if dst_text not in node_id_set:
                node_id_set[dst_text] = len(node_id_set)
            if rel_text not in rel_dict:
                rel_dict[rel_text] = len(rel_dict)
                rel_id_to_text_dict[rel_dict[rel_text]] = rel_text

            source = node_id_set[src_text]
            target = node_id_set[dst_text]
            rel_type = "REL_" + str(rel_dict[rel_text])
            rel_split = rel_types[file_name]

            dataset[rel_split][rel_type].append(
                {
                    "source": source,
                    "source_text": src_text,
                    "target": target,
                    "target_text": dst_text,
                    # "rel_text": rel_text,
                }
            )

    print("Number of nodes: ", len(node_id_set))
    for rel_split in dataset:
        print(
            f"Number of relationships of type {rel_split}: ",
            sum([len(dataset[rel_split][rel_type]) for rel_type in dataset[rel_split]]),
        )
    return dataset


def put_data_in_db(gds):
    res = gds.run_cypher("MATCH (m) RETURN count(m) as num_nodes")
    if res["num_nodes"].values[0] > 0:
        print("Data already in db, number of nodes: ", res["num_nodes"].values[0])
        return
    dataset = read_data()
    pbar = tqdm(
        desc="Putting data in db",
        total=sum([len(dataset[rel_split][rel_type]) for rel_split in dataset for rel_type in dataset[rel_split]]),
    )
    rel_split_id = {"TRAIN": 0, "VALID": 1, "TEST": 2}
    for rel_split in dataset:
        for rel_type in dataset[rel_split]:
            edges = dataset[rel_split][rel_type]

            # MERGE (n)-[:{rel_type} {{text:l.rel_text}}]->(m)
            # MERGE (n)-[:{rel_split}]->(m)
            gds.run_cypher(
                f"""
                UNWIND $ll as l
                MERGE (n:Entity {{id:l.source, text:l.source_text}})
                MERGE (m:Entity {{id:l.target, text:l.target_text}})
                MERGE (n)-[:{rel_type} {{split: {rel_split_id[rel_split]}}}]->(m)
                """,
                params={"ll": edges},
            )
            pbar.update(len(edges))
    pbar.close()

    for rel_split in dataset:
        res = gds.run_cypher(
            f"""
            MATCH ()-[r:{rel_split}]->()
            RETURN COUNT(r) AS numberOfRelationships
            """
        )
        print(f"Number of relationships of type {rel_split} in db: ", res.numberOfRelationships)


def project_train_graph(gds):
    all_rels = gds.run_cypher(
        """
    CALL db.relationshipTypes() YIELD relationshipType
    """
    )
    all_rels = all_rels["relationshipType"].to_list()
    all_rels = [rel for rel in all_rels if rel.startswith("REL_")]
    gds.graph.drop("trainGraph", failIfMissing=False)

    G_train, result = gds.graph.project("trainGraph", ["Entity"], all_rels)

    return G_train


def project_predict_graph(gds):
    all_rels = gds.run_cypher(
        """
    CALL db.relationshipTypes() YIELD relationshipType
    """
    )
    all_rels = all_rels["relationshipType"].to_list()
    rel_spec = {}
    for rel in all_rels:
        if rel.startswith("REL_"):
            rel_spec[rel] = {"properties": ["split"]}

    gds.graph.drop("fullGraph", failIfMissing=False)
    gds.graph.drop("predictGraph", failIfMissing=False)

    # {"REL": {"properties": ["relY"]}, "RELR": {"properties": ["relY"]}}
    # print(rel_spec)

    G_full, result = gds.graph.project("fullGraph", ["Entity"], all_rels)

    G_full, result = gds.graph.project("fullGraph", ["Entity"], rel_spec)
    # G_predict = gds.graph.filter('predictGraph', 'fullGraph', '*', 'r.split == 2')

    inspect_graph(G_full)
    return G_full


def inspect_graph(G):
    func_names = [
        "name",
        "node_count",
        "relationship_count",
        "node_labels",
        "relationship_types",
    ]
    for func_name in func_names:
        print(f"==={func_name}===: {getattr(G, func_name)()}")


if __name__ == "__main__":
    gds = setup_connection()
    create_constraint(gds)
    put_data_in_db(gds)
    G_train = project_train_graph(gds)
    # G_predict = project_predict_graph(gds)
    # inspect_graph(G_train)

    gds.set_compute_cluster_ip("localhost")

    print(gds.debug.arrow())

    model_name = "dummyModelName_" + str(time.time())

    gds.kge.model.train(
        G_train,
        model_name=model_name,
        scoring_function="DistMult",
        num_epochs=1,
        embedding_dimension=10,
        epochs_per_checkpoint=0,
    )

    gds.kge.model.predict(
        G_train,
        model_name=model_name,
        top_k=10,
        node_ids=[1, 2, 3],
        rel_types=["REL_1", "REL_2"],
    )

    gds.kge.model.predict_tail(
        G_train,
        model_name=model_name,
        top_k=10,
        node_ids=[gds.find_node_id(["Entity"], {"text": "/m/016wzw"}), gds.find_node_id(["Entity"], {"id": 2})],
        rel_types=["REL_1", "REL_2"],
    )

    gds.kge.model.score_triples(
        G_train,
        model_name=model_name,
        triples=[
            (gds.find_node_id(["Entity"], {"text": "/m/016wzw"}), "REL_1", gds.find_node_id(["Entity"], {"id": 2})),
            (gds.find_node_id(["Entity"], {"id": 0}), "REL_123", gds.find_node_id(["Entity"], {"id": 3})),
        ],
    )

    print("Finished training")
