import os
os.environ['OPENAI_API_KEY'] = 'sk-zS5Y7PQWgxzn4Hk151Af2uZ1PFRXN4mwVJM6Zfp9taYEIPau'
os.environ['OPENAI_BASE_URL'] = 'https://api.chatanywhere.tech'
os.environ['EMBEDDING_MODEL'] = 'text-embedding-3-small'

from pymilvus import MilvusClient
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app import create_app, db
from app.models.document import Document

app = create_app('development')
with app.app_context():
    embeddings = OpenAIEmbeddings(
        model='text-embedding-3-small',
        api_key='sk-zS5Y7PQWgxzn4Hk151Af2uZ1PFRXN4mwVJM6Zfp9taYEIPau',
        base_url='https://api.chatanywhere.tech'
    )
    
    client = MilvusClient(uri='http://192.168.52.176:19530')
    
    docs = Document.query.filter_by(status='published').filter(Document.deleted_at.is_(None)).all()
    print(f'Found {len(docs)} published documents')
    
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    
    for doc in docs:
        if doc.content:
            print(f'Processing doc {doc.id}: {doc.title[:30]}...')
            chunks = text_splitter.split_text(doc.content)
            print(f'  Split into {len(chunks)} chunks')
            
            vectors = embeddings.embed_documents(chunks)
            print(f'  Generated {len(vectors)} embeddings')
            
            data = []
            for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
                data.append({
                    'text': chunk,
                    'vector': vector,
                    'document_id': doc.id,
                    'chunk_index': i
                })
            
            res = client.insert(collection_name='wiki_embeddings', data=data)
            print(f'  Inserted vectors: {res}')
    
    client.flush('wiki_embeddings')
    info = client.get_collection_stats('wiki_embeddings')
    row_count = info['row_count']
    print(f'Total vectors: {row_count}')
    client.close()
    print('Done!')
