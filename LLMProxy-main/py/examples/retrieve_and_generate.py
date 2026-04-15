from llmproxy import LLMProxy
from string import Template
from time import sleep

def rag_context_string_simple(rag_context):

    """
    Convert the RAG context list (from retrieve API)
    into a single plain-text string that can be appended to a query.
    """

    context_string = ""

    i=1
    for collection in rag_context:
    
        if not context_string:
            context_string = """The following is additional context that may be helpful in answering the user's query."""

        context_string += """
        #{} {}
        """.format(i, collection['doc_summary'])
        j=1
        for chunk in collection['chunks']:
            context_string+= """
            #{}.{} {}
            """.format(i,j, chunk)
            j+=1
        i+=1
    return context_string


if __name__ == '__main__':

    client = LLMProxy()

    # Add several documents to session_id = "RAG"

    # DOC1
    client.upload_text(
        text="""
        Luna was a small robotic explorer built to study remote planets.
        Despite her tiny frame, she carried advanced sensors and an AI core
        designed to learn from every environment she visited.
        Her creators hoped she would uncover signs of ancient civilizations.
        """,
        session_id="RAG",
        strategy="fixed",
    )


    # DOC2
    client.upload_text(
        text="""
        Luna landed on a rocky moon orbiting a gas giant.
        She discovered carvings and metallic fragments buried beneath the dust.
        Her analysis suggested they were remnants of a lost robotic species.
        """,
        session_id="RAG",
        strategy="fixed",
    )



    # sleep so documents are added to session_id=RAG
    sleep(20)

    # Query used to retrieve relevant context
    query = "What did Luna discover during her missions?"


    # assuming some document(s) has previously been uploaded to session_id=RAG
    rag_context = client.retrieve(
        query =query,
        session_id='RAG',
        rag_threshold = 0.2,
        rag_k = 3)

    # combining query with rag_context
    query_with_rag_context = Template("$query\n$rag_context").substitute(
                            query=query,
                            rag_context=rag_context_string_simple(rag_context))

    # Pass to LLM using a different session (session_id=GenericSession)
    # You can also set rag_usage=True to use RAG context from GenericSession
    response = client.generate(model = '4o-mini',
        system="You are a concise scientific assistant",
        query = query_with_rag_context,
        temperature=0.0,
        lastk=0,
        session_id='GenericSession',
        rag_usage = False
        )

    print(response)