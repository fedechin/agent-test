

from fastapi import FastAPI
from pydantic import BaseModel
from agent_test.rag_chain import build_rag_chain

app = FastAPI()
qa_chain = build_rag_chain()

class Question(BaseModel):
    query: str

@app.post("/ask")
def ask_question(q: Question):
    result = qa_chain.run(q.query)
    return {"answer": result}
