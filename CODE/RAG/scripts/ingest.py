from app import config
from app.loaders import load_knowledge_base
from app.vector_store import TelcoVectorStore


def main():
    store = TelcoVectorStore()
    chunks = load_knowledge_base(config.KNOWLEDGE_BASE_DIR)
    count = store.ingest(chunks)
    print(f"Indexed {count} chunks into collection '{config.COLLECTION_NAME}'")


if __name__ == "__main__":
    main()
