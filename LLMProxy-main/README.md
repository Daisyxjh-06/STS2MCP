# LLMProxy Client Libraries

This repository contains client libraries for interacting with an
LLMProxy backend server.\

The API supports five operations:

-   **generate** --- send a prompt and get model-generated output\
-   **retrieve** --- query previously uploaded or stored content\
-   **upload_text** --- upload raw text for storage, retrieval, and RAG style workflows\
-   **upload_file** --- upload PDFs for storage, retrieval, and RAG style workflows\
-   **model_info** --- to get the list of models available for your subscription plan

These operations are available through **Python** and **C** client
libraries included in this repo.

------------------------------------------------------------------------

## Repository Structure

    .
    ├── c/ # C client (library + header + examples)
    ├── py/ # Python client (package + examples)
    └── README.md # This file

If you plan to use:

-   **Python**, start in [`py/README.md`](py/README.md)\
-   **C**, start in [`c/README.md`](c/README.md)

------------------------------------------------------------------------

## Authentication & Configuration

Both clients require a `.env` file providing:

    LLMPROXY_API_KEY="your-api-key-here"
    LLMPROXY_ENDPOINT="https://a061igc186.execute-api.us-east-1.amazonaws.com/prod"

You can place the `.env` file:

-   inside `py/examples/`
-   inside `c/examples/`
-   or anywhere where you run your program

The clients search for `.env` inside the directory your program is running in.

You will receive your API key from the maintainers of the LLMProxy

------------------------------------------------------------------------

## Getting Started

1.  Acquire an API key for your LLMProxy backend.
2.  Create a `.env` file with the required variables.
3.  Choose a language and follow its README:
    -   [`py/README.md`](py/README.md)
    -   [`c/README.md`](c/README.md)
4.  Run an example program (e.g., `generate` or `model_info`) to verify
    your setup.