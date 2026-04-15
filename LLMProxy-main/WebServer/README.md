# Web Server
This folder contains an example of a web application (app.py) using Flask and LLMProxy, a simple script(test_query) to test the deployment, and additional files (requirements.txt, Procfile) required for a Koyeb deployment.

## Getting Started
### Creating Koyeb Deployment
    1. Sign-up to the service using this link: https://app.koyeb.com/auth/signup 
    2. Create service and follow steps to link either your Github repo or you could try this public repo example https://github.com/koyeb/example-flask 
    3. Use "Secrets" to add your LLMProxy API key and end-point information. More info at this link https://www.koyeb.com/docs/reference/secrets
    4. Update your deployment with the environment variables where variables names must be "LLMPROXY_ENDPOINT" and "LLMPROXY_API_KEY". Then redeploy with a build triggered option. The `llmproxy` client reads these from the environment; `.env` is only for local development and is not required in Koyeb.
    5. Add a secret `GH_TOKEN` (a GitHub PAT with read access to the repo) so Koyeb can install the package from Git.

### Installing the package in Koyeb

Because Koyeb build environments do not provide SSH, install via HTTPS + token.
You can add this line to `WebServer/requirements.txt` or run it in your build step:

``` bash
pip install "llmproxy @ git+https://${GH_TOKEN}@github.com/Tufts-University/LLMProxy.git@py-v0.1.3#subdirectory=py"
```
    5. Click on the service link and it should open a web page with the mesage "Hello from Koyeb - you reached the main page!".

### Testing Your Deployment
    1. Edit the "test.py" file and replace the links in below lines with your service link - keep the "/query" part in the second line
        response_main = requests.get("https://replace_with_your_web_server_link")
        response_llmproxy = requests.post("https://replace_with_your_web_server_link/query", json=data)
    2. Run the test file locally on your machine and you should receive two responses from the web application and LLMProxy respectively.
