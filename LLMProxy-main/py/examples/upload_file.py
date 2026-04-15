from llmproxy import LLMProxy

if __name__ == '__main__':

    client = LLMProxy()
    response = client.upload_file(
        path = 'greentim.pdf',
        session_id = 'GenericSession',
        strategy = 'smart'
    )

    print(response)
