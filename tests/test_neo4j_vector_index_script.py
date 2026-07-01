from scripts.init_neo4j_vector_index import build_vector_index_cypher


def test_build_vector_index_cypher_targets_evidence_embedding():
    cypher = build_vector_index_cypher("labkag_evidence_embedding_index", 1536)

    assert "CREATE VECTOR INDEX" in cypher
    assert "labkag_evidence_embedding_index" in cypher
    assert "`vector.dimensions`: 1536" in cypher
    assert "`vector.similarity_function`: 'cosine'" in cypher
    assert "FOR (e:Evidence) ON (e.embedding)" in cypher
