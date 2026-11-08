# -*- coding: utf-8 -*-
"""GovDoc UIE SDK - standalone inference for the finetuned govdoc extraction model.

Dependencies: numpy, onnxruntime ONLY. No PaddlePaddle required.

The tokenizer and decoding logic are faithful ports of PaddleNLP 2.6.1
(ErnieTokenizer + Taskflow information_extraction), verified byte-identical
against the official implementation.

Usage:
    from govdoc_sdk import GovDocExtractor
    ex = GovDocExtractor("model.onnx", "vocab.txt")
    result = ex.extract(text, schema=["标题", "发文字号", "成文日期"])
    # result: {"标题": [{"text": ..., "probability": 0.99, "start": 10, "end": 40}], ...}

Integration with regex post-processing (recommended):
    from postprocess import fill_attachment_caption
    r = ex.extract(text, SCHEMA)
    r = fill_attachment_caption(r, text)   # fills 附件说明 when model missed it
"""
import json
import unicodedata

import numpy as np
import onnxruntime as ort

# ---------------------------------------------------------------- tokenizer
# Ported from paddlenlp/transformers/{tokenizer_utils,bert/tokenizer}.py


def _is_whitespace(char):
    if char in (" ", "\t", "\n", "\r"):
        return True
    return unicodedata.category(char) == "Zs"


def _is_control(char):
    if char in ("\t", "\n", "\r"):
        return False
    return unicodedata.category(char).startswith("C")


def _is_punctuation(char):
    cp = ord(char)
    if (33 <= cp <= 47) or (58 <= cp <= 64) or (91 <= cp <= 96) or (123 <= cp <= 126):
        return True
    return unicodedata.category(char).startswith("P")


def _is_symbol(char):
    cp = ord(char)
    if unicodedata.category(char).startswith("S") or cp in [
        0x00AD, 0x00B2, 0x00BA, 0x3007, 0x00B5, 0x00D8, 0x014B, 0x01B1
    ]:
        return True
    return False


def _is_chinese_char(cp):
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0x20000 <= cp <= 0x2A6DF
        or 0x2A700 <= cp <= 0x2B73F
        or 0x2B740 <= cp <= 0x2B81F
        or 0x2B820 <= cp <= 0x2CEAF
        or 0xF900 <= cp <= 0xFAFF
        or 0x2F800 <= cp <= 0x2FA1F
    )


def whitespace_tokenize(text):
    text = text.strip()
    if not text:
        return []
    return text.split()


class BasicTokenizer:
    def __init__(self, do_lower_case=True):
        self.do_lower_case = do_lower_case

    def tokenize(self, text):
        text = self._clean_text(text)
        text = self._tokenize_chinese_chars(text)
        orig_tokens = whitespace_tokenize(text)
        split_tokens = []
        for token in orig_tokens:
            if self.do_lower_case:
                token = token.lower()
                token = self._run_strip_accents(token)
            split_tokens.extend(self._run_split_on_punc(token))
        return whitespace_tokenize(" ".join(split_tokens))

    def _run_strip_accents(self, text):
        text = unicodedata.normalize("NFD", text)
        return "".join([c for c in text if unicodedata.category(c) != "Mn"])

    def _run_split_on_punc(self, text):
        chars = list(text)
        i = 0
        start_new_word = True
        output = []
        while i < len(chars):
            char = chars[i]
            if _is_punctuation(char) or _is_symbol(char):
                output.append([char])
                start_new_word = True
            else:
                if start_new_word:
                    output.append([])
                start_new_word = False
                output[-1].append(char)
            i += 1
        return ["".join(x) for x in output]

    def _tokenize_chinese_chars(self, text):
        output = []
        for char in text:
            if _is_chinese_char(ord(char)):
                output.append(" ")
                output.append(char)
                output.append(" ")
            else:
                output.append(char)
        return "".join(output)

    def _clean_text(self, text):
        output = []
        for char in text:
            cp = ord(char)
            if cp == 0 or cp == 0xFFFD or _is_control(char):
                continue
            if _is_whitespace(char):
                output.append(" ")
            else:
                output.append(char)
        return "".join(output)


class ErnieTokenizerLite:
    """ErnieTokenizer (pure python path): tokenize + id convert + offset mapping."""

    ALL_SPECIAL_TOKENS = {"[UNK]", "[SEP]", "[PAD]", "[CLS]", "[MASK]"}

    def __init__(self, vocab_file, do_lower_case=True):
        self.vocab = {}
        with open(vocab_file, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                token = line.rstrip("\n")
                if token not in self.vocab:
                    self.vocab[token] = len(self.vocab)
        self.vocab_size = len(self.vocab)
        self.do_lower_case = do_lower_case
        self.basic_tokenizer = BasicTokenizer(do_lower_case)
        self.unk_token = "[UNK]"
        self.pad_token_id = self.vocab.get("[PAD]", 0)
        self.cls_token_id = self.vocab.get("[CLS]", 1)
        self.sep_token_id = self.vocab.get("[SEP]", 2)

    # ---- wordpiece (greedy longest match), ported from WordpieceTokenizer
    def _wordpiece(self, text):
        output_tokens = []
        for token in whitespace_tokenize(text):
            chars = list(token)
            if len(chars) > 100:
                output_tokens.append(self.unk_token)
                continue
            is_bad = False
            start = 0
            sub_tokens = []
            while start < len(chars):
                end = len(chars)
                cur_substr = None
                while start < end:
                    substr = "".join(chars[start:end])
                    if start > 0:
                        substr = "##" + substr
                    if substr in self.vocab:
                        cur_substr = substr
                        break
                    end -= 1
                if cur_substr is None:
                    is_bad = True
                    break
                sub_tokens.append(cur_substr)
                start = end
            if is_bad:
                output_tokens.append(self.unk_token)
            else:
                output_tokens.extend(sub_tokens)
        return output_tokens

    def tokenize(self, text):
        return [t for tok in self.basic_tokenizer.tokenize(text) for t in self._wordpiece(tok)]

    def convert_tokens_to_ids(self, tokens):
        unk_id = self.vocab.get(self.unk_token, 0)
        return [self.vocab.get(t, unk_id) for t in tokens]

    # ---- ported from PretrainedTokenizer._get_bert_like_offset_mapping
    def get_offset_mapping(self, text):
        split_tokens = self.tokenize(text)
        normalized_text, char_mapping = "", []
        for i, ch in enumerate(text):
            if self.do_lower_case:
                ch = ch.lower()
                ch = unicodedata.normalize("NFD", ch)
                ch = "".join([c for c in ch if unicodedata.category(c) != "Mn"])
            ch = "".join([c for c in ch if not (ord(c) == 0 or ord(c) == 0xFFFD or _is_control(c))])
            normalized_text += ch
            char_mapping.extend([i] * len(ch))
        text, offset = normalized_text, 0

        char_mapping_indexes = []
        for index, token in enumerate(split_tokens):
            if token[:2] == "##":
                token = token[2:]
            if token in self.ALL_SPECIAL_TOKENS:
                token = token.lower() if self.do_lower_case else token
            if "\u03c3" in token or "\u03c2" in token:  # sigma
                start = text[offset:].replace("\u03c2", "\u03c3").index(token.replace("\u03c2", "\u03c3")) + offset
            else:
                if token not in text[offset:]:
                    if index < len(split_tokens) - 1 and split_tokens[index + 1] in self.ALL_SPECIAL_TOKENS:
                        start = offset
                        token = " "
                    else:
                        start = -1
                else:
                    start = text[offset:].index(token) + offset
            end = start + len(token)
            char_mapping_indexes.append([start, end])
            if start != -1:
                offset = end

        token_mapping = []
        for index, (start, end) in enumerate(char_mapping_indexes):
            if start == -1:
                start = 0 if index == 0 else char_mapping_indexes[index - 1][1]
                end = len(char_mapping) if index == len(char_mapping_indexes) - 1 else char_mapping_indexes[index + 1][0]
            token_mapping.append((char_mapping[start], char_mapping[end - 1] + 1))
        return token_mapping

    # ---- encode a (prompt, text) pair exactly as Taskflow's text_reader does
    def encode_pair(self, prompt, text, max_len=512):
        ids0 = self.convert_tokens_to_ids(self.tokenize(prompt))
        ids1 = self.convert_tokens_to_ids(self.tokenize(text))
        om0 = self.get_offset_mapping(prompt)
        om1 = self.get_offset_mapping(text)

        # truncation (only_second): keep prompt intact, cut text
        max_input = max_len - 3
        if len(ids0) + len(ids1) > max_input:
            keep = max(max_input - len(ids0), 0)
            ids1 = ids1[:keep]
            om1 = om1[:keep]

        input_ids = [self.cls_token_id] + ids0 + [self.sep_token_id] + ids1 + [self.sep_token_id]
        offset_mapping = [[0, 0]] + [list(x) for x in om0] + [[0, 0]] + [list(x) for x in om1] + [[0, 0]]
        seq_len = len(input_ids)

        input_ids += [self.pad_token_id] * (max_len - seq_len)
        position_ids = list(range(seq_len)) + [0] * (max_len - seq_len)
        attention_mask = [1] * seq_len + [0] * (max_len - seq_len)
        offset_mapping += [[0, 0]] * (max_len - seq_len)

        # token_type_ids: standard BERT segment ids (CLS+prompt+SEP = 0, text+SEP = 1),
        # verified against the actual feed captured from official Taskflow.
        token_type_ids = [0] * (len(ids0) + 2) + [1] * (len(ids1) + 1)
        token_type_ids += [0] * (max_len - len(token_type_ids))
        return {
            "input_ids": input_ids,
            "token_type_ids": token_type_ids,
            "position_ids": position_ids,
            "attention_mask": attention_mask,
            "offset_mapping": offset_mapping,
        }


# ---------------------------------------------------------------- decoding
# Ported from paddlenlp/utils/tools.py + taskflow/utils.py


def get_bool_ids_greater_than(probs, limit, return_prob=True):
    probs = np.array(probs)
    if probs.ndim > 1:
        return [get_bool_ids_greater_than(p, limit, return_prob) for p in probs]
    result = []
    for i, p in enumerate(probs):
        if p > limit:
            result.append((i, p) if return_prob else i)
    return result


def get_span(start_ids, end_ids, with_prob=True):
    if with_prob:
        start_ids = sorted(start_ids, key=lambda x: x[0])
        end_ids = sorted(end_ids, key=lambda x: x[0])
    else:
        start_ids = sorted(start_ids)
        end_ids = sorted(end_ids)
    start_pointer, end_pointer = 0, 0
    len_start, len_end = len(start_ids), len(end_ids)
    couple_dict = {}
    while start_pointer < len_start and end_pointer < len_end:
        if with_prob:
            start_id = start_ids[start_pointer][0]
            end_id = end_ids[end_pointer][0]
        else:
            start_id = start_ids[start_pointer]
            end_id = end_ids[end_pointer]
        if start_id == end_id:
            couple_dict[end_ids[end_pointer]] = start_ids[start_pointer]
            start_pointer += 1
            end_pointer += 1
            continue
        if start_id < end_id:
            couple_dict[end_ids[end_pointer]] = start_ids[start_pointer]
            start_pointer += 1
            continue
        if start_id > end_id:
            end_pointer += 1
            continue
    return set((couple_dict[end], end) for end in couple_dict)


def get_id_and_prob(span_set, offset_mapping):
    prompt_end_token_id = offset_mapping[1:].index([0, 0])
    bias = offset_mapping[prompt_end_token_id][1] + 1
    for idx in range(1, prompt_end_token_id + 1):
        offset_mapping[idx][0] -= bias
        offset_mapping[idx][1] -= bias
    sentence_id, prob = [], []
    for start, end in span_set:
        prob.append(start[1] * end[1])
        start_id = offset_mapping[start[0]][0]
        end_id = offset_mapping[end[0]][1]
        sentence_id.append((start_id, end_id))
    return sentence_id, prob


def dbc2sbc(s):
    rs = ""
    for char in s:
        code = ord(char)
        if code == 0x3000:
            code = 0x0020
        else:
            code -= 0xFEE0
        if not (0x0021 <= code <= 0x7E):
            rs += char
            continue
        rs += chr(code)
    return rs


# ---------------------------------------------------------------- extractor


class GovDocExtractor:
    """Single-stage schema extraction with the finetuned govdoc ONNX model.

    Long text is hard-split into chunks of (max_seq_len - max_prompt_len - 3)
    chars, exactly like Taskflow's _auto_splitter with split_sentence=False.
    """

    def __init__(self, onnx_path, vocab_path, position_prob=0.5,
                 max_seq_len=512, batch_size=16):
        self.session = ort.InferenceSession(
            onnx_path, providers=["CPUExecutionProvider"])
        self.tokenizer = ErnieTokenizerLite(vocab_path)
        self.position_prob = position_prob
        self.max_seq_len = max_seq_len
        self.batch_size = batch_size

    def _single_stage(self, text, prompt):
        """Run one (prompt, text) over split chunks; return list of results."""
        max_predict_len = self.max_seq_len - len(prompt) - 3
        chunks = [text[i:i + max_predict_len] for i in range(0, len(text), max_predict_len)] or [""]

        encoded = [self.tokenizer.encode_pair(prompt, c, self.max_seq_len) for c in chunks]
        results = []
        for b in range(0, len(encoded), self.batch_size):
            batch = encoded[b:b + self.batch_size]
            feed = {
                "input_ids": np.array([e["input_ids"] for e in batch], dtype="int64"),
                "token_type_ids": np.array([e["token_type_ids"] for e in batch], dtype="int64"),
                "position_ids": np.array([e["position_ids"] for e in batch], dtype="int64"),
                "attention_mask": np.array([e["attention_mask"] for e in batch], dtype="int64"),
            }
            start_prob, end_prob = self.session.run(None, feed)
            start_ids_list = get_bool_ids_greater_than(start_prob, self.position_prob, True)
            end_ids_list = get_bool_ids_greater_than(end_prob, self.position_prob, True)
            for s_ids, e_ids, enc in zip(start_ids_list, end_ids_list, batch):
                span_set = get_span(s_ids, e_ids, with_prob=True)
                sent_id, probs = get_id_and_prob(span_set, enc["offset_mapping"])
                results.append((sent_id, probs, enc))

        # convert ids to text spans, join chunks with offsets (_auto_joiner)
        out = []
        offset = 0
        for (sent_id, probs, enc), chunk in zip(results, chunks):
            for i in range(len(sent_id)):
                start, end = sent_id[i]
                if start < 0 and end >= 0:
                    continue
                if end < 0:
                    continue  # answer inside prompt: irrelevant for our schema
                out.append({
                    "text": chunk[start:end],
                    "start": start + offset,
                    "end": end + offset,
                    "probability": round(float(probs[i]), 6),
                })
            offset += len(chunk)
        return out

    def extract(self, text, schema):
        """schema: list of field names. Returns {field: [ {text,start,end,probability} ]}."""
        result = {}
        for field in schema:
            result[field] = self._single_stage(text, dbc2sbc(field))
        return result


if __name__ == "__main__":
    import sys
    ex = GovDocExtractor("model/govdoc-uie-medium.onnx", "checkpoint/govdoc300/vocab.txt")
    t = open(sys.argv[1], encoding="utf-8").read().strip() if len(sys.argv) > 1 else "测试"
    schema = ["份号", "密级", "保密期限", "紧急程度", "发文机关标志", "发文字号",
              "标题", "主送机关", "附件说明", "发文机关署名", "成文日期",
              "附注", "抄送机关", "印发机关", "印发日期"]
    print(json.dumps(ex.extract(t, schema), ensure_ascii=False, indent=2))
