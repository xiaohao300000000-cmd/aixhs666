from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
import re

from intelligence.text_processing import normalize_text, process_text


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_CJK_CHUNK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_SPLIT_RE = re.compile(r"[\s!?！？。,.，、~～:：;；'\"“”‘’()\[\]{}<>《》/\\|+-]+")

_STOP_TOKENS = {
    "一个",
    "一下",
    "不是",
    "有没有",
    "怎么",
    "怎么样",
    "可以",
    "求问",
    "想问",
    "推荐",
    "孩子",
    "家长",
}

_DOMAIN_TERMS = (
    "二刷",
    "压线",
    "原版娃",
    "机构娃",
    "暑假逆袭",
    "分班考",
    "冲刺",
    "退费",
    "试听",
    "价格",
    "班型",
    "跟不上",
    "求推荐",
    "比较",
    "不满意",
    "报名",
)

_INTENT_TERMS = {
    "local_search": ("求推荐", "有没有", "哪里", "本地", "附近"),
    "price_question": ("价格", "多少钱", "收费", "费用", "贵不贵"),
    "trial_request": ("试听", "体验课", "试课"),
    "exam_retry": ("二刷", "压线", "没过", "失败", "再考"),
    "institution_comparison": ("比较", "对比", "哪家", "机构", "老师"),
    "dissatisfaction": ("不满意", "退费", "效果差", "踩雷"),
}


class ClusterStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"


@dataclass(frozen=True)
class SemanticSignature:
    normalized_text: str
    token_weights: dict[str, float]

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(sorted(self.token_weights))


@dataclass(frozen=True)
class SemanticCluster:
    name: str
    description: str
    representative_examples: tuple[str, ...]
    member_indices: tuple[int, ...]
    status: ClusterStatus = ClusterStatus.CANDIDATE
    signature: SemanticSignature = field(default_factory=lambda: SemanticSignature("", {}))


def build_semantic_signature(text: str | None) -> SemanticSignature:
    normalized = normalize_text(text)
    processed = process_text(normalized)
    weights: Counter[str] = Counter()

    for token in _tokenize(normalized):
        weights[token] += 1.0
    for region in processed.fields.regions:
        weights[f"region:{region}"] += 2.0
    for exam in processed.fields.exams:
        weights[f"exam:{exam.upper()}"] += 2.4
    for grade in processed.fields.grades:
        weights[f"grade:{grade}"] += 1.8
    for institution in processed.fields.institution_candidates:
        weights[f"institution:{institution}"] += 2.0
    for intent, terms in _INTENT_TERMS.items():
        if any(term.casefold() in normalized.casefold() for term in terms):
            weights[f"intent:{intent}"] += 1.6

    return SemanticSignature(normalized_text=normalized, token_weights=dict(weights))


def semantic_similarity(left: SemanticSignature, right: SemanticSignature) -> float:
    if not left.token_weights or not right.token_weights:
        return 0.0

    tokens = set(left.token_weights) | set(right.token_weights)
    intersection = sum(min(left.token_weights.get(token, 0.0), right.token_weights.get(token, 0.0)) for token in tokens)
    union = sum(max(left.token_weights.get(token, 0.0), right.token_weights.get(token, 0.0)) for token in tokens)
    return intersection / union if union else 0.0


def cluster_texts(
    texts: list[str] | tuple[str, ...],
    *,
    similarity_threshold: float = 0.18,
    max_representative_examples: int = 3,
) -> list[SemanticCluster]:
    signatures = [build_semantic_signature(text) for text in texts]
    cluster_members: list[list[int]] = []
    cluster_signatures: list[SemanticSignature] = []

    for index, signature in sorted(enumerate(signatures), key=lambda item: (item[1].normalized_text, item[0])):
        if not signature.token_weights:
            cluster_members.append([index])
            cluster_signatures.append(signature)
            continue

        best_cluster_index: int | None = None
        best_score = 0.0
        for cluster_index, cluster_signature in enumerate(cluster_signatures):
            score = semantic_similarity(signature, cluster_signature)
            if score > best_score:
                best_score = score
                best_cluster_index = cluster_index

        if best_cluster_index is not None and best_score >= similarity_threshold:
            cluster_members[best_cluster_index].append(index)
            cluster_signatures[best_cluster_index] = _merge_signatures(
                [signatures[member_index] for member_index in cluster_members[best_cluster_index]]
            )
        else:
            cluster_members.append([index])
            cluster_signatures.append(signature)

    clusters = [
        _build_cluster(members, cluster_signatures[index], signatures, texts, max_representative_examples)
        for index, members in enumerate(cluster_members)
    ]
    return sorted(clusters, key=lambda cluster: (cluster.name, cluster.member_indices))


def _tokenize(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    lowered = text.casefold()
    for term in _DOMAIN_TERMS:
        if term.casefold() in lowered:
            tokens.append(term)
    for ascii_token in _ASCII_TOKEN_RE.findall(text):
        tokens.append(ascii_token.upper() if len(ascii_token) <= 4 else ascii_token.casefold())
    for chunk in _CJK_CHUNK_RE.findall(text):
        tokens.extend(_cjk_ngrams(chunk))
    return tuple(token for token in tokens if token and token not in _STOP_TOKENS)


def _cjk_ngrams(chunk: str) -> list[str]:
    compact = "".join(part for part in _SPLIT_RE.split(chunk) if part)
    grams: list[str] = []
    for size in (2, 3, 4):
        if len(compact) < size:
            continue
        grams.extend(compact[index : index + size] for index in range(len(compact) - size + 1))
    return grams


def _merge_signatures(signatures: list[SemanticSignature]) -> SemanticSignature:
    totals: Counter[str] = Counter()
    for signature in signatures:
        totals.update(signature.token_weights)
    count = len(signatures)
    averaged = {token: weight / count for token, weight in totals.items()}
    return SemanticSignature(normalized_text=" ".join(signature.normalized_text for signature in signatures), token_weights=averaged)


def _build_cluster(
    members: list[int],
    signature: SemanticSignature,
    signatures: list[SemanticSignature],
    texts: list[str] | tuple[str, ...],
    max_representative_examples: int,
) -> SemanticCluster:
    sorted_members = tuple(sorted(members))
    representatives = _representative_examples(sorted_members, signatures, texts, signature, max_representative_examples)
    label_tokens = _label_tokens(signature)
    name = " / ".join(label_tokens[:3]) if label_tokens else "未分类表达"
    return SemanticCluster(
        name=name,
        description=f"{len(sorted_members)} 条文本围绕 {name}",
        representative_examples=representatives,
        member_indices=sorted_members,
        signature=signature,
    )


def _representative_examples(
    member_indices: tuple[int, ...],
    signatures: list[SemanticSignature],
    texts: list[str] | tuple[str, ...],
    cluster_signature: SemanticSignature,
    max_examples: int,
) -> tuple[str, ...]:
    ranked = sorted(
        member_indices,
        key=lambda index: (-semantic_similarity(signatures[index], cluster_signature), index),
    )
    return tuple(normalize_text(texts[index]) for index in ranked[:max_examples])


def _label_tokens(signature: SemanticSignature) -> list[str]:
    labels: list[str] = []
    for token, _weight in sorted(signature.token_weights.items(), key=lambda item: (-item[1], item[0])):
        if ":" in token:
            labels.append(token.split(":", 1)[1])
        elif len(token) >= 2:
            labels.append(token)
        if len(labels) >= 3:
            break
    return labels
