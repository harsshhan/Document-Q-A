from fastapi import FastAPI, UploadFile, File
from services.pdf_loader import extract_text
from services.chunking import chunk_text
from services.embedding import generate_embeddings
from services.vector_store import create_index,search
from services.llm import generate_answer

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Backend running"}

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    
    text = extract_text(file.file)
    chunks = chunk_text(text)
    embeddings = generate_embeddings(chunks=chunks)

    create_index(embeddings, chunks)

    return {
        "message": "Document processed",
        "chunks": len(chunks)
    }



@app.get("/search")
def search_chunks(query: str):
    
    query_embedding = generate_embeddings([query])[0]

    results = search(query_embedding)

    return {
        "query": query,
        "results": results
    }

@app.get("/ask")
def ask(query: str):

    try:
        # 1. Convert query → embedding
        query_embedding = generate_embeddings([query])[0]

        # 2. Retrieve relevant chunks
        chunks = search(query_embedding)

        # 3. Combine context
        context = "\n".join(chunks)

        # 4. Generate answer
        answer = generate_answer(context, query)

        return {
            "query": query,
            "answer": answer,
            "chunks_used": chunks
        }

    except Exception as e:
        return {"error": str(e)}