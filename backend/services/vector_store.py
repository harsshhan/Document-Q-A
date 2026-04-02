import faiss
import numpy as np

# global storage (simple for now)
index = None
stored_chunks = []

def create_index(embeddings, chunks):
    global index, stored_chunks

    dimension = len(embeddings[0])  # vector size

    index = faiss.IndexFlatL2(dimension)

    vectors = np.array(embeddings).astype("float32")

    index.add(vectors)

    stored_chunks = chunks


def search(query_embedding, k=3):
    global index, stored_chunks

    query_vector = np.array([query_embedding]).astype("float32")

    distances, indices = index.search(query_vector, k)

    results = [stored_chunks[i] for i in indices[0]]

    return results