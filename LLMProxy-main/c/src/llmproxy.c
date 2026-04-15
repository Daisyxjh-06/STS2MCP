#include "llmproxy.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <curl/curl.h>
#include <ctype.h>

/* ------------------------------------------
   Internal buffer for collecting HTTP output
------------------------------------------- */

typedef struct {
    char *data;
    size_t size;
} ResponseBuffer;

static size_t write_cb(void *ptr, size_t size, size_t nmemb, void *userdata) {
    size_t total = size * nmemb;
    ResponseBuffer *buf = (ResponseBuffer *)userdata;

    if (total == 0) {
        return 0;
    }

    char *new_data = realloc(buf->data, buf->size + total + 1);
    if (!new_data) {
        // Out of memory: abort transfer
        free(buf->data);
        buf->data = NULL;
        buf->size = 0;
        return 0; // signals error to libcurl → CURLE_WRITE_ERROR
    }

    buf->data = new_data;
    memcpy(buf->data + buf->size, ptr, total);
    buf->size += total;
    buf->data[buf->size] = '\0';

    return total;
}

/* ------------------------------------------
   Small utilities
------------------------------------------- */

/* Safe trim: removes leading/trailing whitespace in-place */
static char *trim(char *str) {
    if (!str) return str;

    // Trim leading
    while (*str && isspace((unsigned char)*str)) {
        str++;
    }

    if (*str == '\0') {
        // All spaces or empty
        return str;
    }

    // Trim trailing
    char *end = str + strlen(str) - 1;
    while (end > str && isspace((unsigned char)*end)) {
        end--;
    }
    end[1] = '\0';

    return str;
}

/*
 * JSON string escaping:
 *  - escapes backslash, double-quote, and common control characters
 *  - returns newly allocated string; caller must free()
 */
static char *json_escape(const char *s) {
    if (!s) {
        // Represent NULL as empty string
        char *empty = malloc(1);
        if (empty) empty[0] = '\0';
        return empty;
    }

    size_t len = strlen(s);
    size_t extra = 0;

    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)s[i];
        switch (c) {
            case '\\':
            case '\"':
            case '\b':
            case '\f':
            case '\n':
            case '\r':
            case '\t':
                extra++; // will become \x
                break;
            default:
                break;
        }
    }

    char *out = malloc(len + extra + 1);
    if (!out) return NULL;

    char *p = out;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)s[i];
        switch (c) {
            case '\\': *p++ = '\\'; *p++ = '\\'; break;
            case '\"': *p++ = '\\'; *p++ = '\"'; break;
            case '\b': *p++ = '\\'; *p++ = 'b';  break;
            case '\f': *p++ = '\\'; *p++ = 'f';  break;
            case '\n': *p++ = '\\'; *p++ = 'n';  break;
            case '\r': *p++ = '\\'; *p++ = 'r';  break;
            case '\t': *p++ = '\\'; *p++ = 't';  break;
            default:
                *p++ = (char)c;
                break;
        }
    }
    *p = '\0';
    return out;
}

/* ------------------------------------------
   .env loading
------------------------------------------- */

/*
 * Load .env file:
 *  - ignores blank lines
 *  - ignores lines starting with '#'
 *  - parses KEY=VALUE
 *  - sets environment variables using setenv()
 *  - silently ignores missing file
 */
void load_dotenv(const char *filename) {

    FILE *fp = fopen(filename, "r");
    if (!fp) {
        // Not fatal — silently continue
        return;
    }

    char line[4096];

    while (fgets(line, sizeof(line), fp)) {
        char *original = trim(line);

        // Skip comments and blanks
        if (original[0] == '\0' || original[0] == '#')
            continue;

        // Find '='
        char *eq = strchr(original, '=');
        if (!eq) continue;

        // Split into key / value
        *eq = '\0';
        char *key = trim(original);
        char *value = trim(eq + 1);

        // Remove optional surrounding quotes
        size_t vlen = strlen(value);
        if (vlen >= 2 && value[0] == '"' && value[vlen - 1] == '"') {
            value[vlen - 1] = '\0';
            value++;
        }

        // Set environment variable (overwrite = 1)
        setenv(key, value, 1);
    }

    fclose(fp);
}

/* ------------------------------------------
   Config loading
------------------------------------------- */

ClientConfig llmproxy_load_config() {
    ClientConfig cfg;

    // Try .env in current directory and then parent directory
    load_dotenv(".env");

    cfg.endpoint = getenv("LLMPROXY_ENDPOINT");
    cfg.api_key  = getenv("LLMPROXY_API_KEY");
    cfg.timeout  = 80;  // seconds

    if (!cfg.endpoint || !cfg.api_key) {
        fprintf(stderr, "Missing LLMPROXY_ENDPOINT or LLMPROXY_API_KEY\n");
        exit(1);
    }
    return cfg;
}

/* ------------------------------------------
   Build headers
------------------------------------------- */

static struct curl_slist* build_headers(
    const ClientConfig *cfg,
    const char *request_type
) {
    struct curl_slist *headers = NULL;

    char api_key_hdr[512];
    snprintf(api_key_hdr, sizeof(api_key_hdr), "x-api-key: %s", cfg->api_key);

    char type_hdr[256];
    snprintf(type_hdr, sizeof(type_hdr), "request_type: %s", request_type);

    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, api_key_hdr);
    headers = curl_slist_append(headers, type_hdr);

    return headers;
}

/* ------------------------------------------
   Core JSON POST
   Returns malloc'd char* which caller must free()
------------------------------------------- */

static char *post_json(
    const ClientConfig *cfg,
    const char *request_type,
    const char *json_body
) {
    CURL *curl = curl_easy_init();
    if (!curl) return strdup("{\"error\":\"curl init failed\"}");

    ResponseBuffer resp = {0};
    struct curl_slist *headers = build_headers(cfg, request_type);

    curl_easy_setopt(curl, CURLOPT_URL, cfg->endpoint);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_body);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)strlen(json_body));
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, (long)cfg->timeout);

    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &resp);

    CURLcode rc = curl_easy_perform(curl);

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (rc != CURLE_OK) {
        free(resp.data);
        char buf[256];
        snprintf(buf, sizeof(buf),
                 "{\"error\":\"network error: %s\"}",
                 curl_easy_strerror(rc));
        return strdup(buf);
    }

    if (!resp.data) {
        return strdup("{}");
    }
    return resp.data; // caller must free
}

/* ------------------------------------------
   Public JSON endpoints
   All return malloc'd JSON strings; caller must free()
------------------------------------------- */

char *llmproxy_retrieve(
    const ClientConfig *cfg,
    const char *query,
    const char *session_id,
    double rag_threshold,
    int rag_k
) {
    char *e_query = json_escape(query);
    char *e_session = json_escape(session_id);
    if (!e_query || !e_session) {
        free(e_query);
        free(e_session);
        return strdup("{\"error\":\"out of memory\"}");
    }

    size_t buf_size = strlen(e_query) + strlen(e_session) + 128;
    char *body = malloc(buf_size);
    if (!body) {
        free(e_query);
        free(e_session);
        return strdup("{\"error\":\"out of memory\"}");
    }

    snprintf(body, buf_size,
        "{"
        "\"query\":\"%s\","
        "\"session_id\":\"%s\","
        "\"rag_threshold\":%.6f,"
        "\"rag_k\":%d"
        "}",
        e_query, e_session, rag_threshold, rag_k
    );

    free(e_query);
    free(e_session);

    char *res = post_json(cfg, "retrieve", body);
    free(body);
    return res;
}

char *llmproxy_model_info(const ClientConfig *cfg) {
    return post_json(cfg, "model_info", "{}");
}


char *llmproxy_generate(
    const ClientConfig *cfg,
    const char *model,
    const char *system,
    const char *query,
    const double *temperature,        // optional → None
    const int    *lastk,              // optional, default → None
    const char   *session_id,         // optional, defaults → GenericSession
    const double *rag_threshold,      // optional, defaults → 0.5
    const int    *rag_usage,          // optional, defaults → false
    const int    *rag_k               // optional, defaults → 5
) {
    char *e_model  = json_escape(model);
    char *e_system = json_escape(system);
    char *e_query  = json_escape(query);
    const char *sess_raw = session_id ? session_id : "GenericSession";
    char *e_session = json_escape(sess_raw);

    if (!e_model || !e_system || !e_query || !e_session) {
        free(e_model);
        free(e_system);
        free(e_query);
        free(e_session);
        return strdup("{\"error\":\"out of memory\"}");
    }

    double rag_t = rag_threshold ? *rag_threshold : 0.5;
    int rag_u = rag_usage ? *rag_usage : 0;
    int ragk = rag_k ? *rag_k : 5;

    // Over-allocate generously using lengths of escaped strings.
    size_t buf_size =
        strlen(e_model) +
        strlen(e_system) +
        strlen(e_query) +
        strlen(e_session) +
        256; // extra for field names and numbers

    char *body = malloc(buf_size);
    if (!body) {
        free(e_model);
        free(e_system);
        free(e_query);
        free(e_session);
        return strdup("{\"error\":\"out of memory\"}");
    }

    char *p = body;
    p += sprintf(p, "{");

    // Required fields
    p += sprintf(p, "\"model\":\"%s\",",  e_model);
    p += sprintf(p, "\"system\":\"%s\",", e_system);
    p += sprintf(p, "\"query\":\"%s\",",  e_query);

    // Optional fields
    if (temperature != NULL)
        p += sprintf(p, "\"temperature\":%.6f,", *temperature);
    if (lastk != NULL)
        p += sprintf(p, "\"lastk\":%d,", *lastk);

    // Defaults / always-present fields
    p += sprintf(p, "\"session_id\":\"%s\",", e_session);
    p += sprintf(p, "\"rag_threshold\":%.6f,", rag_t);
    p += sprintf(p, "\"rag_usage\":%s,", rag_u ? "true" : "false");
    p += sprintf(p, "\"rag_k\":%d", ragk);

    p += sprintf(p, "}");

    free(e_model);
    free(e_system);
    free(e_query);
    free(e_session);

    char *res = post_json(cfg, "call", body);
    free(body);
    return res;
}

/* ------------------------------------------
   Multipart file upload
   Returns malloc'd JSON string; caller must free()
------------------------------------------- */

char *llmproxy_upload_file(
    const ClientConfig *cfg,
    const char *filepath,
    const char *session_id
) {
    CURL *curl = curl_easy_init();
    if (!curl) return strdup("{\"error\":\"curl init failed\"}");

    ResponseBuffer resp = {0};

    struct curl_slist *headers = NULL;
    char api_key_hdr[512];
    snprintf(api_key_hdr, sizeof(api_key_hdr), "x-api-key: %s", cfg->api_key);

    headers = curl_slist_append(headers, api_key_hdr);
    headers = curl_slist_append(headers, "request_type: add");

    curl_easy_setopt(curl, CURLOPT_URL, cfg->endpoint);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, (long)cfg->timeout);

    curl_mime *mime = curl_mime_init(curl);
    curl_mimepart *part;

    char *e_session = json_escape(session_id);
    if (!e_session) {
        curl_mime_free(mime);
        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
        return strdup("{\"error\":\"out of memory\"}");
    }

    char params[512];
    snprintf(params, sizeof(params),
        "{\"session_id\":\"%s\",\"strategy\":\"smart\"}",
        e_session
    );
    free(e_session);

    // params part
    part = curl_mime_addpart(mime);
    curl_mime_name(part, "params");
    curl_mime_type(part, "application/json");
    curl_mime_data(part, params, CURL_ZERO_TERMINATED);

    // file part
    part = curl_mime_addpart(mime);
    curl_mime_name(part, "file");
    curl_mime_filedata(part, filepath);

    curl_easy_setopt(curl, CURLOPT_MIMEPOST, mime);

    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &resp);

    CURLcode rc = curl_easy_perform(curl);

    curl_mime_free(mime);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (rc != CURLE_OK) {
        free(resp.data);
        char buf[256];
        snprintf(buf, sizeof(buf),
                 "{\"error\":\"network error: %s\"}",
                 curl_easy_strerror(rc));
        return strdup(buf);
    }

    if (!resp.data) {
        return strdup("{}");
    }
    return resp.data;
}

/* ------------------------------------------
   Multipart text upload
   Returns malloc'd JSON string; caller must free()
------------------------------------------- */

char *llmproxy_upload_text(
    const ClientConfig *cfg,
    const char *text,
    const char *session_id
) {
    CURL *curl = curl_easy_init();
    if (!curl) return strdup("{\"error\":\"curl init failed\"}");

    ResponseBuffer resp = {0};

    struct curl_slist *headers = NULL;
    char api_key_hdr[512];
    snprintf(api_key_hdr, sizeof(api_key_hdr), "x-api-key: %s", cfg->api_key);

    headers = curl_slist_append(headers, api_key_hdr);
    headers = curl_slist_append(headers, "request_type: add");

    curl_easy_setopt(curl, CURLOPT_URL, cfg->endpoint);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, (long)cfg->timeout);

    curl_mime *mime = curl_mime_init(curl);
    curl_mimepart *part;

    char *e_session = json_escape(session_id);
    if (!e_session) {
        curl_mime_free(mime);
        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
        return strdup("{\"error\":\"out of memory\"}");
    }

    char params[512];
    snprintf(params, sizeof(params),
        "{\"session_id\":\"%s\",\"strategy\":\"smart\"}",
        e_session
    );
    free(e_session);

    // params part
    part = curl_mime_addpart(mime);
    curl_mime_name(part, "params");
    curl_mime_type(part, "application/json");
    curl_mime_data(part, params, CURL_ZERO_TERMINATED);

    // text part
    part = curl_mime_addpart(mime);
    curl_mime_name(part, "text");
    curl_mime_type(part, "application/text");
    curl_mime_data(part, text, CURL_ZERO_TERMINATED);

    curl_easy_setopt(curl, CURLOPT_MIMEPOST, mime);

    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &resp);

    CURLcode rc = curl_easy_perform(curl);

    curl_mime_free(mime);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (rc != CURLE_OK) {
        free(resp.data);
        char buf[256];
        snprintf(buf, sizeof(buf),
                 "{\"error\":\"network error: %s\"}",
                 curl_easy_strerror(rc));
        return strdup(buf);
    }

    if (!resp.data) {
        return strdup("{}");
    }
    return resp.data;
}


__attribute__((constructor))
static void llmproxy_init(void) {
    curl_global_init(CURL_GLOBAL_DEFAULT);
}

__attribute__((destructor))
static void llmproxy_cleanup(void) {
    curl_global_cleanup();
}