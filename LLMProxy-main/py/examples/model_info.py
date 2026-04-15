from llmproxy import LLMProxy
import os

if __name__ == '__main__':


    print("CWD =", os.getcwd())
    
    client = LLMProxy()

    response = client.model_info()
    print(response)
