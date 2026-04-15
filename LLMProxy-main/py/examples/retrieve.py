from llmproxy import LLMProxy

if __name__ == '__main__':

    client = LLMProxy()
    response = client.retrieve(
        query = 'Tell me about AURA?',
        session_id='GenericSession',
        rag_threshold = 0.3,
        rag_k = 5
    )

    print(response)