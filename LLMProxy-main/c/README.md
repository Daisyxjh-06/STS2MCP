# LLMProxy C Client

This directory contains the **C client library** for interacting with an
LLMProxy backend.\
It includes:

-   `llmproxy.h` --- public header\
-   example programs that demonstrate usage

------------------------------------------------------------------------

## Building

From inside the `c/` directory:

``` bash
make
```

This builds:

-   the static library `libllmproxy.a`
-   example binaries inside `c/examples/`

**Dependencies:**\
Requires `libcurl` (installed by default on Linux/macOS).

------------------------------------------------------------------------

## Configuration & Environment Variables

The C client loads a `.env` file **from the current directory**

Your `.env` must contain:


    LLMPROXY_API_KEY="your-api-key-here"
    LLMPROXY_ENDPOINT="https://a061igc186.execute-api.us-east-1.amazonaws.com/prod"


Both variables are required. Missing either one will cause the client to
exit with an error.

Examples:

-   place `.env` inside `c/examples/`
-   OR place `.env` inside any directory you run programs from

------------------------------------------------------------------------

## Core API Functions

All functions return a **malloc'd JSON string** that **you must
`free()`**.

### 1. `llmproxy_generate`

``` c
char *llmproxy_generate(
    const ClientConfig *cfg,
    const char *model,
    const char *system,
    const char *query,
    const double *temperature,   // optional (NULL → omit)
    const int    *lastk,         // optional (NULL → omit)
    const char   *session_id,    // optional (NULL → "GenericSession")
    const double *rag_threshold, // optional (NULL → 0.5)
    const int    *rag_usage,     // optional (NULL → 0)
    const int    *rag_k          // optional (NULL → 5)
);
```

### Notes

-   The request is encoded as JSON and POSTed to the endpoint.
-   Optional parameters are included only when pointers are non-NULL.
-   `session_id` defaults to `"GenericSession"`.

------------------------------------------------------------------------

### 2. `llmproxy_retrieve`

``` c
char *llmproxy_retrieve(
    const ClientConfig *cfg,
    const char *query,
    const char *session_id,
    double rag_threshold,
    int rag_k
);
```

### Notes

-   Signature uses **fixed** threshold/k (not pointers).
-   Both are **required** in C.
-   Query and session ID are JSON-escaped automatically.

------------------------------------------------------------------------

### 3. `llmproxy_upload_file`

``` c
char *llmproxy_upload_file(
    const ClientConfig *cfg,
    const char *filepath,
    const char *session_id
);
```

------------------------------------------------------------------------

### 4. `llmproxy_upload_text`

``` c
char *llmproxy_upload_text(
    const ClientConfig *cfg,
    const char *text,
    const char *session_id
);
```

------------------------------------------------------------------------

### 5. `llmproxy_model_info`

``` c
char *llmproxy_model_info(const ClientConfig *cfg);
```

------------------------------------------------------------------------

## Example: Generate Text

``` c
#include "llmproxy.h"
#include <stdio.h>
#include <stdlib.h>

int main() {
    // Loads .env from current directory
    ClientConfig cfg = llmproxy_load_config();

    char *resp = llmproxy_generate(
        &cfg,
        "4o-mini",
        "Answer humorously",
        "Who are the Jumbos?",
        NULL,    // temperature
        NULL,    // lastk
        NULL,    // session ID (→ GenericSession)
        NULL,    // rag_threshold (→ 0.5)
        NULL,    // rag_usage (→ 0)
        NULL     // rag_k (→ 5)
    );

    printf("%s\n", resp);
    free(resp);
}
```

### Run it:

``` bash
make
./examples/example_generate
```

------------------------------------------------------------------------

## Important Notes

-   All returned strings are **heap allocated** --- always `free()`
    them.

-   JSON escaping is handled automatically for your strings.

-   Missing `.env`, missing API key, or missing endpoint = program
    exits.

------------------------------------------------------------------------

## Recommended Starting Points

-   `c/examples/example_generate.c`
-   `c/examples/example_model_info.c`

These show the correct call structure and required freeing behavior.
