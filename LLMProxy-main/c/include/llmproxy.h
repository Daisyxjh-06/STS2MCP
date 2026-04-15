#ifndef LLMPROXY_H
#define LLMPROXY_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================
   LLMProxy C Client – Public API
   Mirrors the Python implementation.
   All functions that return char* allocate heap memory.
   The caller *must* free() the returned JSON string.
   ============================================================ */

typedef struct {
    const char *endpoint;
    const char *api_key;
    long timeout;       // seconds
} ClientConfig;

/* ------------------------------------------------------------
   Configuration & environment
   ------------------------------------------------------------ */

/**
 * Loads configuration values from environment variables:
 *
 *   LLMPROXY_ENDPOINT
 *   LLMPROXY_API_KEY
 *
 * Also attempts to load a ".env" file in the current directory
 * or parent directory (if present), but does NOT require it.
 *
 * Exits the program if endpoint or api_key are missing.
 *
 * Returns a ClientConfig with pointers to environment strings.
 */
ClientConfig llmproxy_load_config();

/**
 * Loads KEY=VALUE pairs from a .env file into the process
 * environment using setenv().
 *
 * - Blank lines and lines beginning with '#' are ignored.
 * - Quotes around values are stripped.
 * - Missing file is silently ignored.
 *
 * Provided for users who want to manually load .env files.
 */
void load_dotenv(const char *filename);


/* ------------------------------------------------------------
   Public JSON endpoints
   IMPORTANT: All functions return malloc()'d JSON strings.
              Caller must free() the returned pointer.
   ------------------------------------------------------------ */

/**
 * Retrieval endpoint (RAG lookup).
 *
 * Parameters:
 *   query         - text query string
 *   session_id    - unique session identifier
 *   rag_threshold - float threshold for retrieval filtering
 *   rag_k         - how many items to retrieve
 *
 * Returns:
 *   A malloc()'d JSON string. Caller must free().
 */
char *llmproxy_retrieve(
    const ClientConfig *cfg,
    const char *query,
    const char *session_id,
    double rag_threshold,
    int rag_k
);

/**
 * Fetch model info from server.
 *
 * Returns:
 *   A malloc()'d JSON string. Caller must free().
 */
char *llmproxy_model_info(const ClientConfig *cfg);

/**
 * Generation endpoint.
 *
 * Optional parameters must be passed as pointers:
 *   - If NULL, the field is omitted and server defaults apply.
 *
 * Example:
 *   double t = 0.4;
 *   llmproxy_generate(cfg, "model", "sys", "query", &t, NULL, ... );
 *
 * Returns:
 *   A malloc()'d JSON string. Caller must free().
 */
char *llmproxy_generate(
    const ClientConfig *cfg,
    const char *model,
    const char *system,
    const char *query,
    const double *temperature,        // optional → if NULL omitted
    const int    *lastk,              // optional
    const char   *session_id,         // optional, default "GenericSession"
    const double *rag_threshold,      // optional, default 0.5
    const int    *rag_usage,          // optional, default false (0)
    const int    *rag_k               // optional, default 5
);


/* ------------------------------------------------------------
   File / text upload (multipart/form-data)
   ------------------------------------------------------------ */

/**
 * Upload a file via multipart/form-data.
 *
 * Parameters:
 *   filepath    - path to the file on disk
 *   session_id  - session identifier
 *
 * Returns:
 *   A malloc()'d JSON string. Caller must free().
 */
char *llmproxy_upload_file(
    const ClientConfig *cfg,
    const char *filepath,
    const char *session_id
);

/**
 * Upload a raw text string as multipart form data.
 *
 * Returns:
 *   A malloc()'d JSON string. Caller must free().
 */
char *llmproxy_upload_text(
    const ClientConfig *cfg,
    const char *text,
    const char *session_id
);


#ifdef __cplusplus
}
#endif

#endif /* LLMPROXY_H */
