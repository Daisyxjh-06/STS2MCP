from llmproxy import LLMProxy

if __name__ == '__main__':

    client = LLMProxy()

    response = client.generate(
        model='4o-mini',

        system="""

You are a helpful assistant.

Constraints:
- Answer only based on information that you are confident was available before your knowledge cutoff.
- Do NOT claim access to real-time, current, or post-cutoff data.
- Do NOT include specific dates or time references after your knowledge cutoff.
- If a ranking or fact may change over time, explicitly state this uncertainty.
- If you cannot guarantee the temporal accuracy of a claim, say so.

""",

        query="""
What is your model?",
""",

        lastk=0,
        session_id='ass3-model',
        rag_usage=False,
    )

    print(response)
