from transformers import pipeline

# Load once on startup
qa_pipeline = pipeline("question-answering", model="distilbert-base-cased-distilled-squad")

def local_qa(query: str, context: str):
    result = qa_pipeline(question=query, context=context)
    return result['answer']
