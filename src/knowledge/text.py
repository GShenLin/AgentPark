import re
from functools import lru_cache


@lru_cache(maxsize=1)
def tokenizer():
    import jieba
    instance = jieba.Tokenizer()
    instance.initialize()
    return instance


def tokens(text: str) -> str:
    return " ".join(part.casefold() for part in tokenizer().cut_for_search(text, HMM=False)
                    if any(char.isalnum() for char in part))


def match_query(query: str) -> str:
    terms = list(dict.fromkeys(tokens(query).split()))[:64]
    if not terms:
        raise ValueError("查询必须包含可检索的文字")
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
