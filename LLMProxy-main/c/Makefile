CC      = gcc
CFLAGS  = -Wall -O2 -Iinclude
LDFLAGS = -lcurl

SRC_DIR     = src
INC_DIR     = include
EX_DIR      = examples
BUILD_DIR   = build

LIB_NAME    = libllmproxy.a
LIB_OBJ     = $(BUILD_DIR)/llmproxy.o

EXAMPLES = \
    $(EX_DIR)/example_generate \
    $(EX_DIR)/example_model_info

.PHONY: all clean examples

# ------------ Default Target ------------
all: $(LIB_NAME) examples


# ------------ Build Static Library ------------

$(LIB_NAME): $(LIB_OBJ)
	ar rcs $@ $^


$(BUILD_DIR)/llmproxy.o: $(SRC_DIR)/llmproxy.c $(INC_DIR)/llmproxy.h
	mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@


# ------------ Build Examples ------------

examples: $(EXAMPLES)


$(EX_DIR)/example_generate: $(EX_DIR)/example_generate.c $(LIB_NAME)
	$(CC) $(CFLAGS) -o $@ $< $(LIB_NAME) $(LDFLAGS)


$(EX_DIR)/example_model_info: $(EX_DIR)/example_model_info.c $(LIB_NAME)
	$(CC) $(CFLAGS) -o $@ $< $(LIB_NAME) $(LDFLAGS)


# ------------ Clean ------------

clean:
	rm -rf $(BUILD_DIR) $(LIB_NAME) \
		$(EX_DIR)/example_generate \
		$(EX_DIR)/example_model_info
