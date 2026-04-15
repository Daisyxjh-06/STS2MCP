import requests
from llmproxy import LLMProxy

if __name__ == '__main__':

    # 1. Fetch a webpage
    url = "https://www.eecs.tufts.edu/~abdullah/"
    page = requests.get(url)
    html_text = page.text



    # 2. Create client
    client = LLMProxy()

    # 3. Call LLM with the HTML as the query
    response = client.generate(
        model='4o-mini',
        system=(
            "You will receive the raw HTML of a webpage. "
            "Extract the key findings, important topics, and any key dates. "
            "Respond briefly and clearly."
        ),
        query=html_text,
        temperature=0.0,
        lastk=0,
        session_id='WebSummarySession',
        rag_usage=False,
    )

    print(response)



        query="When was the OSDI paper published?",
